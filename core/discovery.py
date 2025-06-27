# 文件: core/discovery.py (修改)
import time
import socket
import json
import asyncio
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser
from typing import cast

# 【核心修正】将导入语句移到函数内部，打破启动时的循环依赖
# from .web_api import manager
online_devices = {}


def broadcast_event(event_data: dict):
    """安全地在后台广播WebSocket事件。"""
    # 动态导入以避免循环依赖
    from .web_api import manager
    try:
        # 尝试获取当前线程的事件循环，如果没有则创建一个新的
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(asyncio.create_task, manager.broadcast(json.dumps(event_data)))
        else:
            # 如果主线程的事件循环没有运行（例如在某些测试场景下），直接运行任务
            asyncio.run(manager.broadcast(json.dumps(event_data)))
    except RuntimeError:
        # 如果当前线程没有事件循环，则创建一个新的并运行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(manager.broadcast(json.dumps(event_data)))


class DiscoveryListener:
    """zeroconf的监听器，处理服务的添加、更新和移除事件。"""

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        friendly_name = name.split('._netneighbor._tcp.local.')[0]
        print(f"设备下线: {friendly_name}")
        if name in online_devices: del online_devices[name]
        broadcast_event({"event": "peer_offline", "name": friendly_name})

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        # 更新服务时，也走添加服务的逻辑来刷新信息
        self.add_service(zeroconf, type_, name)

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name)
        if info and info.addresses and info.port is not None:
            is_new = name not in online_devices
            friendly_name = name.split('._netneighbor._tcp.local.')[0]
            try:
                # 将字节串地址转换为字符串
                address = socket.inet_ntoa(info.addresses[0])
                port = cast(int, info.port)
                # 安全地解码属性
                properties = {k.decode('utf-8'): v.decode('utf-8') for k, v in
                              info.properties.items()} if info.properties else {}

                online_devices[name] = {"address": address, "port": port, "properties": properties}

                if is_new:
                    print(f"发现新设备: {friendly_name} at {address}:{port}")
                    broadcast_event({"event": "peer_online", "name": friendly_name, "address": f"{address}:{port}"})
            except (socket.error, AttributeError, IndexError) as e:
                print(f"解析设备 {name} 信息时出错: {e}")


class DiscoveryService:
    # 【修复1】将服务类型定义为类常量
    SERVICE_TYPE = "_netneighbor._tcp.local."

    def __init__(self, host_ip, port, service_name, service_properties):
        self.zeroconf = Zeroconf()
        self.host_ip, self.port, self.service_name, self.service_properties = host_ip, port, service_name, service_properties
        self.service_info, self.browser = None, None

    def start(self):
        self._register_service()
        self._browse_services()
        print("设备发现服务已启动...")

    def stop(self):
        if not self.zeroconf: return
        print("正在关闭设备发现服务...")
        self.zeroconf.unregister_service(self.service_info)
        self.zeroconf.close()

    def _register_service(self):
        # 使用类常量
        full_service_name = f"{self.service_name}.{self.SERVICE_TYPE}"
        self.service_info = ServiceInfo(
            self.SERVICE_TYPE,
            full_service_name,
            addresses=[socket.inet_aton(self.host_ip)],
            port=self.port,
            properties=self.service_properties
        )
        self.zeroconf.register_service(self.service_info)
        print(f"服务 '{self.service_name}' 已注册。")

    def _browse_services(self):
        # 【修复1】使用类常量，修复 NameError
        self.browser = ServiceBrowser(self.zeroconf, self.SERVICE_TYPE, DiscoveryListener())