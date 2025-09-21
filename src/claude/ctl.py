#!/usr/bin/env python3
"""
Claude服务控制器 - 使用优化后的基础类
"""
from ..core.base_proxy import BaseServiceController
from ..config.cached_config_manager import claude_config_manager

class ClaudeController(BaseServiceController):
    """
    Claude服务控制器
    """
    def __init__(self):
        super().__init__(
            service_name='claude',
            port=3210,
            config_manager=claude_config_manager,
            proxy_module_path='src.claude.proxy'
        )
        # 为了兼容性，设置旧的PID文件名
        self.pid_file = self.config_dir / 'claude_code_proxy.pid'

# 创建全局实例
controller = ClaudeController()

# 兼容性函数（保持原有接口）
def get_pid():
    return controller.get_pid()

def is_running():
    return controller.is_running()

def start():
    return controller.start()

def stop():
    return controller.stop()

def restart():
    return controller.restart()

def status():
    controller.status()

# 兼容旧版本的函数
def start_daemon(port=3210):
    """启动守护进程（兼容旧接口）"""
    return start()

def stop_handler(signum, frame):
    """停止信号处理函数（兼容旧接口）"""
    stop()

# 导出配置目录等路径（为了兼容性）
from pathlib import Path
config_dir = Path.home() / '.clp/run'
data_dir = Path.home() / '.clp/data'
PID_FILE = controller.pid_file
LOG_FILE = controller.log_file

# 添加缺失的函数
def set_active_config(config_name):
    """设置激活配置"""
    if claude_config_manager.set_active_config(config_name):
        print(f"Claude配置已切换到: {config_name}")
        return True
    else:
        print(f"配置 {config_name} 不存在")
        return False

def list_configs():
    """列出所有配置"""
    configs = claude_config_manager.configs
    active = claude_config_manager.active_config
    
    if not configs:
        print("Claude: 没有可用配置")
        return
    
    print("Claude 可用配置:")
    for name in configs:
        if name == active:
            print(f"  * {name} (激活)")
        else:
            print(f"    {name}")