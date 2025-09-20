# 使用缓存版本的配置管理器
from ..config.cached_config_manager import codex_config_manager

# 直接暴露config_manager的接口
def get_active_config():
    return codex_config_manager.active_config

def get_configs():
    return codex_config_manager.configs