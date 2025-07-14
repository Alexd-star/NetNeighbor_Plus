import os
from typing import Dict, Any, Tuple
from fastapi import HTTPException

from .config_loader import load_config


def get_safe_path_and_share(
    share_name: str, sub_path: str = "/", require_permission: str = None
) -> Tuple[str, Dict[str, Any]]:
    """
    安全地解析请求的路径，防止路径遍历攻击，并返回共享配置。
    
    Args:
        share_name: 共享名称
        sub_path: 子路径
        require_permission: 需要的权限（如 "download", "upload"）
        
    Returns:
        Tuple[str, Dict]: (完整路径, 共享配置)
        
    Raises:
        HTTPException: 当共享不存在、权限不足或路径不安全时
        FileNotFoundError: 当共享不存在时（用于TCP服务器）
        PermissionError: 当权限不足或路径不安全时（用于TCP服务器）
    """
    all_shares = load_config().get("shares", [])
    target_share = next((s for s in all_shares if s.get("name") == share_name), None)

    if not target_share:
        # 根据调用环境抛出不同的异常
        if require_permission:  # TCP服务器调用
            raise FileNotFoundError(f"Share '{share_name}' not found")
        else:  # Web API调用
            raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")

    # 检查权限
    if require_permission:
        permissions = target_share.get("permissions", ["read"])
        if require_permission not in permissions:
            error_msg = f"{require_permission.title()} permission denied for share '{share_name}'"
            if require_permission:  # TCP服务器调用
                raise PermissionError(error_msg)
            else:  # Web API调用
                raise HTTPException(status_code=403, detail=error_msg)

    # 路径安全验证
    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip("/\\"))
    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        error_msg = "Access denied: Path traversal attempt detected."
        if require_permission:  # TCP服务器调用
            raise PermissionError(error_msg)
        else:  # Web API调用
            raise HTTPException(status_code=403, detail=error_msg)

    return full_path, target_share


def normalize_path(path: str) -> str:
    """
    跨平台路径标准化处理。
    
    Args:
        path: 原始路径
        
    Returns:
        str: 标准化后的路径
    """
    # 处理 Windows 反斜杠
    normalized = path.replace('\\', '/')
    # 移除危险字符和路径
    normalized = os.path.normpath(normalized)
    return normalized


def validate_filename(filename: str) -> bool:
    """
    验证文件名是否安全。
    
    Args:
        filename: 文件名
        
    Returns:
        bool: 文件名是否安全
    """
    if not filename or filename in ['.', '..']:
        return False
        
    # 检查危险字符
    dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '\0']
    if any(char in filename for char in dangerous_chars):
        return False
        
    # 检查Windows保留名称
    reserved_names = [
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    ]
    if filename.upper().split('.')[0] in reserved_names:
        return False
        
    return True


def check_file_permissions(file_path: str, operation: str) -> bool:
    """
    跨平台文件权限检查。
    
    Args:
        file_path: 文件路径
        operation: 操作类型 ("read", "write", "execute")
        
    Returns:
        bool: 是否有权限
    """
    if not os.path.exists(file_path):
        return False
        
    if operation == "read":
        return os.access(file_path, os.R_OK)
    elif operation == "write":
        return os.access(file_path, os.W_OK)
    elif operation == "execute":
        return os.access(file_path, os.X_OK)
    return False
