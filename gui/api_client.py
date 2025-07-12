# 文件: gui/api_client.py (最终架构版)

import os
import httpx
import json
import socket
from typing import Optional, Callable, Union


# ------------------- 新增的 TCP 下载器类 -------------------
class TcpDownloader:
    """
    一个实现了上下文管理器协议的TCP下载器。
    它负责建立、维持和在下载结束后安全关闭TCP连接。
    """

    def __init__(self, host: str, port: int, request_header: dict):
        self.sock = None  # 先初始化为 None
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((host, port))

            # 发送请求头
            self.sock.sendall(json.dumps(request_header).encode('utf-8'))

            # 接收响应头
            response_data = self.sock.recv(1024)
            if not response_data:
                raise ConnectionAbortedError("Server closed connection unexpectedly.")

            response_header = json.loads(response_data.decode('utf-8'))
            if response_header.get("status") != "ok":
                raise ConnectionAbortedError(f"Server error: {response_header.get('message', 'Unknown error')}")

            # 发送准备就绪信号
            self.sock.sendall(b'ready')
            self.sock.settimeout(None)  # 为数据传输取消超时
        except Exception:
            if self.sock:
                self.sock.close()
            raise

    def __iter__(self):
        """让这个类的实例可以被 for 循环迭代，逐块产出下载数据。"""
        while True:
            chunk = self.sock.recv(65536)
            if not chunk:
                break
            yield chunk

    def __enter__(self):
        """进入 'with' 语句块时被调用，返回自身实例。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出 'with' 语句块时被调用，确保 socket 被关闭。"""
        if self.sock:
            self.sock.close()


# ------------------- UploadStreamer (无需改动) -------------------
class UploadStreamer:
    # ... 此类代码保持不变 ...
    def __init__(
            self,
            file_path: str,
            progress_callback: Optional[Callable[[int], None]] = None,
            chunk_size: int = 4096
    ):
        self.file_path = file_path
        self.total_size = os.path.getsize(file_path)
        self.chunk_size = chunk_size
        self.file = open(self.file_path, "rb")
        self.progress_callback = progress_callback

    def read(self, size: int = -1) -> bytes:
        chunk = self.file.read(self.chunk_size)
        if self.progress_callback:
            self.progress_callback(len(chunk))
        return chunk

    def __len__(self):
        return self.total_size

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file.close()


# ------------------- ApiClient (修改 download_folder_tcp) -------------------
class ApiClient:
    """用于与后端API交互的客户端。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.Client(timeout=5.0)

    # ... get_ping, get_peers, get_shares 等函数保持不变 ...

    def notify_shares_changed(self):
        try:
            response = self.client.post(f"{self.base_url}/api/v1/internal/notify_shares_changed", timeout=5.0)
            response.raise_for_status()
            return True
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"Error notifying peers of share change: {e}")
            return False

    def get_ping(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/ping", timeout=2.0)
            return response.status_code == 200
        except (httpx.RequestError, httpx.HTTPStatusError):
            return False

    def get_peers(self) -> Optional[dict]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/peers", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求设备列表失败 - {e}")
            return None

    def get_shares(self) -> Optional[list]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/shares", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求共享列表失败 - {e}")
            return None

    def get_files(self, share_name: str, path: str = "/") -> Optional[list]:
        try:
            params = {"path": path}
            url = f"{self.base_url}/api/v1/files/{share_name}"
            response = self.client.get(url, params=params, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - {e}")
            return None

    def download_file_stream(self, share_name: str, file_path: str):
        url = f"{self.base_url}/api/v1/download/{share_name}"
        params = {"file_path": file_path}
        return self.client.stream("GET", url, params=params, timeout=None)


    def upload_file_stream(self, share_name: str, dest_path: str, uploader: UploadStreamer):
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path}
        files = {'file': (os.path.basename(uploader.file_path), uploader, 'application/octet-stream')}
        response = self.client.post(url, params=params, files=files, timeout=None)
        response.raise_for_status()
        return response.json()

    def create_directory(self, share_name: str, path: str):
        url = f"{self.base_url}/api/v1/create_dir/{share_name}"
        params = {"path": path}
        response = self.client.post(url, params=params, timeout=5.0)
        response.raise_for_status()
        return response.json()
        
    def delete_file(self, share_name: str, file_path: str):
        """删除文件或文件夹"""
        try:
            url = f"{self.base_url}/api/v1/delete/{share_name}"
            params = {"file_path": file_path}
            response = self.client.delete(url, params=params, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 删除文件 '{file_path}' 失败 - {e}")
            return None
            
    def rename_file(self, share_name: str, file_path: str, new_name: str):
        """重命名文件或文件夹"""
        try:
            url = f"{self.base_url}/api/v1/rename/{share_name}"
            params = {"file_path": file_path, "new_name": new_name}
            response = self.client.put(url, params=params, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 重命名文件 '{file_path}' 失败 - {e}")
            return None

    def download_folder_tcp(self, share_name: str, remote_path: str) -> TcpDownloader:
        """
        连接到对方的高速TCP传输服务。
        【核心修改】: 此函数现在返回一个 TcpDownloader 的实例。
        """
        host = self.base_url.split('//')[1].split(':')[0]

        peers_data = self.get_peers()
        tcp_port = None
        if peers_data:
            for name, data in peers_data.items():
                if data['address'] == host:
                    tcp_port = int(data.get('properties', {}).get('tcp_port', 0))
                    break

        if not tcp_port:
            raise ConnectionError(f"无法找到设备 {host} 的TCP传输端口。")

        request_header = {
            "action": "download_folder",
            "share_name": share_name,
            "remote_path": remote_path
        }

        # 返回一个全新的、管理着TCP连接的下载器对象
        return TcpDownloader(host, tcp_port, request_header)