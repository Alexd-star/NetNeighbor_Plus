"""
TCP服务器，提供高速文件传输服务
"""

import asyncio
import json
import os
import sys
import time
from typing import Tuple

from .path_utils import get_safe_path_and_share
from gui.api_client import TarUploader


def log_server(message, is_error=False):
    """服务器端的日志函数，可区分普通日志和错误日志。"""
    timestamp = time.strftime("%H:%M:%S")
    log_stream = sys.stderr if is_error else sys.stdout
    print(f"[{timestamp}] [TCP_SERVER] {message}", file=log_stream)


async def handle_client_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    """
    处理TCP客户端连接。
    现在直接使用 TarUploader 在线程中打包，并将数据流异步写入客户端。
    """
    client_address = writer.get_extra_info("peername")
    log_server(f"已接受来自 {client_address} 的TCP连接")

    try:
        header_data = await asyncio.wait_for(reader.read(1024), timeout=10.0)
        if not header_data:
            return

        header = json.loads(header_data.decode("utf-8"))
        action = header.get("action")

        if action == "download_folder":
            share_name = header.get("share_name")
            remote_path = header.get("remote_path")

            absolute_path, _ = get_safe_path_and_share(
                share_name, remote_path, require_permission="download"
            )

            if not os.path.isdir(absolute_path):
                raise FileNotFoundError(
                    f"文件夹 '{absolute_path}' 未找到或不是一个目录。"
                )

            writer.write(json.dumps({"status": "ok"}).encode("utf-8"))
            await writer.drain()

            await asyncio.wait_for(reader.read(1024), timeout=10.0)

            log_server(f"开始为 {client_address} 流式传输文件夹: {absolute_path}")

            streamer = TarUploader(absolute_path)

            try:
                while True:
                    chunk = await asyncio.to_thread(streamer.read)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
            finally:
                streamer.close()

            log_server(f"文件夹 {absolute_path} 已成功流式传输到 {client_address}")

    except Exception as e:
        error_msg = (
            f"处理TCP客户端 {client_address} 时发生错误: {type(e).__name__}: {e}"
        )
        log_server(error_msg, is_error=True)
        try:
            if not writer.is_closing():
                error_response = json.dumps({"status": "error", "message": str(e)})
                writer.write(error_response.encode("utf-8"))
                await writer.drain()
        except Exception as write_err:
            log_server(f"向客户端发送错误通知时失败: {write_err}", is_error=True)
    finally:
        if writer and not writer.is_closing():
            try:
                if writer.can_write_eof():
                    writer.write_eof()
                await writer.drain()
            except ConnectionError:
                pass
            finally:
                writer.close()
                await writer.wait_closed()
        log_server(f"与 {client_address} 的连接已确认完全关闭。")


async def run_tcp_server(port: int, stop_event: asyncio.Event):
    """启动并管理TCP服务器的生命周期。"""
    try:
        server = await asyncio.start_server(handle_client_connection, "0.0.0.0", port)
        addr = server.sockets[0].getsockname()
        log_server(f"异步TCP高速传输服务已在 {addr} 上启动...")

        async with server:
            stop_waiter = asyncio.create_task(stop_event.wait())
            serve_task = asyncio.create_task(server.serve_forever())
            done, pending = await asyncio.wait(
                {stop_waiter, serve_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        log_server("异步TCP服务已优雅关闭。")
    except Exception as e:
        log_server(f"TCP服务器启动或运行失败: {e}", is_error=True)
