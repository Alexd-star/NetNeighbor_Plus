# 文件: core/tcp_server.py (优化)
import socket
import threading
import json
import os
from .config_loader import get_shares

def get_safe_path_for_tcp(share_name: str, sub_path: str = "/") -> str:
    target_share = next((s for s in get_shares() if s["name"] == share_name), None)
    if not target_share: raise FileNotFoundError(f"Share '{share_name}' not found")
    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)
    if not os.path.abspath(full_path).startswith(base_path): raise PermissionError("Access denied")
    return full_path

def handle_client_connection(client_socket):
    try:
        header_data = client_socket.recv(1024).decode('utf-8')
        if not header_data:
            return # 客户端未发送数据就断开
        header = json.loads(header_data)
        action, share_name, file_path = header.get("action"), header.get("share_name"), header.get("file_path")
        if not all([action, share_name, file_path]): raise ValueError("元数据不完整")
        if action == "download":
            absolute_path = get_safe_path_for_tcp(share_name, file_path)
            if not os.path.isfile(absolute_path): raise FileNotFoundError("File not found on server")
            file_size = os.path.getsize(absolute_path)
            client_socket.sendall(json.dumps({"status": "ok", "size": file_size}).encode('utf-8'))
            client_socket.recv(1024)
            with open(absolute_path, 'rb') as f:
                # 【性能优化】调整TCP缓冲区大小
                while chunk := f.read(64 * 1024): # 64KB chunk
                    client_socket.sendall(chunk)
        else: raise ValueError(f"未知的动作: {action}")
    except Exception as e:
        try: client_socket.sendall(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except socket.error: pass
        print(f"处理TCP客户端连接时发生错误: {e}")
    finally:
        client_socket.close()

def run_tcp_server(port: int, stop_event):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.settimeout(1.0)
    try:
        server_socket.bind(('', port))
        server_socket.listen(5)
        print(f"TCP高速传输服务器已在端口 {port} 启动...")
    except OSError as e:
        print(f"错误: 无法启动TCP服务器在端口 {port}: {e}")
        return

    while not stop_event.is_set():
        try:
            client_sock, address = server_socket.accept()
            print(f"接受到来自 {address} 的TCP连接")
            thread = threading.Thread(target=handle_client_connection, args=(client_sock,), daemon=True)
            thread.start()
        except socket.timeout:
            continue
    server_socket.close()
    print("TCP服务器已关闭。")