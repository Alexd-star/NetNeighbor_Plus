"""
连接模型类，用于管理API客户端和连接状态
"""
from typing import Dict, Any, List, Callable, Optional
import socket
import threading
import time

from gui.api_client import ApiClient


class ConnectionModel:
    """连接数据模型，管理API客户端和连接状态"""
    
    def __init__(self):
        self._api_client: Optional[ApiClient] = None
        self._active_peer_client: Optional[ApiClient] = None
        self._active_device_name: Optional[str] = None
        self._active_device_address: Optional[str] = None
        self._connection_state: str = "disconnected"  # disconnected, connecting, connected
        self._ping_ms: int = 0
        
        self._on_connection_state_changed_callbacks: List[Callable[[str], None]] = []
        self._on_active_peer_changed_callbacks: List[Callable[[Optional[ApiClient]], None]] = []
        
    def set_local_api_client(self, base_url: str) -> None:
        """设置本地API客户端"""
        self._api_client = ApiClient(base_url)
        
    def get_local_api_client(self) -> Optional[ApiClient]:
        """获取本地API客户端"""
        return self._api_client
        
    def set_active_peer_client(self, client: Optional[ApiClient], device_name: Optional[str] = None, 
                              device_address: Optional[str] = None) -> None:
        """设置活动的对等设备客户端"""
        self._active_peer_client = client
        self._active_device_name = device_name
        self._active_device_address = device_address
        
        if client:
            self.set_connection_state("connected")
        else:
            self.set_connection_state("disconnected")
            
        for callback in self._on_active_peer_changed_callbacks:
            callback(client)
            
    def get_active_peer_client(self) -> Optional[ApiClient]:
        """获取活动的对等设备客户端"""
        return self._active_peer_client
        
    def get_active_device_name(self) -> Optional[str]:
        """获取活动设备名称"""
        return self._active_device_name
        
    def get_active_device_address(self) -> Optional[str]:
        """获取活动设备地址"""
        return self._active_device_address
        
    def set_connection_state(self, state: str) -> None:
        """设置连接状态"""
        if self._connection_state != state:
            self._connection_state = state
            for callback in self._on_connection_state_changed_callbacks:
                callback(state)
                
    def get_connection_state(self) -> str:
        """获取连接状态"""
        return self._connection_state
        
    def measure_ping(self) -> None:
        """在后台测量与远程设备的延迟"""
        if not self._active_peer_client:
            self._ping_ms = 0
            return
            
        def do_ping():
            try:
                start = time.perf_counter()
                if self._active_peer_client and self._active_peer_client.get_ping():
                    self._ping_ms = int((time.perf_counter() - start) * 1000)
                else:
                    self._ping_ms = 0
            except Exception:
                self._ping_ms = 0
                
        threading.Thread(target=do_ping, daemon=True).start()
        
    def get_ping_ms(self) -> int:
        """获取延迟（毫秒）"""
        return self._ping_ms
        
    def on_connection_state_changed(self, callback: Callable[[str], None]) -> None:
        """注册连接状态变化回调"""
        self._on_connection_state_changed_callbacks.append(callback)
        
    def on_active_peer_changed(self, callback: Callable[[Optional[ApiClient]], None]) -> None:
        """注册活动对等设备变化回调"""
        self._on_active_peer_changed_callbacks.append(callback)
        
    @staticmethod
    def get_my_ip() -> str:
        """获取本机的局域网IP地址"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1" 