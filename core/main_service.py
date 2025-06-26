import socket
import uvicorn
import threading  # 导入线程库
from .config import config as app_config
from .discovery import DiscoveryService
from .web_api import app
from .tcp_server import run_tcp_server  # 导入TCP服务器启动函数


def run_service():
    """
    启动所有后端服务，包括设备发现、HTTP API和TCP传输服务器。
    """
    service_config = app_config['service']
    port = service_config['port']

    hostname = socket.gethostname()
    host_ip = socket.gethostbyname(hostname)

    # 启动设备发现服务
    # 我们需要在广播信息里告诉别人我们的TCP端口是多少
    properties = {
        'os': 'openKylin',
        'user': 'testuser',
        'tcp_port': str(8081)  # 将TCP端口作为属性广播出去
    }
    discovery = DiscoveryService(
        host_ip=host_ip,
        port=port,
        service_name=service_config['name'],
        service_properties=properties
    )
    discovery.start()

    # 在一个独立的后台线程中启动TCP服务器
    tcp_thread = threading.Thread(target=run_tcp_server)
    tcp_thread.daemon = True
    tcp_thread.start()

    print(f"API服务器将在 http://{host_ip}:{port} 启动")

    # 启动uvicorn（这个会阻塞主线程）
    uvicorn.run(
        app, host=host_ip, port=port, log_level="info"
    )