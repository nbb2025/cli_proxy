# 使用缓存版本的配置管理器
from ..config.cached_config_manager import claude_config_manager

# 直接暴露config_manager的接口
def get_active_config():
    return claude_config_manager.active_config

def get_configs():
    return claude_config_manager.configs