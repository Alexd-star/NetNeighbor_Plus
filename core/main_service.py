# 文件: core/main_service.py (最终HTTP版)

import socket
import uvicorn
from .config import config as app_config
from .discovery import DiscoveryService
from .web_api import app


def run_service():
    """
    启动所有后端服务，以简单的HTTP模式运行。
    """
    service_config = app_config['service']
    port = service_config['port']

    hostname = socket.gethostname()
    host_ip = socket.gethostbyname(hostname)

    # 启动设备发现服务
    properties = {'os': 'openKylin', 'user': 'testuser'}
    discovery = DiscoveryService(
        host_ip=host_ip,
        port=port,
        service_name=service_config['name'],
        service_properties=properties
    )
    discovery.start()

    print(f"API服务器将在 http://{host_ip}:{port} 启动")

    # 使用最简单的HTTP模式启动uvicorn，移除所有SSL相关参数
    uvicorn.run(
        app,
        host=host_ip,
        port=port,
        log_level="info"
    )