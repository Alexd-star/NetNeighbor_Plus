# 文件: core/tcp_server.py (已重构为异步模型)
import asyncio
import json
import os
import socket
from typing import Tuple
from .config_loader import load_config

# get_safe_path_for_tcp 函数保持不变，它已经做得很好
def get_safe_path_for_tcp(share_name: str, sub_path: str = "/") -> Tuple[str, dict]:
    all_shares = load_config(force_reload=True).get('shares', [])
    target_share = next((s for s in all_shares if s["name"] == share_name), None)
    if not target_share:
        raise FileNotFoundError(f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)
    if not os.path.abspath(full_path).startswith(base_path):
        raise PermissionError("Access denied: Path traversal attempt detected.")

    return full_path, target_share


async def handle_client_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """
    异步处理单个TCP客户端连接。
    使用 asyncio 的 StreamReader 和 StreamWriter，性能极高。
    """
    client_address = writer.get_extra_info('peername')
    print(f"Accepted async TCP connection from {client_address}")

    try:
        # 异步读取数据，设置超时防止连接卡死
        header_data = await asyncio.wait_for(reader.read(1024), timeout=10.0)
        if not header_data:
            return

        header = json.loads(header_data.decode('utf-8'))
        action = header.get("action")
        share_name = header.get("share_name")
        file_path = header.get("file_path")

        if not all([action, share_name, file_path]):
            raise ValueError("Incomplete metadata received.")

        if action == "download":
            absolute_path, target_share = get_safe_path_for_tcp(share_name, file_path)

            if "download" not in target_share.get("permissions", []):
                raise PermissionError("Download permission denied for this share via TCP.")

            if not os.path.isfile(absolute_path):
                raise FileNotFoundError("File not found on server for TCP transfer.")

            file_size = os.path.getsize(absolute_path)
            # 异步发送响应头
            response_header = json.dumps({"status": "ok", "size": file_size}).encode('utf-8')
            writer.write(response_header)
            await writer.drain()

            # 等待客户端的“准备就绪”信号
            await asyncio.wait_for(reader.read(1024), timeout=10.0)

            # 异步发送文件内容
            with open(absolute_path, 'rb') as f:
                while chunk := f.read(65536):  # 64KB 块大小
                    writer.write(chunk)
                    await writer.drain()  # 等待缓冲区清空，防止内存爆炸

        else:
            raise ValueError(f"Unknown action: {action}")

    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError) as e:
        print(f"TCP connection error with {client_address}: {e}")
    except Exception as e:
        print(f"Error during TCP client handling with {client_address}: {e}")
        try:
            # 异步发送错误信息
            error_msg = json.dumps({"status": "error", "message": str(e)}).encode('utf-8')
            writer.write(error_msg)
            await writer.drain()
        except Exception as e_send:
            print(f"Failed to send error message to {client_address}: {e_send}")
    finally:
        print(f"Closing TCP connection with {client_address}")
        writer.close()
        await writer.wait_closed()


async def run_tcp_server(port: int, stop_event: asyncio.Event):
    """
    启动并管理异步TCP服务器。
    """
    server = await asyncio.start_server(handle_client_connection, '0.0.0.0', port)

    addr = server.sockets[0].getsockname()
    print(f'Async TCP high-speed transfer server started on {addr}...')

    # 运行服务器直到 stop_event 被设置
    async with server:
        # 创建一个等待 stop_event 的任务
        stop_waiter = asyncio.create_task(stop_event.wait())
        # 创建一个服务永久运行的任务
        serve_task = asyncio.create_task(server.serve_forever())

        # 等待任意一个任务完成 (要么是服务出错，要么是收到了停止信号)
        done, pending = await asyncio.wait(
            {stop_waiter, serve_task},
            return_when=asyncio.FIRST_COMPLETED
        )

        # 取消所有还没完成的挂起任务
        for task in pending:
            task.cancel()

        # 等待所有任务确实被取消
        await asyncio.gather(*pending, return_exceptions=True)

    print("Async TCP server has been shut down.")