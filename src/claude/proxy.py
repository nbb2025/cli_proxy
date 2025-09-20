#!/usr/bin/env python3
"""
Claude代理服务 - 使用优化后的基础类
"""
from ..core.base_proxy import BaseProxyService
from ..config.cached_config_manager import claude_config_manager

class ClaudeProxy(BaseProxyService):
    """Claude代理服务实现"""
    
    def __init__(self):
        super().__init__(
            service_name='claude',
            port=3210,
            config_manager=claude_config_manager
        )

# 创建全局实例
proxy_service = ClaudeProxy()
app = proxy_service.app

# log_request 方法已在基类中实现

# 路由已在基类的 _setup_routes 中设置

# build_target_param 方法已在基类中实现

def run_app(port=3210):
    """启动Claude代理服务"""
    proxy_service.run_app()

if __name__ == '__main__':
    # 调试模式直接运行Uvicorn
    import uvicorn

    uvicorn.run(
        app,
        host='0.0.0.0',
        port=3210,
        log_level='info',
        timeout_keep_alive=60,
        http='h11'
    )
