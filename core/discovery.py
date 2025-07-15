"""
设备发现服务，基于Zeroconf协议实现网络设备自动发现
"""

import socket
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast

from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from .event_bus import bus


online_devices = {}
_last_event_times = {}
_device_info_queue = queue.Queue()
_device_info_executor = ThreadPoolExecutor(
    max_workers=20, thread_name_prefix="DeviceInfo"
)
_discovery_thread = None
_discovery_running = False


def _should_publish_event(
    event_type: str, name: str, debounce_time: float = 0.01
) -> bool:
    current_time = time.time()
    event_key = f"{event_type}:{name}"

    if event_key in _last_event_times:
        if current_time - _last_event_times[event_key] < debounce_time:
            return False

    _last_event_times[event_key] = current_time
    return True


def _process_device_info_async(
    zeroconf: Zeroconf, service_type: str, name: str, online_time: float = None
):
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

                # 创建设备唯一标识符：IP地址+端口
                # 这样即使同一台机器上有多个实例，也能区分它们
                device_id = f"{address}:{port}"

                device_data = {
                    "address": address,
                    "port": port,
                    "properties": properties,
                    "device_id": device_id,  # 添加设备唯一标识符
                }

                # 检查设备是否已存在且信息未变化
                is_new_device = name not in online_devices
                is_device_changed = (
                    not is_new_device and online_devices[name] != device_data
                )

                online_devices[name] = device_data

                # 移除日志输出，专注于速度

                # 防抖检查 - 只发布新设备或信息变化的事件
                if (is_new_device or is_device_changed) and _should_publish_event(
                    "peer_online", name
                ):
                    event_data = {
                        "event": "peer_online",
                        "name": name,
                        "friendly_name": friendly_name,
                        "data": device_data,
                        "online_time": online_time or time.time(),
                        "is_new_device": is_new_device,
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

            # 支持新的时间戳参数
            if len(task) == 4:
                zeroconf, service_type, name, online_time = task
            else:
                zeroconf, service_type, name = task
                online_time = time.time()

            # 提交到线程池异步处理，传递时间戳
            future = _device_info_executor.submit(
                _process_device_info_async, zeroconf, service_type, name, online_time
            )

            _device_info_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"设备信息工作线程错误: {e}")


