# 文件: gui/api_client.py (最终HTTP版)

import os
import httpx
from typing import Optional


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        # 创建一个普通的HTTP客户端，移除所有SSL/TLS相关的verify参数
        self.client = httpx.Client(timeout=5.0)

    def get_peers(self) -> Optional[dict]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/peers")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"错误: 请求设备列表失败 - {e}")
            return None

    def get_shares(self) -> Optional[list]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/shares")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"错误: 请求共享列表失败 - {e}")
            return None

    def get_files(self, share_name: str, path: str = "/") -> Optional[list]:
        try:
            params = {"path": path}
            url = f"{self.base_url}/api/v1/files/{share_name}"
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - {e}")
            return None

    # 注意：这两个流式传输的方法保持不变，因为httpx会自动处理HTTP和HTTPS
    def download_file_stream(self, share_name: str, file_path: str):
        url = f"{self.base_url}/api/v1/download/{share_name}"
        params = {"file_path": file_path}
        return self.client.stream("GET", url, params=params, timeout=60.0)

    def upload_file_stream(self, share_name: str, dest_path: str, local_file_path: str):
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path}
        file_name = os.path.basename(local_file_path)

        with open(local_file_path, "rb") as f:
            files = {'file': (file_name, f)}
            response = self.client.post(url, params=params, files=files, timeout=None)
            response.raise_for_status()
            return response.json()