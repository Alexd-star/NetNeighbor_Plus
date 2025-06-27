# 文件: core/config.py
import toml
from typing import Optional, Dict, Any

def load_config(path="config.toml") -> Optional[Dict[str, Any]]:
    """加载并返回TOML配置文件内容。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return toml.load(f)
    except FileNotFoundError:
        print(f"错误：找不到配置文件 {path} ！请确保它在项目根目录。")
        exit(1)
    except Exception as e:
        print(f"错误：读取配置文件 {path} 失败 - {e}")
        exit(1)

# 全局配置对象
config = load_config()