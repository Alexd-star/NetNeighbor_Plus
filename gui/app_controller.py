"""
应用程序主控制器，协调各个模块的工作
"""

import asyncio
import copy
import getpass
import json
import os
import platform
import socket
import threading
import time

import uvicorn
from PySide6.QtCore import QObject, Signal, QTimer

from core.config_loader import get_config, get_shares
from core.event_bus import bus


from core.web_api import app as fastapi_app, manager as websocket_manager


class UvicornServer(threading.Thread):
    """在一个独立的线程中运行 Uvicorn 服务器。"""

    def __init__(self, config):
        super().__init__()
        self.daemon = True
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


class AppController(QObject):
    """应用的核心控制器, 管理所有后台服务的生命周期。"""

    server_started = Signal()
    device_info_updated = Signal()

    def __init__(self, port_override=None, parent=None):
        super().__init__(parent)
        self.running_config = copy.deepcopy(get_config())
        self.port_override = port_override

        if self.port_override:
            self.port = self.port_override
            self.running_config["service"]["port"] = self.port
        else:
            self.port = self.running_config.get("service", {}).get("port", 8080)

        self.tcp_port = self.port + 1
        self.device_name = self.running_config.get("service", {}).get("name", "auto")
        self.service_name = self.device_name
        self.device_properties = {}

        self.stop_event = threading.Event()
        self.watcher_stop_event = threading.Event()

        self.uvicorn_server_thread = None
        self.discovery_service = None
        self.watcher_thread = None
        self.is_running = False

        bus.subscribe("peer_update", self._handle_peer_update_event)

        # WebSocket广播防抖机制
        self._last_broadcast_time = 0
        self._pending_broadcasts = {}
        self._broadcast_timer = None

    def _handle_peer_update_event(self, event_data: dict):
        """当从事件总线接收到设备更新事件时，通过WebSocket广播出去。"""
        # 使用防抖机制减少WebSocket广播频率
        device_name = event_data.get("name")
        if device_name:
            self._pending_broadcasts[device_name] = event_data

            # 减少广播延迟，提高响应速度
            current_time = time.time()
            if current_time - self._last_broadcast_time > 0.005:  # 5ms防抖
                self._schedule_broadcast()
                self._last_broadcast_time = current_time

    def _schedule_broadcast(self):
        """调度WebSocket广播"""
        if self._broadcast_timer:
            return  # 已有定时器在运行

        def do_broadcast():
            if not self._pending_broadcasts:
                return

            # 批量广播所有待处理的事件
            broadcasts_to_send = list(self._pending_broadcasts.values())
            self._pending_broadcasts.clear()
            self._broadcast_timer = None

            loop = getattr(fastapi_app.state, "asyncio_loop", None)
            if loop and loop.is_running():
                for event_data in broadcasts_to_send:
                    loop.call_soon_threadsafe(
                        asyncio.create_task,
                        websocket_manager.broadcast(json.dumps(event_data)),
                    )

        # 使用线程定时器而不是QTimer，避免依赖Qt
        self._broadcast_timer = threading.Timer(0.005, do_broadcast)  # 5ms延迟
        self._broadcast_timer.start()

    def _get_dynamic_device_type(self) -> str:
        """根据操作系统动态判断设备类型。"""
        system = platform.system().lower()
        if system in ["windows", "linux", "darwin"]:
            return "PC"
        elif system == "android":
            return "Phone/Tablet"
        else:
            return "Unknown Device"

    def start_all_services(self):
        """启动所有后台服务。"""
        if self.is_running:
            return

        print("正在启动所有后台服务...")

        # 并行获取网络信息和设备信息，避免阻塞
        def get_host_info():
            try:
                return socket.gethostbyname(socket.gethostname())
            except socket.gaierror:
                return "127.0.0.1"

        def get_device_info():
            base_name = (
                self.running_config.get("service", {}).get("name", "auto").strip()
            )
            dynamic_base_name = (
                socket.gethostname()
                if not base_name or base_name.lower() == "auto"
                else base_name
            )

            device_name = (
                f"{dynamic_base_name}-{self.port}"
                if self.port_override
                else dynamic_base_name
            )

            device_properties = {
                "os": f"{platform.system()} {platform.release()}",
                "user": getpass.getuser(),
                "tcp_port": str(self.tcp_port),
                "dev_type": self._get_dynamic_device_type(),
            }

            return device_name, device_properties

        # 并行执行网络和设备信息获取
        host_thread = threading.Thread(
            target=lambda: setattr(self, "_host_ip", get_host_info())
        )
        device_thread = threading.Thread(
            target=lambda: setattr(self, "_device_info", get_device_info())
        )

        host_thread.start()
        device_thread.start()

        # 等待信息获取完成
        host_thread.join()
        device_thread.join()

        # 设置设备信息
        self.device_name, self.device_properties = self._device_info
        self.service_name = self.device_name
        self.device_info_updated.emit()

        # 配置FastAPI应用状态
        fastapi_app.state.controller = self
        fastapi_app.state.tcp_port = self.tcp_port

        # 启动Uvicorn服务器
        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host="0.0.0.0",
            port=self.port,
            log_level="error",
            lifespan="on",
        )
        self.uvicorn_server_thread = UvicornServer(uvicorn_config)
        self.uvicorn_server_thread.start()

        # 启动等待线程
        waiter_thread = threading.Thread(
            target=self._wait_and_signal_startup, daemon=True
        )
        waiter_thread.start()

        # 更短的延迟启动非关键服务
        QTimer.singleShot(200, self._start_delayed_services)

        self.is_running = True

    def _start_delayed_services(self):
        """延迟启动非关键服务，避免阻塞UI"""
        # 使用已获取的主机IP，避免重复网络调用
        host_ip = getattr(self, "_host_ip", "127.0.0.1")

        # 并行启动发现服务和文件监视器
        def start_discovery():
            # 懒导入发现服务
            from core.discovery import DiscoveryService

            self.discovery_service = DiscoveryService(
                host_ip, self.port, self.service_name, self.device_properties
            )
            self.discovery_service.start()

        def start_watcher():
            self._start_file_watcher()

        # 并行启动服务
        discovery_thread = threading.Thread(target=start_discovery, daemon=True)
        watcher_thread = threading.Thread(target=start_watcher, daemon=True)

        discovery_thread.start()
        watcher_thread.start()

    def _wait_and_signal_startup(self):
        """等待 Uvicorn 启动完毕后, 发射 server_started 信号。"""
        while not getattr(self.uvicorn_server_thread.server, "started", False):
            if self.stop_event.is_set():
                return
            time.sleep(0.1)

        print(
            f"API服务器已在 http://{socket.gethostbyname(socket.gethostname())}:"
            f"{self.port} 启动"
        )
        self.server_started.emit()

    def stop_all_services(self):
        """以正确的顺序, 安全地停止所有服务。"""
        if not self.is_running:
            return
        print("正在关闭所有服务...")
        self.stop_event.set()
        self.watcher_stop_event.set()

        try:
            loop = getattr(fastapi_app.state, "asyncio_loop", None)
            stop_event = getattr(fastapi_app.state, "tcp_stop_event", None)
            if loop and stop_event and loop.is_running() and not stop_event.is_set():
                loop.call_soon_threadsafe(stop_event.set)
        except Exception as e:
            print(f"停止TCP服务器时发生非致命错误: {e}")

        if self.discovery_service:
            self.discovery_service.stop()
        if self.uvicorn_server_thread:
            self.uvicorn_server_thread.stop()
        if self.uvicorn_server_thread:
            self.uvicorn_server_thread.join(timeout=2)
        if self.watcher_thread and self.watcher_thread.is_alive():
            self.watcher_thread.join(timeout=2)

        self.is_running = False
        print("所有服务已关闭。")

    def _start_file_watcher(self):
        """启动文件监视器。"""
        paths = [s["path"] for s in get_shares() if os.path.exists(s["path"])]
        if not paths:
            return

        # 懒导入文件监视器
        from core.file_watcher import start_file_watcher

        def on_change(delete_events=None, moved_events=None):
            if not self.is_running or self.stop_event.is_set():
                return

            # 处理文件变更通知
            event_data = {"event": "refresh_files", "source": "file_watcher"}

            # 获取共享配置，用于确定文件属于哪个共享
            shares = get_shares()
            share_paths = {s["path"]: s["name"] for s in shares}

            # 如果有删除事件，添加到事件数据中
            if delete_events and len(delete_events) > 0:
                # 收集删除事件信息
                deleted_files = []
                for event in delete_events:
                    path = event["path"]
                    # 确定文件所属的共享
                    for share_path, share_name in share_paths.items():
                        if path.startswith(share_path):
                            rel_path = os.path.relpath(path, share_path)
                            deleted_files.append(
                                {
                                    "share_name": share_name,
                                    "path": rel_path.replace("\\", "/"),
                                    "is_directory": event["is_directory"],
                                }
                            )
                            break

                # 如果有删除文件，添加到事件数据中
                if deleted_files:
                    event_data["deleted_files"] = deleted_files

            # 如果有重命名/移动事件，添加到事件数据中
            if moved_events and len(moved_events) > 0:
                # 收集重命名事件信息
                renamed_files = []
                for event in moved_events:
                    src_path = event["src_path"]
                    dest_path = event["dest_path"]
                    # 确定文件所属的共享
                    for share_path, share_name in share_paths.items():
                        if src_path.startswith(share_path) and dest_path.startswith(share_path):
                            src_rel_path = os.path.relpath(src_path, share_path)
                            dest_rel_path = os.path.relpath(dest_path, share_path)
                            renamed_files.append(
                                {
                                    "share_name": share_name,
                                    "old_path": src_rel_path.replace("\\", "/"),
                                    "new_path": dest_rel_path.replace("\\", "/"),
                                    "is_directory": event["is_directory"],
                                }
                            )
                            break

                # 如果有重命名文件，添加到事件数据中
                if renamed_files:
                    event_data["renamed_files"] = renamed_files

            try:
                loop = getattr(fastapi_app.state, "asyncio_loop", None)
                if loop and loop.is_running():

                    async def safe_broadcast():
                        try:
                            await websocket_manager.broadcast(json.dumps(event_data))
                        except Exception as e:
                            print(f"文件监视器广播时出错: {e}")

                    loop.call_soon_threadsafe(loop.create_task, safe_broadcast())
            except Exception:
                pass

        self.watcher_thread = threading.Thread(
            target=start_file_watcher,
            args=(
                [os.path.normpath(p) for p in paths],
                on_change,
                self.watcher_stop_event,
            ),
            daemon=True,
        )
        self.watcher_thread.start()

    def restart_file_watcher(self):
        """重启文件监视器 (例如在配置变更后)。"""
        print("正在请求重启文件监视器...")
        if self.watcher_thread and self.watcher_thread.is_alive():
            self.watcher_stop_event.set()
            self.watcher_thread.join(timeout=2)
            print("旧的文件监视器已停止。")
        self.watcher_stop_event.clear()
        self._start_file_watcher()
