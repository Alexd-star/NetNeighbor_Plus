import os
import platform
import socket
import threading
from typing import Optional, Dict, Any

import toml


_config: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()


def get_config_dir() -> str:
    """获取用户专属的配置文件夹路径，确保文件夹存在。"""
    system = platform.system()
    if system == "Windows":
        path = os.path.join(os.environ["APPDATA"], "NetNeighbor_Plus")
    else:
        path = os.path.join(os.path.expanduser("~"), ".config", "NetNeighbor_Plus")

    os.makedirs(path, exist_ok=True)
    return path


CONFIG_PATH = os.path.join(get_config_dir(), "config.toml")


def create_default_config() -> Dict[str, Any]:
    """创建一个全新的、安全的默认配置文件内容。"""
    print("检测到首次运行，正在创建新的默认配置文件...")
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "My-New-PC"

    return {
        "service": {"name": hostname, "port": 8080},
        "shares": [],
    }


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    加载并返回TOML配置文件内容。
    如果配置文件不存在，则自动创建一份新的。
    """
    global _config
    with _config_lock:
        if _config is None or force_reload:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    _config = toml.load(f)
            except FileNotFoundError:
                print(f"未找到配置文件于 '{CONFIG_PATH}'")
                _config = create_default_config()
                try:
                    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                        toml.dump(_config, f)
                    print(f"新的配置文件已成功创建于: {CONFIG_PATH}")
                except Exception as e:
                    print(f"错误：无法写入新的配置文件 - {e}")
            except Exception as e:
                print(f"错误：读取配置文件 {CONFIG_PATH} 失败 - {e}")
                _config = create_default_config()

        return _config if _config is not None else create_default_config()


def get_config() -> Dict[str, Any]:
    """获取当前加载的配置，如果从未加载则先加载。"""
    return load_config()


def get_shares() -> list:
    """安全地获取共享列表。"""
    return get_config().get("shares", [])
