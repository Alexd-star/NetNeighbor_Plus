# 文件: core/config_loader.py (新文件)
import toml
from typing import Optional, Dict, Any
import threading

# 全局配置变量和用于保护它的锁
_config: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()
CONFIG_PATH = "config.toml"

def load_config(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """
    加载并返回TOML配置文件内容。
    使用锁来确保线程安全。
    如果配置已加载，默认直接返回内存中的版本，除非强制重新加载。
    """
    global _config
    with _config_lock:
        if _config is None or force_reload:
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    _config = toml.load(f)
                print(f"配置文件 '{CONFIG_PATH}' 已{'重新' if force_reload else ''}加载。")
            except FileNotFoundError:
                print(f"错误：找不到配置文件 {CONFIG_PATH} ！请确保它在项目根目录。")
                # 在找不到配置文件时，返回一个基本的、可用的结构，避免程序崩溃
                _config = {"service": {"name": "DefaultPC", "port": 8080}, "shares": []}
                # exit(1) # 在GUI应用中，不应直接退出，而是允许应用启动并提示用户
            except Exception as e:
                print(f"错误：读取配置文件 {CONFIG_PATH} 失败 - {e}")
                # 同样，返回一个安全默认值
                _config = {"service": {"name": "DefaultPC", "port": 8080}, "shares": []}
                # exit(1)
        return _config

def get_config() -> Dict[str, Any]:
    """获取当前加载的配置，如果从未加载则先加载。"""
    config = load_config()
    # load_config 内部处理了None的情况，理论上这里不会是None
    return config if config is not None else {}

def get_shares() -> list:
    """安全地获取共享列表。"""
    return get_config().get("shares", [])