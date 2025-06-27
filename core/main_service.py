# 文件: core/main_service.py (最终确认版)

import os
import socket
import uvicorn
import threading
from .config import config as app_config
from .discovery import DiscoveryService
from .web_api import app, manager
from .tcp_server import run_tcp_server
from .file_watcher import start_file_watcher


def run_service():
    service_config = app_config['service']
    port = service_config['port']
    hostname = socket.gethostname()
    host_ip = socket.gethostbyname(hostname)

    properties = {'os': 'openKylin', 'user': 'testuser', 'tcp_port': str(8081)}
    discovery = DiscoveryService(host_ip, port, service_config['name'], properties)
    discovery.start()

    tcp_thread = threading.Thread(target=run_tcp_server, daemon=True)
    tcp_thread.start()

    original_paths = [s['path'] for s in app_config.get('shares', [])]
    normalized_paths = [os.path.normpath(p) for p in original_paths]

    if normalized_paths:
        import asyncio
        def on_change():
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(asyncio.create_task, manager.broadcast("refresh_files"))
                else:
                    asyncio.run(manager.broadcast("refresh_files"))
            except RuntimeError:
                asyncio.run(manager.broadcast("refresh_files"))

        watcher_thread = threading.Thread(target=start_file_watcher, args=(normalized_paths, on_change), daemon=True)
        watcher_thread.start()

    print(f"API服务器将在 http://{host_ip}:{port} 启动")
    uvicorn.run(app, host=host_ip, port=port, log_level="info")