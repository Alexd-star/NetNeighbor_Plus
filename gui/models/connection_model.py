"""
连接模型类，用于管理API客户端和连接状态
"""

from typing import Dict, Any, List, Callable, Optional
import socket
import threading
import time
import platform
import subprocess
import os

from gui.api_client import ApiClient


class ConnectionModel:
    """连接数据模型，管理API客户端和连接状态"""

    def __init__(self):
        self._api_client: Optional[ApiClient] = None
        self._active_peer_client: Optional[ApiClient] = None
        self._active_device_name: Optional[str] = None
        self._active_device_address: Optional[str] = None
        self._connection_state: str = (
            "disconnected"  # disconnected, connecting, connected
        )
        self._ping_ms: int = 0

        self._on_connection_state_changed_callbacks: List[Callable[[str], None]] = []
        self._on_active_peer_changed_callbacks: List[
            Callable[[Optional[ApiClient]], None]
        ] = []

    def set_local_api_client(self, base_url: str) -> None:
        from gui.api_client import ApiClient

        self._api_client = ApiClient(base_url)

    def get_local_api_client(self) -> Optional["ApiClient"]:
        return self._api_client

    def set_active_peer_client(
        self,
        client: Optional["ApiClient"],
        device_name: Optional[str] = None,
        device_address: Optional[str] = None,
    ) -> None:
        self._active_peer_client = client
        self._active_device_name = device_name
        self._active_device_address = device_address

        if client:
            self.set_connection_state("connected")
        else:
            self.set_connection_state("disconnected")

        for callback in self._on_active_peer_changed_callbacks:
            callback(client)

    def get_active_peer_client(self) -> Optional["ApiClient"]:
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

    def on_active_peer_changed(
        self, callback: Callable[[Optional["ApiClient"]], None]
    ) -> None:
        """注册活动对等设备变化回调"""
        self._on_active_peer_changed_callbacks.append(callback)

    @staticmethod
    def get_my_ip() -> str:
        """
        获取本机的局域网IP地址。
        这个函数经过了优化，可以更智能地处理多个网络接口的情况。
        它会遍历所有网络接口，并根据优先级选择最合适的IP地址。
        """
        ips = []
        try:
            # 这种方法可以获取所有接口的地址，比连接外部服务更可靠
            # 在Windows上，这会包括所有网卡，包括虚拟网卡
            # 在Linux/macOS上，效果类似
            all_addrs = socket.getaddrinfo(socket.gethostname(), None)
            for item in all_addrs:
                # 只关心IPv4地址
                if item[0] == socket.AF_INET:
                    ip = item[4][0]
                    # 排除环回地址
                    if ip != "127.0.0.1":
                        ips.append(ip)
        except socket.gaierror:
            # 如果gethostname失败，尝试备用方法
            pass

        # 如果上述方法没有找到IP，尝试使用连接外部服务器的方式作为备用
        if not ips:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(2)
                    s.connect(("8.8.8.8", 80))
                    ip = s.getsockname()[0]
                    if ip != "127.0.0.1":
                        ips.append(ip)
            except Exception:
                return "127.0.0.1"

        if not ips:
            return "127.0.0.1"

        # 优先级排序：
        # 1. 私有IP地址 (192.168.x.x, 10.x.x.x, 172.16-31.x.x) - 这些最可能是局域网IP
        # 2. 其他所有IP (可能是公网IP或特殊IP)
        private_ips = []
        other_ips = []

        for ip in ips:
            try:
                parts = [int(p) for p in ip.split(".")]
                if parts[0] == 192 and parts[1] == 168:
                    private_ips.append(ip)
                elif parts[0] == 10:
                    private_ips.append(ip)
                elif parts[0] == 172 and 16 <= parts[1] <= 31:
                    private_ips.append(ip)
                else:
                    other_ips.append(ip)
            except (ValueError, IndexError):
                continue  # IP地址格式不正确

        # 优先返回私有地址列表中的第一个地址
        if private_ips:
            # 您可以在这里添加更复杂的逻辑，比如优先有线网络的IP
            # 但通常列表中的第一个私有地址就是最常用的那个
            return private_ips[0]

        # 如果没有私有地址，返回其他IP中的第一个
        if other_ips:
            return other_ips[0]

        # 最后的回退
        return "127.0.0.1"
