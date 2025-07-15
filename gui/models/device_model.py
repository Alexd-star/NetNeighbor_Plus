"""
设备模型类，用于管理设备数据
"""

import re
from typing import Dict, Any, Optional, List, Callable


def natural_sort_key(s: str) -> list:
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
        self.my_service_name = None
        self._batch_update_enabled = False
        self._pending_notifications = set()

    def set_my_service_name(self, service_name: str):
        self.my_service_name = service_name
        if service_name in self.online_devices:
            self.remove_device(service_name)

    def add_device(self, service_name: str, device_data: Dict[str, Any]) -> bool:
        if self.my_service_name and service_name == self.my_service_name:
            return False

        if service_name in self.online_devices:
            return False

        self.online_devices[service_name] = device_data

        if self._batch_update_enabled:
            self._pending_notifications.add("device_added")
            self._pending_notifications.add("list_changed")
        else:
            for callback in self._on_device_added_callbacks:
                callback(service_name, device_data)
            for callback in self._on_device_list_changed_callbacks:
                callback()

        return True

    def remove_device(self, service_name: str) -> bool:
        if service_name not in self.online_devices:
            return False

        del self.online_devices[service_name]

        if self._batch_update_enabled:
            self._pending_notifications.add("device_removed")
            self._pending_notifications.add("list_changed")
        else:
            for callback in self._on_device_removed_callbacks:
                callback(service_name)
            for callback in self._on_device_list_changed_callbacks:
                callback()

        return True

    def get_device(self, service_name: str) -> Optional[Dict[str, Any]]:
        return self.online_devices.get(service_name)

    def get_all_devices(self) -> Dict[str, Dict[str, Any]]:
        return self.online_devices.copy()

    def get_sorted_devices(self) -> List[tuple]:
        return sorted(
            self.online_devices.items(),
            key=lambda item: natural_sort_key(
                item[0].split("._netneighbor._tcp.local.")[0]
            ),
        )

    def clear(self) -> None:
        self.online_devices.clear()
        for callback in self._on_device_list_changed_callbacks:
            callback()

    def get_device_count(self) -> int:
        return len(self.online_devices)

    def remove_my_device(self) -> bool:
        if self.my_service_name and self.my_service_name in self.online_devices:
            return self.remove_device(self.my_service_name)
        return False

    def on_device_added(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        self._on_device_added_callbacks.append(callback)

    def on_device_removed(self, callback: Callable[[str], None]) -> None:
        self._on_device_removed_callbacks.append(callback)

    def on_device_list_changed(self, callback: Callable[[], None]) -> None:
        self._on_device_list_changed_callbacks.append(callback)

    def enable_batch_updates(self):
        self._batch_update_enabled = True
        self._pending_notifications.clear()

    def disable_batch_updates(self):
        self._batch_update_enabled = False
        if "list_changed" in self._pending_notifications:
            for callback in self._on_device_list_changed_callbacks:
                callback()
        self._pending_notifications.clear()
