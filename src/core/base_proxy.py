#!/usr/bin/env python3
"""
基础代理服务类 - 消除claude和codex的重复代码
提供统一的代理服务实现
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
from abc import ABC
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..utils.usage_parser import (
    extract_usage_from_response,
    normalize_usage_record,
)
from ..utils.platform_helper import create_detached_process

class BaseProxyService(ABC):
    """基础代理服务类"""
    
    def __init__(self, service_name: str, port: int, config_manager):
        """
        初始化代理服务
        
        Args:
            service_name: 服务名称 (claude/codex)
            port: 服务端口
            config_manager: 配置管理器实例
        """
        self.service_name = service_name
        self.port = port
        self.config_manager = config_manager

        # 初始化路径
        self.config_dir = Path.home() / '.clp/run'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file = self.config_dir / f'{service_name}_proxy.pid'
        self.log_file = self.config_dir / f'{service_name}_proxy.log'
        
        # 数据目录
        self.data_dir = Path.home() / '.clp/data'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.traffic_log = self.data_dir / 'proxy_requests.jsonl'
        old_log = self.data_dir / 'traffic_statistics.jsonl'
        if not self.traffic_log.exists() and old_log.exists():
            try:
                old_log.rename(self.traffic_log)
            except OSError:
                # 如果重命名失败，则保留旧文件并继续使用旧路径
                self.traffic_log = old_log
        
        # 初始化异步HTTP客户端
        self.client = self._create_async_client()

        # 响应日志截断阈值（避免长流占用过多内存）
        self.max_logged_response_bytes = 1024 * 1024  # 1MB

        # 初始化FastAPI应用
        self.app = FastAPI()
        self._setup_routes()
        self.app.add_event_handler("shutdown", self._shutdown_event)
        
        # 导入过滤器
        try:
            from ..filter.cached_request_filter import CachedRequestFilter
            self.request_filter = CachedRequestFilter()
        except ImportError:
            # 如果缓存版本不存在，使用原版本
            from ..filter.request_filter import filter_request_data
            self.filter_request_data = filter_request_data
            self.request_filter = None
    
    def _create_async_client(self) -> httpx.AsyncClient:
        """创建并配置 httpx AsyncClient"""
        timeout = httpx.Timeout(  # 允许长时间流式响应
            timeout=None,
            connect=30.0,
            read=None,
            write=30.0,
            pool=None,
        )
        limits = httpx.Limits(
            max_connections=200,
            max_keepalive_connections=100,
        )
        return httpx.AsyncClient(timeout=timeout, limits=limits, headers={"Connection": "keep-alive"})

    async def _shutdown_event(self):
        """FastAPI 关闭事件，释放HTTP客户端资源"""
        await self.client.aclose()

    def _setup_routes(self):
        """设置API路由"""
        @self.app.api_route(
            "/{path:path}",
            methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']
        )
        async def proxy_route(path: str, request: Request):
            return await self.proxy(path, request)

    async def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        target_headers: Optional[Dict] = None,
        filtered_body: Optional[bytes] = None,
        original_headers: Optional[Dict] = None,
        original_body: Optional[bytes] = None,
        response_content: Optional[bytes] = None,
        channel: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        response_truncated: bool = False,
        total_response_bytes: Optional[int] = None,
        target_url: Optional[str] = None,
    ):
        """记录请求日志到jsonl文件（异步调度）"""

        def _write_log():
            try:
                log_entry = {
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'service': self.service_name,
                    'method': method,
                    'path': target_url if target_url else path,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                    'target_headers': target_headers or {}
                }

                if channel:
                    log_entry['channel'] = channel

                if filtered_body:
                    log_entry['filtered_body'] = base64.b64encode(filtered_body).decode('utf-8')

                if original_headers:
                    log_entry['original_headers'] = original_headers

                if original_body:
                    log_entry['original_body'] = base64.b64encode(original_body).decode('utf-8')

                usage_record = usage
                if usage_record is None:
                    usage_record = extract_usage_from_response(self.service_name, response_content)
                usage_record = normalize_usage_record(self.service_name, usage_record)
                log_entry['usage'] = usage_record

                if response_content:
                    log_entry['response_content'] = base64.b64encode(response_content).decode('utf-8')

                if response_truncated:
                    log_entry['response_truncated'] = True

                if total_response_bytes is not None:
                    log_entry['response_bytes'] = total_response_bytes

                with open(self.traffic_log, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            except Exception as exc:
                print(f"日志记录失败: {exc}")

        await asyncio.to_thread(_write_log)

    def build_target_param(self, path: str, request: Request, body: bytes) -> Tuple[str, Dict, bytes, Optional[str]]:
        """
        构建请求参数

        Returns:
            (target_url, headers, body, active_config_name)
        """
        # 从配置管理器获取配置
        active_config_name = self.config_manager.active_config
        config_data = self.config_manager.configs.get(active_config_name)
        
        if not config_data:
            raise ValueError(f"未找到激活配置: {active_config_name}")
        
        # 构建目标URL
        base_url = config_data['base_url'].rstrip('/')
        normalized_path = path.lstrip('/')
        target_url = f"{base_url}/{normalized_path}" if normalized_path else base_url

        raw_query = request.url.query
        if raw_query:
            target_url = f"{target_url}?{raw_query}"

        # 处理headers，排除会被重新设置的头
        excluded_headers = {'authorization', 'host', 'content-length'}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded_headers}
        headers['host'] = urlsplit(target_url).netloc
        headers.setdefault('connection', 'keep-alive')
        if config_data.get('api_key'):
            headers['x-api-key'] = config_data['api_key']
        if config_data.get('auth_token'):
            headers['authorization'] = f'Bearer {config_data["auth_token"]}'

        return target_url, headers, body, active_config_name

    def apply_request_filter(self, data: bytes) -> bytes:
        """应用请求过滤器"""
        if self.request_filter:
            # 使用缓存版本的过滤器
            return self.request_filter.apply_filters(data)
        else:
            # 使用原版本的过滤器
            return self.filter_request_data(data)
    
    async def proxy(self, path: str, request: Request):
        """处理代理请求"""
        start_time = time.time()

        original_headers = {k: v for k, v in request.headers.items()}
        original_body = await request.body()

        active_config_name: Optional[str] = None
        target_headers: Optional[Dict[str, str]] = None
        filtered_body: Optional[bytes] = None
        target_url: Optional[str] = None

        try:
            target_url, target_headers, target_body, active_config_name = self.build_target_param(path, request, original_body)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

        # 应用请求过滤器，放到线程池避免阻塞事件循环
        filtered_body = await asyncio.to_thread(self.apply_request_filter, target_body)

        # 检测是否需要流式传输
        headers_lower = {k.lower(): v for k, v in original_headers.items()}
        x_stainless_helper_method = headers_lower.get('x-stainless-helper-method', '').lower()
        content_type = headers_lower.get('content-type', '').lower()
        accept = headers_lower.get('accept', '').lower()
        is_stream = (
            'text/event-stream' in accept or
            'text/event-stream' in content_type or
            'stream' in content_type or
            'application/x-ndjson' in content_type or
            "stream" in x_stainless_helper_method
        )

        try:
            request_out = self.client.build_request(
                method=request.method,
                url=target_url,
                headers=target_headers,
                content=filtered_body if filtered_body else None,
            )
            response = await self.client.send(request_out, stream=is_stream)

            duration_ms = int((time.time() - start_time) * 1000)
            status_code = response.status_code

            # 构造返回头，移除跳跃性头信息
            excluded_response_headers = {'connection', 'transfer-encoding'}
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in excluded_response_headers
            }

            collected = bytearray()
            total_response_bytes = 0
            response_truncated = False

            async def iterator():
                nonlocal response_truncated, total_response_bytes
                try:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        total_response_bytes += len(chunk)
                        if len(collected) < self.max_logged_response_bytes:
                            remaining = self.max_logged_response_bytes - len(collected)
                            collected.extend(chunk[:remaining])
                            if len(chunk) > remaining:
                                response_truncated = True
                        else:
                            response_truncated = True
                        yield chunk
                finally:
                    await response.aclose()
                    response_content = bytes(collected) if collected else None
                    await self.log_request(
                        method=request.method,
                        path=path,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        target_headers=target_headers,
                        filtered_body=filtered_body,
                        original_headers=original_headers,
                        original_body=original_body,
                        response_content=response_content,
                        channel=active_config_name,
                        response_truncated=response_truncated,
                        total_response_bytes=total_response_bytes,
                        target_url=target_url,
                    )

            return StreamingResponse(
                iterator(),
                status_code=status_code,
                headers=response_headers
            )
        except httpx.RequestError as exc:
            duration_ms = int((time.time() - start_time) * 1000)

            if isinstance(exc, httpx.ConnectTimeout):
                error_msg = "连接超时"
            elif isinstance(exc, httpx.ReadTimeout):
                error_msg = "响应读取超时"
            elif isinstance(exc, httpx.ConnectError):
                error_msg = "连接错误"
            elif isinstance(exc, httpx.HTTPStatusError):
                error_msg = "上游返回错误状态"
            else:
                error_msg = "请求失败"

            response_data = {"error": error_msg, "detail": str(exc)}
            status_code = 500

            await self.log_request(
                method=request.method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                target_headers=target_headers,
                filtered_body=filtered_body,
                original_headers=original_headers,
                original_body=original_body,
                channel=active_config_name,
                target_url=target_url
            )

            return JSONResponse(response_data, status_code=status_code)

    def run_app(self):
        """启动代理服务"""
        import os
        # 切换到项目根目录
        project_root = Path(__file__).parent.parent.parent
        
        # 在daemon环境中，需要明确指定环境和重定向
        env = os.environ.copy()
        
        try:
            with open(self.log_file, 'a') as log_file:
                uvicorn_cmd = [
                    sys.executable, '-m', 'uvicorn',
                    f'src.{self.service_name}.proxy:app',
                    '--host', '0.0.0.0',
                    '--port', str(self.port),
                    '--http', 'h11',
                    '--timeout-keep-alive', '60',
                    '--limit-concurrency', '500',
                ]
                subprocess.run(
                    uvicorn_cmd,
                    cwd=str(project_root),
                    env=env,
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL
                )
                print(f"启动{self.service_name}代理成功 在端口 {self.port}")
        except Exception as e:
            print(f"启动{self.service_name}代理失败: {e}")


class BaseServiceController(ABC):
    """基础服务控制器类"""
    
    def __init__(self, service_name: str, port: int, config_manager, proxy_module_path: str):
        """
        初始化服务控制器
        
        Args:
            service_name: 服务名称
            port: 服务端口
            config_manager: 配置管理器实例
            proxy_module_path: 代理模块路径 (如 'src.claude.proxy')
        """
        self.service_name = service_name
        self.port = port
        self.config_manager = config_manager
        self.proxy_module_path = proxy_module_path
        
        # 初始化路径
        self.config_dir = Path.home() / '.clp/run'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file = self.config_dir / f'{service_name}_proxy.pid'
        self.log_file = self.config_dir / f'{service_name}_proxy.log'
    
    def get_pid(self) -> Optional[int]:
        """获取服务进程PID"""
        if self.pid_file.exists():
            try:
                return int(self.pid_file.read_text().strip())
            except:
                return None
        return None
    
    def is_running(self) -> bool:
        """检查服务是否在运行"""
        import psutil
        pid = self.get_pid()
        if pid:
            try:
                process = psutil.Process(pid)
                return process.is_running()
            except psutil.NoSuchProcess:
                return False
        return False
    
    def start(self) -> bool:
        """启动服务"""
        if self.is_running():
            print(f"{self.service_name}服务已经在运行")
            return False
        
        config_file_path = None
        ensure_file_fn = getattr(self.config_manager, 'ensure_config_file', None)
        if callable(ensure_file_fn):
            config_file_path = ensure_file_fn()
        elif hasattr(self.config_manager, 'config_file'):
            config_file_path = getattr(self.config_manager, 'config_file')

        # 检查配置
        configs = self.config_manager.configs
        if not configs:
            if config_file_path:
                print(f"警告: {self.service_name}配置为空，将以占位模式启动。请编辑 {config_file_path} 补充配置后重启。")
            else:
                print(f"警告: 未检测到{self.service_name}配置文件，将以占位模式启动。")
        
        import os
        project_root = Path(__file__).parent.parent.parent
        env = os.environ.copy()
        
        uvicorn_cmd = [
            sys.executable, '-m', 'uvicorn',
            f'{self.proxy_module_path}:app',
            '--host', '0.0.0.0',
            '--port', str(self.port),
            '--http', 'h11',
            '--timeout-keep-alive', '60',
            '--limit-concurrency', '500',
        ]
        with open(self.log_file, 'a') as log_handle:
            # 在独立进程组中运行，避免控制台信号终止子进程
            process = create_detached_process(
                uvicorn_cmd,
                log_handle,
                cwd=str(project_root),
                env=env,
            )

        # 保存PID
        self.pid_file.write_text(str(process.pid))

        # 等待服务启动
        time.sleep(1)

        if self.is_running():
            print(f"{self.service_name}服务启动成功 (端口: {self.port})")
            return True
        else:
            print(f"{self.service_name}服务启动失败")
            return False
    
    def stop(self) -> bool:
        """停止服务"""
        import psutil
        
        if not self.is_running():
            print(f"{self.service_name}服务未运行")
            return False
        
        pid = self.get_pid()
        if pid:
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
            except psutil.NoSuchProcess:
                pass
            
            # 清理PID文件
            if self.pid_file.exists():
                self.pid_file.unlink()
            
            print(f"{self.service_name}服务已停止")
            return True
        
        return False
    
    def restart(self) -> bool:
        """重启服务"""
        self.stop()
        time.sleep(1)
        return self.start()
    
    def status(self):
        """查看服务状态"""
        if self.is_running():
            pid = self.get_pid()
            active_config = self.config_manager.active_config
            print(f"{self.service_name}服务: 运行中 (PID: {pid}, 配置: {active_config})")
        else:
            print(f"{self.service_name}服务: 未运行")
