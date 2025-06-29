# 文件: gui/api_client.py
# (已修改 UploadStreamer 以支持速度计算)

import os
import httpx
from typing import Optional, Callable, Union


class UploadStreamer:
    """
    一个可流式读取文件并提供进度的类。

    【修改】现在它接受一个回调函数, 该函数在每次读取块后被调用。
    """

    def __init__(
            self,
            file_path: str,
            # 回调函数接收一个参数: 读取的字节数
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
            # 调用回调, 传递读取到的块的长度
            self.progress_callback(len(chunk))
        return chunk

    def __len__(self):
        return self.total_size

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file.close()


class ApiClient:
    """用于与后端API交互的客户端。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)

    # ... 其他 ApiClient 方法保持不变 ...
    def notify_shares_changed(self):
        try:
            response = self.client.post(f"{self.base_url}/api/v1/internal/notify_shares_changed")
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
            response = self.client.get(f"{self.base_url}/api/v1/peers")
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求设备列表失败 - {e}")
            return None

    def get_shares(self) -> Optional[list]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/shares")
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求共享列表失败 - {e}")
            return None

    def get_files(self, share_name: str, path: str = "/") -> Optional[list]:
        try:
            params = {"path": path}
            url = f"{self.base_url}/api/v1/files/{share_name}"
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - {e}")
            return None

    def download_file_stream(self, share_name: str, file_path: str):
        url = f"{self.base_url}/api/v1/download/{share_name}"
        params = {"file_path": file_path}
        return self.client.stream("GET", url, params=params, timeout=None)

    def download_folder_stream(self, share_name: str, folder_path: str):
        """请求后端的 /api/v1/download_folder 端点。"""
        url = f"{self.base_url}/api/v1/download_folder/{share_name}"
        params = {"folder_path": folder_path}
        return self.client.stream("GET", url, params=params, timeout=None)

    def upload_file_stream(self, share_name: str, dest_path: str, uploader: UploadStreamer):
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path}
        files = {'file': (os.path.basename(uploader.file_path), uploader, 'application/octet-stream')}
        response = self.client.post(url, params=params, files=files, timeout=None)
        response.raise_for_status()
        return response.json()

    def create_directory(self, share_name: str, path: str):
        """请求后端的 /api/v1/create_dir 端点。"""
        url = f"{self.base_url}/api/v1/create_dir/{share_name}"
        params = {"path": path}
        response = self.client.post(url, params=params)
        response.raise_for_status()
        return response.json()