class DiscoveryListener:
    """zeroconf的监听器，利用操作系统事件机制实现高效设备发现。"""

    def _write_debug_log(self, message):
        """写入调试日志到文件"""
        try:
            import os
            import datetime

            log_file = os.path.join(os.path.expanduser("~"), "netneighbor_debug.log")
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] DiscoveryListener: {message}\n")
                f.flush()
        except:
            pass  # 忽略日志写入错误

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        """设备下线事件处理 - 利用操作系统网络事件"""
        friendly_name = name.split("._netneighbor._tcp.local.")[0]

        # 记录设备下线时间，用于统计
        import time

        offline_time = time.time()

        if name in online_devices:
            # 获取设备信息用于日志
            device_info = online_devices[name]
            del online_devices[name]

            # 防抖检查 - 避免网络抖动导致的重复事件
            if _should_publish_event("peer_offline", name):
                event_data = {
                    "event": "peer_offline",
                    "name": name,
                    "friendly_name": friendly_name,
                    "offline_time": offline_time,
                    "device_info": device_info,
                }
                bus.publish("peer_update", event_data)

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zeroconf, type_, name)

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        """设备上线事件处理 - 利用操作系统网络事件机制"""
        global _discovery_running

        self._write_debug_log(f"🔍 发现新设备: {name}")

        if not _discovery_running:
            self._write_debug_log("设备发现服务未运行，忽略设备")
            return

        # 记录设备上线时间，用于性能统计
        import time

        online_time = time.time()
        self._write_debug_log(f"设备 {name} 上线时间: {online_time}")

        # 利用操作系统事件机制，直接加入高优先级处理队列
        # 移除队列大小检查以提高响应速度
        _device_info_queue.put((zeroconf, type_, name, online_time))
        self._write_debug_log(f"设备 {name} 已加入处理队列")


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

    def _write_debug_log(self, message):
        """写入调试日志到文件"""
        try:
            import os
            import datetime

            log_file = os.path.join(os.path.expanduser("~"), "netneighbor_debug.log")
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] DiscoveryService: {message}\n")
                f.flush()
        except:
            pass  # 忽略日志写入错误

    def start(self):
        """启动设备发现服务"""
        global _discovery_running, _discovery_thread

        try:
            self._write_debug_log("=== 开始启动设备发现服务 ===")

            # 启动设备信息处理线程
            _discovery_running = True
            _discovery_thread = threading.Thread(
                target=_device_info_worker, daemon=True
            )
            _discovery_thread.start()
            self._write_debug_log("设备信息处理线程已启动")

            self._register_service()
            self._write_debug_log("服务注册完成")

            self._browse_services()
            self._write_debug_log("服务浏览器启动完成")

            print("设备发现服务已启动...")
            self._write_debug_log("=== 设备发现服务启动完成 ===")

        except Exception as e:
            error_msg = f"启动设备发现服务时出错: {e}"
            print(error_msg)
            self._write_debug_log(error_msg)
            import traceback

            traceback_str = traceback.format_exc()
            self._write_debug_log(f"设备发现服务启动异常堆栈: {traceback_str}")
            raise

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
        try:
            full_service_name = f"{self.service_name}.{self.SERVICE_TYPE}"
            self._write_debug_log(f"准备注册服务: {full_service_name}")
            self._write_debug_log(f"服务参数: IP={self.host_ip}, 端口={self.port}")
            self._write_debug_log(f"服务属性: {self.service_properties}")

            # 检查IP地址是否为局域网IP
            is_lan_ip = (
                self.host_ip.startswith("192.168.")
                or self.host_ip.startswith("10.")
                or (
                    self.host_ip.startswith("172.")
                    and 16 <= int(self.host_ip.split(".")[1]) <= 31
                )
            )

            if not is_lan_ip:
                self._write_debug_log(
                    f"警告: 当前IP {self.host_ip} 不是局域网IP，可能是VPN接口"
                )
                # 尝试获取局域网IP
                try:
                    from gui.models.connection_model import ConnectionModel

                    lan_ip = ConnectionModel.get_my_ip()
                    if lan_ip != self.host_ip:
                        self._write_debug_log(
                            f"使用局域网IP {lan_ip} 替代 {self.host_ip}"
                        )
                        self.host_ip = lan_ip
                except Exception as e:
                    self._write_debug_log(f"获取局域网IP失败: {e}")

            self.service_info = ServiceInfo(
                self.SERVICE_TYPE,
                full_service_name,
                addresses=[socket.inet_aton(self.host_ip)],
                port=self.port,
                properties=self.service_properties,
            )
            self._write_debug_log("ServiceInfo 对象创建成功")

            self.zeroconf.register_service(self.service_info)
            print(f"服务 '{self.service_name}' 已注册。")
            self._write_debug_log(f"✅ 服务 '{self.service_name}' 注册成功")

        except Exception as e:
            error_msg = f"注册服务时出错: {e}"
            print(error_msg)
            self._write_debug_log(error_msg)
            import traceback

            traceback_str = traceback.format_exc()
            self._write_debug_log(f"服务注册异常堆栈: {traceback_str}")
            raise

    def _browse_services(self):
        try:
            self._write_debug_log(f"准备启动服务浏览器，监听类型: {self.SERVICE_TYPE}")

            self.browser = ServiceBrowser(
                self.zeroconf, self.SERVICE_TYPE, DiscoveryListener()
            )

            self._write_debug_log("✅ 服务浏览器启动成功")

        except Exception as e:
            error_msg = f"启动服务浏览器时出错: {e}"
            print(error_msg)
            self._write_debug_log(error_msg)
            import traceback

            traceback_str = traceback.format_exc()
            self._write_debug_log(f"服务浏览器启动异常堆栈: {traceback_str}")
            raise
