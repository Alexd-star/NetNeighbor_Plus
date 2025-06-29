# 文件: gui/api_client.py (最终版)

import os
import httpx
from typing import Optional


class UploadStreamer:
    """一个可流式读取文件并提供进度的类。"""
    def __init__(self, file_path: str, progress_callback=None, chunk_size: int = 4096):
        self.file_path = file_path
        self.total_size = os.path.getsize(file_path)
        self.chunk_size = chunk_size
        self.sent_bytes = 0
        self.file = open(self.file_path, "rb")
        self.progress_callback = progress_callback

    def read(self, size=-1) -> bytes:
        chunk = self.file.read(self.chunk_size)
        self.sent_bytes += len(chunk)
        if self.progress_callback and self.total_size > 0:
            self.progress_callback(int((self.sent_bytes / self.total_size) * 100))
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
        # 设置一个更长的默认超时时间，以适应大文件/文件夹操作
        self.client = httpx.Client(timeout=30.0)

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
        # timeout=None 允许下载持续进行，不受默认超时限制
        return self.client.stream("GET", url, params=params, timeout=None)

    # 【新功能】请求下载文件夹的ZIP流的客户端方法
    def download_folder_stream(self, share_name: str, folder_path: str):
        """
        请求后端的 /api/v1/download_folder 端点，获取文件夹的ZIP压缩流。
        """
        url = f"{self.base_url}/api/v1/download_folder/{share_name}"
        params = {"folder_path": folder_path}
        # timeout=None 允许下载持续进行
        return self.client.stream("GET", url, params=params, timeout=None)

    def upload_file_stream(self, share_name: str, dest_path: str, uploader: UploadStreamer):
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path}
        files = {'file': (os.path.basename(uploader.file_path), uploader, 'application/octet-stream')}
        # timeout=None 允许上传持续进行
        response = self.client.post(url, params=params, files=files, timeout=None)
        response.raise_for_status()
        return response.json()

    # 【新功能】请求在远程设备上创建目录的客户端方法
    def create_directory(self, share_name: str, path: str):
        """
        请求后端的 /api/v1/create_dir 端点，在远程共享中创建目录。
        """
        url = f"{self.base_url}/api/v1/create_dir/{share_name}"
        params = {"path": path}
        response = self.client.post(url, params=params)
        response.raise_for_status()
        return response.json()