import socket
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast

from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from .event_bus import bus


online_devices = {}
# 防抖机制：记录最后一次事件发布时间
_last_event_times = {}
# 设备信息处理队列和线程池 - 增加线程数提高并发处理能力
_device_info_queue = queue.Queue()
_device_info_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="DeviceInfo")
_discovery_thread = None
_discovery_running = False


def _should_publish_event(event_type: str, name: str, debounce_time: float = 0.01) -> bool:
    """检查是否应该发布事件（减少防抖时间提高响应速度）"""
    current_time = time.time()
    event_key = f"{event_type}:{name}"

    if event_key in _last_event_times:
        if current_time - _last_event_times[event_key] < debounce_time:
            return False

    _last_event_times[event_key] = current_time
    return True


def _process_device_info_async(zeroconf: Zeroconf, service_type: str, name: str):
    """异步处理设备信息获取"""
    try:
        info = zeroconf.get_service_info(service_type, name)
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

                # 检查设备是否已存在且信息未变化
                is_new_device = name not in online_devices
                is_device_changed = (
                    not is_new_device and
                    online_devices[name] != device_data
                )

                online_devices[name] = device_data

                # 移除日志输出，专注于速度

                # 防抖检查 - 只发布新设备或信息变化的事件
                if (is_new_device or is_device_changed) and _should_publish_event("peer_online", name):
                    event_data = {
                        "event": "peer_online",
                        "name": name,
                        "friendly_name": friendly_name,
                        "data": device_data,
                    }
                    bus.publish("peer_update", event_data)

            except (socket.error, AttributeError, IndexError) as e:
                print(f"解析设备 {name} 信息时出错: {e}")
    except Exception as e:
        print(f"异步处理设备 {name} 时出错: {e}")


def _device_info_worker():
    """设备信息处理工作线程"""
    global _discovery_running

    while _discovery_running:
        try:
            # 从队列获取待处理的设备信息请求
            task = _device_info_queue.get(timeout=1.0)
            if task is None:  # 停止信号
                break

            zeroconf, service_type, name = task

            # 提交到线程池异步处理
            future = _device_info_executor.submit(_process_device_info_async, zeroconf, service_type, name)

            _device_info_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"设备信息工作线程错误: {e}")


class DiscoveryListener:
    """zeroconf的监听器，发布包含完整设备信息的事件。"""

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        friendly_name = name.split("._netneighbor._tcp.local.")[0]
        if name in online_devices:
            del online_devices[name]

        # 防抖检查
        if _should_publish_event("peer_offline", name):
            event_data = {
                "event": "peer_offline",
                "name": name,
                "friendly_name": friendly_name,
            }
            bus.publish("peer_update", event_data)

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zeroconf, type_, name)

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        """添加服务 - 使用异步处理避免阻塞"""
        global _discovery_running

        if not _discovery_running:
            return

        # 直接加入队列，移除队列大小检查以提高速度
        _device_info_queue.put((zeroconf, type_, name))


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
        """启动设备发现服务"""
        global _discovery_running, _discovery_thread

        # 启动设备信息处理线程
        _discovery_running = True
        _discovery_thread = threading.Thread(target=_device_info_worker, daemon=True)
        _discovery_thread.start()

        self._register_service()
        self._browse_services()
        print("设备发现服务已启动...")

    def stop(self):
        """停止设备发现服务"""
        global _discovery_running, _discovery_thread

        print("正在关闭设备发现服务...")

        # 停止设备信息处理线程
        _discovery_running = False
        if _discovery_thread and _discovery_thread.is_alive():
            # 发送停止信号
            _device_info_queue.put(None)
            _discovery_thread.join(timeout=2.0)

        # 关闭线程池
        _device_info_executor.shutdown(wait=True)

        # 关闭zeroconf
        if self.zeroconf:
            if self.service_info:
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
