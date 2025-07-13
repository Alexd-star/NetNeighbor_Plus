"""
共享文件夹模型类，用于管理共享文件夹数据
"""

from typing import Dict, Any, List, Callable, Optional
import os
from core.config_loader import load_config


class ShareModel:
    """共享文件夹数据模型，管理本地共享文件夹列表"""

    def __init__(self):
        self._shares: List[Dict[str, Any]] = []
        self._on_shares_changed_callbacks: List[Callable[[], None]] = []
        self._load_shares()

    def _load_shares(self) -> None:
        """从配置文件加载共享文件夹"""
        self._shares = load_config(force_reload=True).get("shares", [])

    def reload_shares(self) -> None:
        """重新加载共享文件夹并通知回调"""
        self._load_shares()
        self._notify_shares_changed()

    def get_shares(self) -> List[Dict[str, Any]]:
        """获取所有共享文件夹"""
        return self._shares.copy()

    def get_share_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """根据名称获取共享文件夹"""
        for share in self._shares:
            if share.get("name") == name:
                return share.copy()
        return None

    def has_shares(self) -> bool:
        """检查是否有共享文件夹"""
        return len(self._shares) > 0

    def get_share_count(self) -> int:
        """获取共享文件夹数量"""
        return len(self._shares)

    def on_shares_changed(self, callback: Callable[[], None]) -> None:
        """注册共享文件夹变化回调"""
        self._on_shares_changed_callbacks.append(callback)

    def _notify_shares_changed(self) -> None:
        """通知所有回调共享文件夹已变化"""
        for callback in self._on_shares_changed_callbacks:
            callback()


class RemoteShareModel:
    """远程共享文件夹数据模型，管理远程设备的共享文件夹列表"""

    def __init__(self):
        self._shares: List[Dict[str, Any]] = []
        self._current_share: Optional[str] = None
        self._path_stack: List[str] = []
        self._on_shares_changed_callbacks: List[Callable[[], None]] = []
        self._on_path_changed_callbacks: List[Callable[[], None]] = []

    def set_shares(self, shares: List[Dict[str, Any]]) -> None:
        """设置远程共享文件夹列表"""
        self._shares = shares
        self._notify_shares_changed()

    def get_shares(self) -> List[Dict[str, Any]]:
        """获取所有远程共享文件夹"""
        return self._shares.copy()

    def get_share_names(self) -> List[str]:
        """获取所有远程共享文件夹名称"""
        return [s.get("name", "") for s in self._shares if "name" in s]

    def set_current_share(self, share_name: str) -> None:
        """设置当前选中的共享文件夹"""
        if self._current_share != share_name:
            self._current_share = share_name
            self._path_stack = []
            self._notify_path_changed()

    def get_current_share(self) -> Optional[str]:
        """获取当前选中的共享文件夹名称"""
        return self._current_share

    def get_current_share_info(self) -> Optional[Dict[str, Any]]:
        """获取当前选中的共享文件夹信息"""
        if not self._current_share:
            return None

        for share in self._shares:
            if share.get("name") == self._current_share:
                return share.copy()

        return None

    def has_permission(self, permission: str) -> bool:
        """检查当前共享是否有指定权限"""
        share_info = self.get_current_share_info()
        if not share_info:
            return False

        return permission in share_info.get("permissions", [])

    def push_path(self, folder_name: str) -> None:
        """进入子文件夹"""
        self._path_stack.append(folder_name)
        self._notify_path_changed()

    def pop_path(self) -> Optional[str]:
        """返回上一级文件夹"""
        if not self._path_stack:
            return None

        folder = self._path_stack.pop()
        self._notify_path_changed()
        return folder

    def get_path_stack(self) -> List[str]:
        """获取当前路径栈"""
        return self._path_stack.copy()

    def get_current_path(self) -> str:
        """获取当前完整路径"""
        return "/" + "/".join(self._path_stack)

    def clear(self) -> None:
        """清空数据"""
        self._shares = []
        self._current_share = None
        self._path_stack = []
        self._notify_shares_changed()
        self._notify_path_changed()

    def on_shares_changed(self, callback: Callable[[], None]) -> None:
        """注册共享文件夹变化回调"""
        self._on_shares_changed_callbacks.append(callback)

    def on_path_changed(self, callback: Callable[[], None]) -> None:
        """注册路径变化回调"""
        self._on_path_changed_callbacks.append(callback)

    def _notify_shares_changed(self) -> None:
        """通知所有回调共享文件夹已变化"""
        for callback in self._on_shares_changed_callbacks:
            callback()

    def _notify_path_changed(self) -> None:
        """通知所有回调路径已变化"""
        for callback in self._on_path_changed_callbacks:
            callback()
