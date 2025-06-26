import time
import socket
from threading import Thread
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser
from typing import cast

online_devices = {}

class DiscoveryListener:
    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        print(f"设备下线: {name}")
        if name in online_devices:
            del online_devices[name]

    # 【修正】添加了 update_service 方法来处理警告
    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        # 在这个应用中，我们把更新当作一次新的添加来处理
        self.add_service(zeroconf, type_, name)

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name)
        if info:
            try:
                address = socket.inet_ntoa(info.addresses[0])
                port = cast(int, info.port)
                online_devices[name] = {
                    "address": address,
                    "port": port,
                    "properties": {k.decode(): v.decode() for k, v in info.properties.items()}
                }
                print(f"发现设备: {name} at {address}:{port}")
            except (AttributeError, IndexError):
                print(f"警告：无法解析设备 {name} 的地址信息。")

class DiscoveryService:
    def __init__(self, host_ip, port, service_name, service_properties):
        self.zeroconf = Zeroconf()
        self.host_ip = host_ip
        self.port = port
        self.service_name = service_name
        self.service_properties = service_properties
        self.service_info = None
        self.browser = None

    def start(self):
        self._register_service()
        self._browse_services()
        print("设备发现服务已启动...")

    def stop(self):
        print("正在关闭设备发现服务...")
        self.zeroconf.unregister_service(self.service_info)
        self.zeroconf.close()

    def _register_service(self):
        self.service_info = ServiceInfo(
            "_netneighbor._tcp.local.",
            f"{self.service_name}._netneighbor._tcp.local.",
            addresses=[socket.inet_aton(self.host_ip)],
            port=self.port,
            properties=self.service_properties,
        )
        self.zeroconf.register_service(self.service_info)
        print(f"服务 '{self.service_name}' 已注册。")

    def _browse_services(self):
        self.browser = ServiceBrowser(self.zeroconf, "_netneighbor._tcp.local.", DiscoveryListener())