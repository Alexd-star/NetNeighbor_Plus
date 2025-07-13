"""
设备模型类，用于管理设备数据
"""
from typing import Dict, Any, Optional, List, Callable
import re


def natural_sort_key(s: str) -> list:
    """
    为字符串生成一个可用于自然排序的键。
    例如，'v10' 会被转换为 ['v', 10]，'v2' 会被转换为 ['v', 2]。
    这样在比较时，10 会被正确地识别为大于 2。
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'([0-9]+)', s)]


class DeviceModel:
    """设备数据模型，管理在线设备列表"""
    
    def __init__(self):
        self.online_devices: Dict[str, Dict[str, Any]] = {}
        self._on_device_added_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []
        self._on_device_removed_callbacks: List[Callable[[str], None]] = []
        self._on_device_list_changed_callbacks: List[Callable[[], None]] = []
        
    def add_device(self, service_name: str, device_data: Dict[str, Any]) -> bool:
        """添加设备到列表中，如果设备已存在则返回False"""
        if service_name in self.online_devices:
            return False
            
        self.online_devices[service_name] = device_data
        
        # 通知回调
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
        
        # 通知回调
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
            key=lambda item: natural_sort_key(item[0].split('._netneighbor._tcp.local.')[0])
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
        
    def on_device_added(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """注册设备添加回调"""
        self._on_device_added_callbacks.append(callback)
        
    def on_device_removed(self, callback: Callable[[str], None]) -> None:
        """注册设备移除回调"""
        self._on_device_removed_callbacks.append(callback)
        
    def on_device_list_changed(self, callback: Callable[[], None]) -> None:
        """注册设备列表变化回调"""
        self._on_device_list_changed_callbacks.append(callback) 