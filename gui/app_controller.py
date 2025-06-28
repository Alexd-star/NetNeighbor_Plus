# 文件: gui/app_controller.py (修复)
import os
import socket
import threading
import uvicorn
import time
import json
import asyncio
from PySide6.QtCore import QObject, Signal
from core.config_loader import get_config, get_shares
from core.discovery import DiscoveryService
from core.web_api import app as fastapi_app
from core.tcp_server import run_tcp_server
from core.file_watcher import start_file_watcher


class UvicornServer(threading.Thread):
    def __init__(self, config, started_callback=None):
        super().__init__()
        self.daemon = True
        self._stop_event = threading.Event()
        self.server = uvicorn.Server(config)
        self.started_callback = started_callback

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True

    def wait_for_startup(self):
        while not self.server.started and not self._stop_event.is_set():
            time.sleep(0.1)
        if self.server.started and self.started_callback:
            self.started_callback()


class AppController(QObject):
    server_started = Signal()

    def __init__(self, port_override=None, parent=None):
        super().__init__(parent)
        config = get_config()
        self.port_override = port_override
        self.port = port_override or config.get("service", {}).get("port", 8080)
        self.tcp_port = self.port + 1

        original_name = config.get("service", {}).get("name", "DefaultPC")
        self.device_name = f"{original_name}-{self.port}" if port_override else original_name
        self.service_name = self.device_name

        self.running_config = config
        self.running_config['service']['port'] = self.port
        self.running_config['service']['name'] = self.device_name

        self.stop_event = threading.Event()
        self.watcher_stop_event = threading.Event()
        self.uvicorn_server_thread, self.discovery_service, self.tcp_server_thread, self.watcher_thread, self.is_running = None, None, None, None, False

    def start_all_services(self):
        if self.is_running: return
        try:
            host_ip = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            host_ip = "127.0.0.1"

        print("正在启动所有后台服务...")

        properties = {'os': 'openKylin', 'user': 'testuser', 'tcp_port': str(self.tcp_port)}
        self.discovery_service = DiscoveryService(host_ip, self.port, self.service_name, properties)
        self.discovery_service.start()

        self.tcp_server_thread = threading.Thread(target=run_tcp_server, args=(self.tcp_port, self.stop_event),
                                                  daemon=True)
        self.tcp_server_thread.start()

        self._start_file_watcher()

        # 【修复】将controller实例存入FastAPI应用状态，方便API接口访问
        fastapi_app.state.controller = self

        uvicorn_config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=self.port, log_level="info")
        self.uvicorn_server_thread = UvicornServer(uvicorn_config)
        self.uvicorn_server_thread.start()

        waiter_thread = threading.Thread(target=self._wait_and_signal_startup, daemon=True)
        waiter_thread.start()

        self.is_running = True

    def _wait_and_signal_startup(self):
        while not self.uvicorn_server_thread.server.started:
            if self.stop_event.is_set():
                return
            time.sleep(0.1)

        print(f"API服务器已在 http://{socket.gethostbyname(socket.gethostname())}:{self.port} 启动")
        self.server_started.emit()

    def stop_all_services(self):
        if not self.is_running: return
        print("正在关闭所有服务...")
        self.stop_event.set()
        self.watcher_stop_event.set()

        if self.discovery_service: self.discovery_service.stop()
        if self.uvicorn_server_thread: self.uvicorn_server_thread.stop()

        if self.uvicorn_server_thread: self.uvicorn_server_thread.join(timeout=2)
        if self.tcp_server_thread: self.tcp_server_thread.join(timeout=2)
        if self.watcher_thread and self.watcher_thread.is_alive(): self.watcher_thread.join(timeout=2)

        self.is_running = False
        print("所有服务已关闭。")

    def _start_file_watcher(self):
        original_paths = [s['path'] for s in get_shares() if os.path.exists(s['path'])]
        if not original_paths:
            print("没有有效的共享文件夹可供监视。")
            return

        normalized_paths = [os.path.normpath(p) for p in original_paths]
        from core.web_api import manager

        def on_change():
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
                event_data = {"event": "refresh_files"}
                if loop.is_running():
                    loop.call_soon_threadsafe(asyncio.create_task, manager.broadcast(json.dumps(event_data)))
                else:
                    asyncio.run(manager.broadcast(json.dumps(event_data)))
            except RuntimeError:
                loop = asyncio.new_event_loop();
                asyncio.set_event_loop(loop)
                loop.run_until_complete(manager.broadcast(json.dumps(event_data)))

        self.watcher_thread = threading.Thread(target=start_file_watcher,
                                               args=(normalized_paths, on_change, self.watcher_stop_event), daemon=True)
        self.watcher_thread.start()
        print(f"文件监视器已启动，正在监视: {normalized_paths}")

    def restart_file_watcher(self):
        print("正在请求重启文件监视器...")
        if self.watcher_thread and self.watcher_thread.is_alive():
            self.watcher_stop_event.set()
            self.watcher_thread.join(timeout=2)
            print("旧的文件监视器已停止。")

        self.watcher_stop_event.clear()

        self._start_file_watcher()