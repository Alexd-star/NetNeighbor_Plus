"""
设备模型类，用于管理设备数据
"""

import re
from typing import Dict, Any, Optional, List, Callable


def natural_sort_key(s: str) -> list:
    """为字符串生成一个可用于自然排序的键"""
    result = []
    parts = re.split(r"(\d+)", s)
    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part.lower())
    return result


class DeviceModel:
    """设备数据模型，管理在线设备列表"""

    def __init__(self):
        self.online_devices: Dict[str, Dict[str, Any]] = {}
        self._on_device_added_callbacks: List[Callable[[str, Dict[str, Any]], None]] = (
            []
        )
        self._on_device_removed_callbacks: List[Callable[[str], None]] = []
        self._on_device_list_changed_callbacks: List[Callable[[], None]] = []
        self.my_service_name = None  # 用于存储本机服务名称

        # 批量更新机制
        self._batch_update_enabled = False
        self._pending_notifications = set()

        # 移除性能监控和限制，专注于速度

    def set_my_service_name(self, service_name: str):
        """设置本机服务名称"""
        self.my_service_name = service_name
        # 如果本机设备已在列表中，立即移除
        if service_name in self.online_devices:
            self.remove_device(service_name)

    def add_device(self, service_name: str, device_data: Dict[str, Any]) -> bool:
        """添加设备到列表中，如果设备已存在则返回False"""
        # 如果是本机设备，则不添加
        if self.my_service_name and service_name == self.my_service_name:
            return False

        if service_name in self.online_devices:
            return False

        self.online_devices[service_name] = device_data

        # 批量更新模式下延迟通知
        if self._batch_update_enabled:
            self._pending_notifications.add("device_added")
            self._pending_notifications.add("list_changed")
        else:
            # 立即通知回调
            for callback in self._on_device_added_callbacks:
                callback(service_name, device_data)

            for callback in self._on_device_list_changed_callbacks:
                callback()

        return True

    def remove_device(self, service_name: str) -> bool:
        """从列表中移除设备，如果设备不存在则返回False"""
        if service_name not in self.online_devices:
            return False

        del self.online_devices[service_name]

        # 批量更新模式下延迟通知
        if self._batch_update_enabled:
            self._pending_notifications.add("device_removed")
            self._pending_notifications.add("list_changed")
        else:
            # 立即通知回调
            for callback in self._on_device_removed_callbacks:
                callback(service_name)

            for callback in self._on_device_list_changed_callbacks:
                callback()

        return True

    def get_device(self, service_name: str) -> Optional[Dict[str, Any]]:
        """获取指定设备的数据"""
        return self.online_devices.get(service_name)

    def get_all_devices(self) -> Dict[str, Dict[str, Any]]:
        """获取所有设备数据"""
        return self.online_devices.copy()

    def get_sorted_devices(self) -> List[tuple]:
        """获取按名称自然排序后的设备列表"""
        return sorted(
            self.online_devices.items(),
            key=lambda item: natural_sort_key(
                item[0].split("._netneighbor._tcp.local.")[0]
            ),
        )

    def clear(self) -> None:
        """清空设备列表"""
        self.online_devices.clear()

        # 通知回调
        for callback in self._on_device_list_changed_callbacks:
            callback()

    def get_device_count(self) -> int:
        """获取设备数量"""
        return len(self.online_devices)

    def remove_my_device(self) -> bool:
        """移除本机设备"""
        if self.my_service_name and self.my_service_name in self.online_devices:
            return self.remove_device(self.my_service_name)
        return False

    def on_device_added(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """注册设备添加回调"""
        self._on_device_added_callbacks.append(callback)

    def on_device_removed(self, callback: Callable[[str], None]) -> None:
        """注册设备移除回调"""
        self._on_device_removed_callbacks.append(callback)

    def on_device_list_changed(self, callback: Callable[[], None]) -> None:
        """注册设备列表变化回调"""
        self._on_device_list_changed_callbacks.append(callback)

    def enable_batch_updates(self):
        """启用批量更新模式"""
        self._batch_update_enabled = True
        self._pending_notifications.clear()

    def disable_batch_updates(self):
        """禁用批量更新模式并处理待处理的通知"""
        self._batch_update_enabled = False

        # 处理待处理的通知
        # 注意：在批量模式下，我们只触发list_changed回调，让Presenter决定如何更新
        if "list_changed" in self._pending_notifications:
            for callback in self._on_device_list_changed_callbacks:
                callback()

        self._pending_notifications.clear()
