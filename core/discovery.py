# 文件: core/discovery.py
import socket
from typing import cast

from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from .event_bus import bus


online_devices = {}


class DiscoveryListener:
    """zeroconf的监听器，发布包含完整设备信息的事件。"""

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        friendly_name = name.split("._netneighbor._tcp.local.")[0]
        print(f"设备下线: {friendly_name}")
        if name in online_devices:
            del online_devices[name]

        event_data = {
            "event": "peer_offline",
            "name": name,
            "friendly_name": friendly_name,
        }
        bus.publish("peer_update", event_data)

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zeroconf, type_, name)

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name)
        if info and info.addresses and info.port is not None:
            friendly_name = name.split("._netneighbor._tcp.local.")[0]
            try:
                address = socket.inet_ntoa(info.addresses[0])
                port = cast(int, info.port)
                properties = (
                    {
                        k.decode("utf-8"): v.decode("utf-8")
                        for k, v in info.properties.items()
                    }
                    if info.properties
                    else {}
                )

                device_data = {
                    "address": address,
                    "port": port,
                    "properties": properties,
                }
                online_devices[name] = device_data

                print(f"发现新设备: {friendly_name} at {address}:{port}")

                event_data = {
                    "event": "peer_online",
                    "name": name,
                    "friendly_name": friendly_name,
                    "data": device_data,
                }
                bus.publish("peer_update", event_data)

            except (socket.error, AttributeError, IndexError) as e:
                print(f"解析设备 {name} 信息时出错: {e}")


class DiscoveryService:
    SERVICE_TYPE = "_netneighbor._tcp.local."

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
        if self.zeroconf:
            print("正在关闭设备发现服务...")
            self.zeroconf.unregister_service(self.service_info)
            self.zeroconf.close()

    def _register_service(self):
        full_service_name = f"{self.service_name}.{self.SERVICE_TYPE}"
        self.service_info = ServiceInfo(
            self.SERVICE_TYPE,
            full_service_name,
            addresses=[socket.inet_aton(self.host_ip)],
            port=self.port,
            properties=self.service_properties,
        )
        self.zeroconf.register_service(self.service_info)
        print(f"服务 '{self.service_name}' 已注册。")

    def _browse_services(self):
        self.browser = ServiceBrowser(
            self.zeroconf, self.SERVICE_TYPE, DiscoveryListener()
        )
