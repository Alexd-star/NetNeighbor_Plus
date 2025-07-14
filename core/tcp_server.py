import asyncio
import json
import os
import sys
import time
from typing import Tuple

from .config_loader import load_config


def log_server(message, is_error=False):
    """服务器端的日志函数，可区分普通日志和错误日志。"""
    timestamp = time.strftime("%H:%M:%S")
    log_stream = sys.stderr if is_error else sys.stdout
    print(f"[{timestamp}] [TCP_SERVER] {message}", file=log_stream)


def get_safe_path_for_tcp(share_name: str, sub_path: str = "/") -> Tuple[str, dict]:
    """安全地解析共享路径，防止路径遍历攻击。"""
    all_shares = load_config(force_reload=True).get("shares", [])
    target_share = next((s for s in all_shares if s["name"] == share_name), None)
    if not target_share:
        raise FileNotFoundError(f"Share '{share_name}' not found")

    # 检查下载权限
    if "download" not in target_share.get("permissions", ["read"]):
        raise PermissionError(f"Download permission denied for share '{share_name}'")

    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip("/\\"))
    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise PermissionError("Access denied: Path traversal attempt detected.")

    return full_path, target_share


async def _drain_stream(
    proc_stream: asyncio.StreamReader,
    stream_name: str,
    client_writer: asyncio.StreamWriter = None,
):
    """一个通用的协程，用于排干子进程的一个流（stdout 或 stderr）。"""
    while True:
        try:
            chunk = await proc_stream.read(65536)
            if not chunk:
                break
            if client_writer:
                client_writer.write(chunk)
                await client_writer.drain()
            else:
                # 将工作进程的错误日志以UTF-8解码后打印出来
                log_server(
                    f"[WORKER_STDERR] {chunk.decode('utf-8', errors='ignore').strip()}",
                    is_error=True,
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log_server(f"处理管道 '{stream_name}' 时发生异常: {e}", is_error=True)
            break


async def handle_client_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    """处理TCP客户端连接。使用严格的屏障来确保数据完整性，并调用TAR打包工作进程。"""
    client_address = writer.get_extra_info("peername")
    log_server(f"已接受来自 {client_address} 的TCP连接")

    proc = None
    try:
        header_data = await asyncio.wait_for(reader.read(1024), timeout=10.0)
        if not header_data:
            return

        header = json.loads(header_data.decode("utf-8"))
        action = header.get("action")

        if action == "download_folder":
            share_name = header.get("share_name")
            remote_path = header.get("remote_path")
            absolute_path, _ = get_safe_path_for_tcp(share_name, remote_path)

            if not os.path.isdir(absolute_path):
                raise FileNotFoundError(
                    f"Folder '{absolute_path}' not found or is not a directory."
                )

            # 响应客户端，表示准备就绪
            writer.write(json.dumps({"status": "ok"}).encode("utf-8"))
            await writer.drain()

            # 等待客户端确认可以开始发送数据
            await asyncio.wait_for(reader.read(1024), timeout=10.0)

            worker_script_path = os.path.join(
                os.path.dirname(__file__), "tar_worker.py"
            )
            if not os.path.exists(worker_script_path):
                raise FileNotFoundError(
                    f"Worker script '{worker_script_path}' not found!"
                )

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                worker_script_path,
                absolute_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            log_server(
                f"已启动 TAR 打包子进程 [PID: {proc.pid}] for folder '{absolute_path}'"
            )

            # 并发地排干stdout和stderr管道
            stdout_task = asyncio.create_task(
                _drain_stream(proc.stdout, "stdout", writer)
            )
            stderr_task = asyncio.create_task(_drain_stream(proc.stderr, "stderr"))

            # 等待子进程结束，并收集其退出码
            return_code = await proc.wait()
            log_server(f"子进程 [PID: {proc.pid}] 已退出，返回码: {return_code}")

            # 等待管道数据完全排干
            await stdout_task
            await stderr_task
            log_server("stdout 和 stderr 管道已完全排干。")

            if return_code != 0:
                raise RuntimeError(f"TAR 打包子进程 [PID: {proc.pid}] 执行失败。")

    except Exception as e:
        error_msg = (
            f"处理TCP客户端 {client_address} 时发生错误: {type(e).__name__}: {e}"
        )
        log_server(error_msg, is_error=True)
        try:
            # 尝试向客户端发送错误信息
            if not writer.is_closing():
                error_response = json.dumps({"status": "error", "message": str(e)})
                writer.write(error_response.encode("utf-8"))
                await writer.drain()
        except Exception as write_err:
            log_server(f"向客户端发送错误通知时失败: {write_err}", is_error=True)
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
            log_server(f"强制终止了子进程 [PID: {proc.pid}]", is_error=True)

        if writer and not writer.is_closing():
            try:
                # 确保在关闭前所有数据都已发送
                if writer.can_write_eof():
                    writer.write_eof()
                await writer.drain()
            except ConnectionError:
                pass  # 忽略在关闭时可能发生的连接错误
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
            # 等待停止信号或服务器自身任务结束
            done, pending = await asyncio.wait(
                {stop_waiter, serve_task}, return_when=asyncio.FIRST_COMPLETED
            )
            # 取消所有仍在运行的挂起任务
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        log_server("异步TCP服务已优雅关闭。")
    except Exception as e:
        log_server(f"TCP服务器启动或运行失败: {e}", is_error=True)
