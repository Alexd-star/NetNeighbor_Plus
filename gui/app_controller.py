# 文件: gui/app_controller.py (修复)
import os
import socket
import threading
import uvicorn
import time
import platform
import getpass
import json
import asyncio
from PySide6.QtCore import QObject, Signal
from core.config_loader import get_config,load_config, get_shares
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
    # 【新增】定义一个信号，用于在设备信息就绪后通知UI
    device_info_updated = Signal()

    def __init__(self, port_override=None, parent=None):
        super().__init__(parent)
        # 【修复】加载原始配置，而不是使用可能被修改的全局单例
        self.running_config = load_config()
        self.port_override = port_override
        self.port = port_override or self.running_config.get("service", {}).get("port", 8080)
        self.tcp_port = self.port + 1

        # 【修复】初始化时，只使用配置文件中的原始名字作为临时名字。
        # 不再拼接端口号，避免污染配置。
        # 最终的、正确的设备名将在 start_all_services 中确定。
        self.device_name = self.running_config.get("service", {}).get("name", "auto")
        self.service_name = self.device_name

        self.device_properties = {}

        self.running_config['service']['port'] = self.port

        self.stop_event = threading.Event()
        self.watcher_stop_event = threading.Event()
        self.uvicorn_server_thread, self.discovery_service, self.tcp_server_thread, self.watcher_thread, self.is_running = None, None, None, None, False

    # 【新增】动态判断设备类型的辅助方法
    def _get_dynamic_device_type(self) -> str:
        system = platform.system().lower()
        if system in ["windows", "linux", "darwin"]:
            return "PC"
        elif system == "android":
            return "Phone/Tablet"
        else:
            return "Unknown Device"

    def start_all_services(self):
        if self.is_running: return
        try:
            host_ip = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            host_ip = "127.0.0.1"

        print("正在启动所有后台服务...")

        # --- 【核心修复】重新构建设备名生成逻辑 ---
        # 1. 从原始配置文件中获取基础设备名（"auto" 或用户自定义名）
        base_name = self.running_config.get("service", {}).get("name", "auto").strip()

        # 2. 如果是 "auto"，则动态获取主机名，否则使用用户自定义名
        if not base_name or base_name.lower() == 'auto':
            dynamic_base_name = socket.gethostname()
        else:
            dynamic_base_name = base_name

        # 3. 只有在提供了端口覆盖参数时，才在名字后附加端口号
        if self.port_override:
            self.device_name = f"{dynamic_base_name}-{self.port}"
        else:
            self.device_name = dynamic_base_name

        self.service_name = self.device_name
        # ----------------------------------------------

        # 动态构建广播属性并存储
        self.device_properties = {
            'os': f"{platform.system()} {platform.release()}",
            'user': getpass.getuser(),
            'tcp_port': str(self.tcp_port),
            'dev_type': self._get_dynamic_device_type()
        }

        # 发射信号通知UI更新
        self.device_info_updated.emit()

        # 使用最终确定的动态信息启动服务
        self.discovery_service = DiscoveryService(host_ip, self.port, self.service_name, self.device_properties)
        self.discovery_service.start()

        self.tcp_server_thread = threading.Thread(target=run_tcp_server, args=(self.tcp_port, self.stop_event),
                                                  daemon=True)
        self.tcp_server_thread.start()

        self._start_file_watcher()

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
            # 【BUG修复】将 event_data 定义移到 try 块之外
            event_data = {"event": "refresh_files"}
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
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

    def restart_file_watcher(self):
        print("正在请求重启文件监视器...")
        if self.watcher_thread and self.watcher_thread.is_alive():
            self.watcher_stop_event.set()
            self.watcher_thread.join(timeout=2)
            print("旧的文件监视器已停止。")

        self.watcher_stop_event.clear()

        self._start_file_watcher()