import os
import socket
import uvicorn
import threading
import asyncio

# 从其他核心模块导入必要的组件
from .config import config as app_config
from .discovery import DiscoveryService
from .web_api import app, manager  # 导入FastAPI应用实例和WebSocket管理器
from .tcp_server import run_tcp_server
from .file_watcher import start_file_watcher


def run_service(controller):
    """
    启动所有后端服务。
    这个函数现在由AppController调用，并接收controller实例作为参数，
    以获取正确的、实例独有的配置信息。
    """
    # 从controller获取此实例独有的端口和设备名
    port = controller.port
    service_name = controller.service_name
    tcp_port = controller.tcp_port

    hostname = socket.gethostname()
    host_ip = socket.gethostbyname(hostname)

    # 1. 启动设备发现服务，使用实例独有的服务名进行广播
    properties = {'os': 'openKylin', 'user': 'testuser', 'tcp_port': str(tcp_port)}
    controller.discovery_service = DiscoveryService(host_ip, port, service_name, properties)
    controller.discovery_service.start()

    # 2. 在后台线程中启动TCP高速传输服务器
    controller.tcp_server_thread = threading.Thread(target=run_tcp_server, args=(tcp_port, controller.stop_event),
                                                    daemon=True)
    controller.tcp_server_thread.start()

    # 3. 在后台线程中启动文件监视器
    original_paths = [s['path'] for s in app_config.get('shares', [])]
    if original_paths:
        normalized_paths = [os.path.normpath(p) for p in original_paths]

        def on_change():
            """定义当文件变化时要执行的回调函数"""
            try:
                # 在正确的事件循环中安全地广播WebSocket消息
                loop = asyncio.get_event_loop_policy().get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(asyncio.create_task, manager.broadcast("refresh_files"))
                else:
                    # 这是备用方案，适用于没有正在运行的循环的罕见情况
                    asyncio.run(manager.broadcast("refresh_files"))
            except RuntimeError:
                # 如果当前线程没有事件循环，则创建一个新的
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(manager.broadcast("refresh_files"))

        controller.watcher_thread = threading.Thread(target=start_file_watcher,
                                                     args=(normalized_paths, on_change, controller.stop_event),
                                                     daemon=True)
        controller.watcher_thread.start()

    print(f"API服务器将在 http://{host_ip}:{port} 启动")

    # 4. 启动Uvicorn/FastAPI服务器
    # 注意：我们不再使用手动创建Config和Server的方式，
    # 因为在一体化应用中，由主线程的AppController来管理Uvicorn线程的生命周期是更清晰的做法。
    # AppController中的UvicornServer类已经处理了这个问题。
    # 这段代码实际上是由AppController里的UvicornServer线程来执行的。
    # 这里我们保留一个清晰的逻辑注释。
    pass  # Uvicorn的启动和运行逻辑已移至AppController中的UvicornServer线程