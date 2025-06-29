# 文件: gui/app_controller.py
# (已按 PEP 8 规范格式化, 并修复逻辑问题)
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

from PySide6.QtCore import QObject, Signal

from core.config_loader import get_config, get_shares
from core.discovery import DiscoveryService
from core.file_watcher import start_file_watcher
from core.web_api import app as fastapi_app


class UvicornServer(threading.Thread):
    """在一个独立的线程中运行 Uvicorn 服务器。"""
    def __init__(self, config, started_callback=None):
        super().__init__()
        self.daemon = True
        self._stop_event = threading.Event()
        self.server = uvicorn.Server(config)
        self.started_callback = started_callback

    def run(self):
        """线程的执行体, 运行服务器直到被停止。"""
        self.server.run()

    def stop(self):
        """从外部请求停止服务器。"""
        self.server.should_exit = True

    def wait_for_startup(self):
        """阻塞直到服务器内部的 'started' 标志为 True。"""
        while not self.server.started and not self._stop_event.is_set():
            time.sleep(0.1)
        if self.server.started and self.started_callback:
            self.started_callback()


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
            self.running_config['service']['port'] = self.port
        else:
            self.port = self.running_config.get("service", {}).get("port", 8080)

        self.tcp_port = self.port + 1
        self.device_name = self.running_config.get("service", {}).get(
            "name", "auto"
        )
        self.service_name = self.device_name
        self.device_properties = {}

        self.stop_event = threading.Event()
        self.watcher_stop_event = threading.Event()

        self.uvicorn_server_thread = None
        self.discovery_service = None
        self.watcher_thread = None
        self.is_running = False

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
        try:
            host_ip = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            host_ip = "127.0.0.1"

        print("正在启动所有后台服务...")

        base_name = self.running_config.get("service", {}).get(
            "name", "auto"
        ).strip()
        if not base_name or base_name.lower() == 'auto':
            dynamic_base_name = socket.gethostname()
        else:
            dynamic_base_name = base_name

        if self.port_override:
            self.device_name = f"{dynamic_base_name}-{self.port}"
        else:
            self.device_name = dynamic_base_name
        self.service_name = self.device_name

        self.device_properties = {
            'os': f"{platform.system()} {platform.release()}",
            'user': getpass.getuser(),
            'tcp_port': str(self.tcp_port),
            'dev_type': self._get_dynamic_device_type()
        }
        self.device_info_updated.emit()

        self.discovery_service = DiscoveryService(
            host_ip, self.port, self.service_name, self.device_properties
        )
        self.discovery_service.start()

        self._start_file_watcher()

        fastapi_app.state.controller = self
        fastapi_app.state.tcp_port = self.tcp_port

        uvicorn_config = uvicorn.Config(
            fastapi_app, host="0.0.0.0", port=self.port,
            log_level="info", lifespan="on"
        )
        self.uvicorn_server_thread = UvicornServer(uvicorn_config)
        self.uvicorn_server_thread.start()

        waiter_thread = threading.Thread(
            target=self._wait_and_signal_startup, daemon=True
        )
        waiter_thread.start()
        self.is_running = True

    def _wait_and_signal_startup(self):
        """等待 Uvicorn 启动完毕后, 发射 server_started 信号。"""
        while not self.uvicorn_server_thread.server.started:
            if self.stop_event.is_set():
                return
            time.sleep(0.1)

        print(
            f"API服务器已在 http://{socket.gethostbyname(socket.gethostname())}"
            f":{self.port} 启动"
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
            loop = getattr(fastapi_app.state, 'asyncio_loop', None)
            stop_event = getattr(fastapi_app.state, 'tcp_stop_event', None)
            if loop and stop_event and not stop_event.is_set():
                # 检查循环是否仍在运行, 避免在已关闭的循环上调用
                if loop.is_running():
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
        paths = [s['path'] for s in get_shares() if os.path.exists(s['path'])]
        if not paths:
            print("没有有效的共享文件夹可供监视。")
            return

        normalized_paths = [os.path.normpath(p) for p in paths]
        from core.web_api import manager

        def on_change():
            """当受监控的文件系统发生变化时执行的回调。"""
            # --- 【逻辑修正】 ---
            # 1. 首先检查服务是否仍在运行, 避免在关闭过程中发送不必要的消息
            if not self.is_running or self.stop_event.is_set():
                return

            event_data = {"event": "refresh_files"}
            try:
                # 2. 从 app.state 安全地获取 loop, 如果不存在则不执行
                loop = getattr(fastapi_app.state, 'asyncio_loop', None)
                if loop and loop.is_running():
                    # 3. 在广播任务上创建一个包装任务, 这样可以捕获异常
                    async def safe_broadcast():
                        try:
                            await manager.broadcast(json.dumps(event_data))
                        except Exception as e:
                            print(f"文件监视器广播时出错: {e}")

                    loop.call_soon_threadsafe(loop.create_task, safe_broadcast())
            except Exception:
                # 在关闭期间, loop 可能会变得不可用, 这是正常的。
                # 我们可以安全地忽略这个异常。
                pass

        self.watcher_thread = threading.Thread(
            target=start_file_watcher,
            args=(normalized_paths, on_change, self.watcher_stop_event),
            daemon=True
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