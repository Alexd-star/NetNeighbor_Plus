# 文件: core/tcp_server.py (最终修正版)
import socket
import threading
import json
import os
from typing import Tuple  # <--- 【修复】添加这行导入语句
from .config_loader import load_config


def get_safe_path_for_tcp(share_name: str, sub_path: str = "/") -> Tuple[str, dict]:
    # TCP服务也应该强制重新加载配置以获取最新权限
    all_shares = load_config(force_reload=True).get('shares', [])
    target_share = next((s for s in all_shares if s["name"] == share_name), None)
    if not target_share:
        raise FileNotFoundError(f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)
    if not os.path.abspath(full_path).startswith(base_path):
        raise PermissionError("Access denied")

    return full_path, target_share


def handle_client_connection(client_socket):
    try:
        header_data = client_socket.recv(1024).decode('utf-8')
        if not header_data: return

        header = json.loads(header_data)
        action = header.get("action")
        share_name = header.get("share_name")
        file_path = header.get("file_path")

        if not all([action, share_name, file_path]):
            raise ValueError("Incomplete metadata received.")

        if action == "download":
            absolute_path, target_share = get_safe_path_for_tcp(share_name, file_path)

            # --- 核心权限检查 ---
            if "download" not in target_share.get("permissions", []):
                raise PermissionError("Download permission denied for this share via TCP.")

            if not os.path.isfile(absolute_path):
                raise FileNotFoundError("File not found on server for TCP transfer.")

            file_size = os.path.getsize(absolute_path)
            client_socket.sendall(json.dumps({"status": "ok", "size": file_size}).encode('utf-8'))
            client_socket.recv(1024)  # Wait for client's 'ready' signal

            with open(absolute_path, 'rb') as f:
                while chunk := f.read(65536):  # Use 64KB chunks
                    client_socket.sendall(chunk)
        else:
            raise ValueError(f"Unknown action: {action}")

    except Exception as e:
        try:
            error_msg = json.dumps({"status": "error", "message": str(e)})
            client_socket.sendall(error_msg.encode('utf-8'))
        except socket.error:
            pass  # Client might have already disconnected
        print(f"Error during TCP client handling: {e}")
    finally:
        client_socket.close()


def run_tcp_server(port: int, stop_event):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.settimeout(1.0)
    try:
        server_socket.bind(('', port))
        server_socket.listen(5)
        print(f"TCP high-speed transfer server started on port {port}...")
    except OSError as e:
        print(f"Error: Could not start TCP server on port {port}: {e}")
        return

    while not stop_event.is_set():
        try:
            client_sock, address = server_socket.accept()
            print(f"Accepted TCP connection from {address}")
            thread = threading.Thread(target=handle_client_connection, args=(client_sock,), daemon=True)
            thread.start()
        except socket.timeout:
            continue

    server_socket.close()
    print("TCP server has been shut down.")