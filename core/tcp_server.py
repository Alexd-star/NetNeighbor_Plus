import socket
import threading
import json
import os
from .config import config

# 【注意】这个端口需要和API服务的端口错开
TCP_PORT = 8081


def get_safe_path_for_tcp(share_name: str, sub_path: str = "/") -> str:
    """一个专门为TCP服务使用的安全路径获取函数"""
    target_share = next((s for s in config.get("shares", []) if s["name"] == share_name), None)
    if not target_share:
        raise FileNotFoundError(f"Share '{share_name}' not found")
    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)
    if not os.path.abspath(full_path).startswith(base_path):
        raise PermissionError("Access to this path is denied")
    return full_path


def handle_client_connection(client_socket):
    """
    处理单个客户端连接的函数，每个连接都在一个独立的线程中运行。
    """
    try:
        # 1. 接收元数据 (一个描述请求的JSON)
        header_data = client_socket.recv(1024).decode('utf-8')
        header = json.loads(header_data)

        action = header.get("action")
        share_name = header.get("share_name")
        file_path = header.get("file_path")

        if not all([action, share_name, file_path]):
            raise ValueError("元数据不完整")

        # 2. 根据动作执行操作
        if action == "download":
            absolute_path = get_safe_path_for_tcp(share_name, file_path)
            if not os.path.isfile(absolute_path):
                raise FileNotFoundError("File not found on server")

            # 发送确认信息和文件大小
            file_size = os.path.getsize(absolute_path)
            client_socket.sendall(json.dumps({"status": "ok", "size": file_size}).encode('utf-8'))

            # 等待客户端的“准备好接收”信号
            client_socket.recv(1024)

            # 发送文件内容
            with open(absolute_path, 'rb') as f:
                while chunk := f.read(4 * 1024 * 1024):  # 每次发送4MB
                    client_socket.sendall(chunk)

        else:
            raise ValueError(f"未知的动作: {action}")

    except (json.JSONDecodeError, ValueError, FileNotFoundError, PermissionError) as e:
        try:
            # 向客户端发送错误信息
            client_socket.sendall(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except socket.error:
            pass  # 如果发送都失败了，就没必要处理了
        print(f"处理客户端连接时发生错误: {e}")
    finally:
        client_socket.close()


def run_tcp_server():
    """
    启动TCP服务器，持续监听并接受客户端连接。
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('', TCP_PORT))
    server_socket.listen(5)
    print(f"TCP高速传输服务器已在端口 {TCP_PORT} 启动...")

    while True:
        client_sock, address = server_socket.accept()
        print(f"接受到来自 {address} 的TCP连接")
        # 为每个新连接创建一个独立的线程来处理，防止阻塞
        thread = threading.Thread(target=handle_client_connection, args=(client_sock,))
        thread.daemon = True  # 设置为守护线程，主程序退出时它也退出
        thread.start()