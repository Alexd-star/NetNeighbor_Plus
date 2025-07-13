# 文件: gui/api_client.py

import io
import json
import os
import socket
import tarfile
import threading
from typing import Optional, Callable, Union

import httpx


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
            self.sock.sendall(json.dumps(request_header).encode("utf-8"))

            # 接收响应头
            response_data = self.sock.recv(1024)
            if not response_data:
                raise ConnectionAbortedError("Server closed connection unexpectedly.")

            response_header = json.loads(response_data.decode("utf-8"))
            if response_header.get("status") != "ok":
                raise ConnectionAbortedError(
                    f"Server error: {response_header.get('message', 'Unknown error')}"
                )

            # 发送准备就绪信号
            self.sock.sendall(b"ready")
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


class TarUploader:
    """
    一个实现了文件夹打包为tar流的上传器。
    它负责将整个文件夹打包为tar格式，并提供流式读取接口。
    """

    def __init__(
            self,
            folder_path: str,
            progress_callback: Optional[Callable[[int], None]] = None,
        chunk_size: int = 65536,  # 64KB
    ):
        self.folder_path = folder_path
        self.progress_callback = progress_callback
        self.chunk_size = chunk_size
        self.total_size = self._calculate_total_size()
        
        # 创建管道用于流式处理
        self.read_pipe, self.write_pipe = os.pipe()
        self.tar_thread = None
        self._start_tar_thread()
    
    def _calculate_total_size(self):
        """计算文件夹中所有文件的总大小"""
        total = 0
        for root, _, files in os.walk(self.folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    total += os.path.getsize(file_path)
        return total
    
    def _start_tar_thread(self):
        """在后台线程中启动tar打包过程"""

        def tar_worker():
            try:
                with os.fdopen(self.write_pipe, "wb") as write_pipe:
                    with tarfile.open(
                        fileobj=write_pipe, mode="w|", format=tarfile.GNU_FORMAT
                    ) as tar:
                        # 添加文件夹到tar
                        folder_name = os.path.basename(self.folder_path)
                        tar.add(self.folder_path, arcname=folder_name, recursive=True)
            except Exception as e:
                print(f"Tar打包过程出错: {e}")
                
        # 启动打包线程
        self.tar_thread = threading.Thread(target=tar_worker)
        self.tar_thread.daemon = True
        self.tar_thread.start()
    
    def read(self, size: int = -1) -> bytes:
        """读取指定大小的数据块"""
        try:
            # 从管道读取数据
            chunk = os.read(self.read_pipe, self.chunk_size if size <= 0 else size)
            if self.progress_callback and chunk:
                self.progress_callback(len(chunk))
            return chunk
        except Exception as e:
            print(f"读取tar数据时出错: {e}")
            return b""
    
    def __len__(self):
        """返回tar文件的总大小（估计值）"""
        # 由于流式处理，无法精确知道tar的大小，返回原始文件大小的估计值
        # tar格式会有一些额外的头信息，所以增加10%作为估计
        return int(self.total_size * 1.1)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """确保资源被正确释放"""
        try:
            # 关闭读取管道
            if hasattr(self, "read_pipe") and self.read_pipe is not None:
                os.close(self.read_pipe)
                self.read_pipe = None
                
            # 等待tar线程完成
            if self.tar_thread and self.tar_thread.is_alive():
                self.tar_thread.join(1.0)  # 等待最多1秒
        except Exception as e:
            print(f"关闭TarUploader资源时出错: {e}")


class UploadStreamer:
    def __init__(
            self,
            file_path: str,
            progress_callback: Optional[Callable[[int], None]] = None,
        chunk_size: int = 4096,
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


class ApiClient:
    """API客户端，负责与远程API通信。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.Client(timeout=None)

    def get_shares(self) -> Optional[list]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/shares", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求共享列表失败 - {e}")
            return None

    def get_peers(self) -> Optional[dict]:
        try:
            response = self.client.get(f"{self.base_url}/api/v1/peers", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"错误: 请求设备列表失败 - {e}")
            return None
            
    def get_ping(self) -> bool:
        """发送ping请求，用于测量延迟"""
        try:
            response = self.client.get(f"{self.base_url}/api/v1/ping", timeout=3.0)
            response.raise_for_status()
            return True
        except httpx.ConnectError as e:
            print(f"Ping失败: 连接错误 - {e}")
            return False
        except httpx.TimeoutException as e:
            print(f"Ping失败: 连接超时 - {e}")
            return False
        except httpx.HTTPStatusError as e:
            print(f"Ping失败: HTTP状态错误 - {e}")
            return False
        except Exception as e:
            print(f"Ping失败: 未知错误 - {e}")
            return False

    def get_files(self, share_name: str, path: str = "/") -> Optional[list]:
        try:
            params = {"path": path}
            url = f"{self.base_url}/api/v1/files/{share_name}"
            response = self.client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            return result
        except httpx.ConnectError as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - 连接错误: {e}")
            return None
        except httpx.TimeoutException as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - 超时: {e}")
            return None
        except httpx.HTTPStatusError as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - HTTP状态错误: {e}")
            return None
        except Exception as e:
            print(f"错误: 请求文件列表'{share_name}{path}'失败 - 未知错误: {e}")
            return None
            
    def delete_file(self, share_name: str, file_path: str) -> bool:
        """删除远程文件或文件夹"""
        try:
            url = f"{self.base_url}/api/v1/delete/{share_name}"
            params = {"file_path": file_path}
            response = self.client.delete(url, params=params, timeout=10.0)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"删除文件失败: {e}")
            return False
            
    def rename_file(self, share_name: str, file_path: str, new_name: str) -> bool:
        """重命名远程文件或文件夹"""
        try:
            url = f"{self.base_url}/api/v1/rename/{share_name}"
            params = {"file_path": file_path, "new_name": new_name}
            response = self.client.post(url, params=params, timeout=5.0)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"重命名文件失败: {e}")
            return False
            
    def check_folder_exists(
        self, share_name: str, dest_path: str, folder_name: str
    ) -> bool:
        """检查远程目录中是否已存在同名文件夹"""
        try:
            # 构建完整路径
            full_path = f"{dest_path}/{folder_name}".replace("//", "/")
            # 尝试获取该路径的文件列表，如果成功则说明文件夹存在
            files = self.get_files(share_name, full_path)
            return files is not None
        except Exception as e:
            print(f"检查文件夹是否存在时出错: {e}")
            return False

    def download_file_stream(self, share_name: str, file_path: str):
        url = f"{self.base_url}/api/v1/download/{share_name}"
        params = {"file_path": file_path}
        return self.client.stream("GET", url, params=params, timeout=None)

    def upload_file_stream(
        self,
        share_name: str,
        dest_path: str,
        uploader: UploadStreamer,
        conflict_action: str = "overwrite",
    ):
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path, "conflict_action": conflict_action}
        files = {
            "file": (
                os.path.basename(uploader.file_path),
                uploader,
                "application/octet-stream",
            )
        }
        response = self.client.post(url, params=params, files=files, timeout=None)
        response.raise_for_status()
        return response.json()
        
    def check_file_exists(self, share_name: str, dest_path: str, filename: str):
        """检查远程目录中是否已存在同名文件"""
        url = f"{self.base_url}/api/v1/upload/{share_name}"
        params = {"dest_path": dest_path, "conflict_action": "check"}
        # 创建一个空文件对象，仅用于检查文件是否存在
        empty_content = b""
        files = {"file": (filename, empty_content, "application/octet-stream")}
        try:
            response = self.client.post(url, params=params, files=files, timeout=5.0)
            response.raise_for_status()
            return response.json().get("exists", False)
        except Exception:
            return False
            
    def create_directory(self, share_name: str, path: str) -> bool:
        """在远程创建目录"""
        url = f"{self.base_url}/api/v1/create_dir/{share_name}"
        params = {"path": path}
        try:
            response = self.client.post(url, params=params, timeout=5.0)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"创建目录失败: {e}")
            return False
            
    def notify_shares_changed(self) -> bool:
        """通知服务器共享配置已更改"""
        try:
            url = f"{self.base_url}/api/v1/notify_shares_changed"
            response = self.client.post(url, timeout=5.0)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"通知共享变更失败: {e}")
            return False
            
    def notify_file_changed(self, share_name: str, path: str) -> bool:
        """通知服务器文件已更改"""
        try:
            url = f"{self.base_url}/api/v1/notify_file_changed"
            data = {"share_name": share_name, "path": path}
            response = self.client.post(url, json=data, timeout=5.0)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"通知文件变更失败: {e}")
            return False

    def download_folder_tcp(self, share_name: str, remote_path: str) -> TcpDownloader:
        """连接到对方的高速TCP传输服务。"""
        host = self.base_url.split("//")[1].split(":")[0]

        peers_data = self.get_peers()
        tcp_port = None
        if peers_data:
            for name, data in peers_data.items():
                if data["address"] == host:
                    tcp_port = int(data.get("properties", {}).get("tcp_port", 0))
                    break

        if not tcp_port:
            raise ConnectionError(f"无法找到设备 {host} 的TCP传输端口。")

        request_header = {
            "action": "download_folder",
            "share_name": share_name,
            "remote_path": remote_path,
        }

        # 返回一个全新的、管理着TCP连接的下载器对象
        return TcpDownloader(host, tcp_port, request_header)
        
    def upload_folder_tar(
        self,
        share_name: str,
        dest_path: str,
        uploader: TarUploader,
        conflict_action: str = "overwrite",
    ):
        """通过tar流式上传整个文件夹"""
        url = f"{self.base_url}/api/v1/upload_folder_tar/{share_name}"
        params = {"dest_path": dest_path, "conflict_action": conflict_action}
        
        # 使用文件夹名称作为tar文件名
        folder_name = os.path.basename(uploader.folder_path)
        files = {"file": (f"{folder_name}.tar", uploader, "application/x-tar")}
        
        response = self.client.post(url, params=params, files=files, timeout=None)
        response.raise_for_status()
        return response.json()
