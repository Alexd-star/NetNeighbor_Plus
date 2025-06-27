# 文件: gui/api_client.py
import os
import httpx
from typing import Optional, Generator

class UploadStreamer:
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
    def __len__(self): return self.total_size
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): self.file.close()

class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        # 增加超时配置，防止UI卡死
        self.client = httpx.Client(timeout=10.0)

    def get_ping(self) -> bool:
        try:
            # 使用较短的超时进行ping测试
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
        # 对于下载，使用流式请求并设置更长的超时
        return self.client.stream("GET", url, params=params, timeout=60.0)

    def upload_file_stream(self, share_name: str, dest_path: str, uploader: UploadStreamer):
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path}
        files = {'file': (os.path.basename(uploader.file_path), uploader, 'application/octet-stream')}
        # 上传可能需要很长时间，不设置超时
        response = self.client.post(url, params=params, files=files, timeout=None)
        response.raise_for_status()
        return response.json()