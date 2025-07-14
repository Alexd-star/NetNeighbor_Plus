import os
import platform
import socket
import threading
import time
from typing import Optional, Dict, Any

import toml


_config: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()
_config_file_mtime: Optional[float] = None
_config_dir_cache: Optional[str] = None


def get_config_dir() -> str:
    """获取用户专属的配置文件夹路径，确保文件夹存在。使用缓存避免重复计算。"""
    global _config_dir_cache
    if _config_dir_cache is not None:
        return _config_dir_cache

    system = platform.system()
    if system == "Windows":
        path = os.path.join(os.environ["APPDATA"], "NetNeighbor_Plus")
    else:
        path = os.path.join(os.path.expanduser("~"), ".config", "NetNeighbor_Plus")

    os.makedirs(path, exist_ok=True)
    _config_dir_cache = path
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


def _check_config_file_changed() -> bool:
    """检查配置文件是否已被修改"""
    global _config_file_mtime
    try:
        current_mtime = os.path.getmtime(CONFIG_PATH)
        if _config_file_mtime is None or current_mtime != _config_file_mtime:
            _config_file_mtime = current_mtime
            return True
        return False
    except OSError:
        # 文件不存在或无法访问
        return True


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    加载并返回TOML配置文件内容。
    如果配置文件不存在，则自动创建一份新的。
    使用文件修改时间检测避免不必要的重新加载。
    """
    global _config
    with _config_lock:
        # 只有在强制重载或配置未加载或文件已修改时才重新加载
        if _config is None or force_reload or _check_config_file_changed():
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
                    # 更新文件修改时间
                    _check_config_file_changed()
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


def invalidate_config_cache():
    """使配置缓存失效，强制下次访问时重新加载"""
    global _config, _config_file_mtime
    with _config_lock:
        _config = None
        _config_file_mtime = None
