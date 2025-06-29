# 文件: core/web_api.py
# 描述: 提供 FastAPI 应用实例和所有 HTTP API 端点。
# (已使用最兼容的 API 调用方式, 彻底解决 zipstream-ng 的版本问题)

import asyncio
import json
import os
import urllib.parse
from typing import Any, Dict, List, Tuple, Generator

from fastapi import (
    FastAPI, File, HTTPException, Request, UploadFile,
    WebSocket, WebSocketDisconnect
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from zipstream import ZIP_STORED, ZipStream

from .config_loader import load_config
from .discovery import online_devices
from .tcp_server import run_tcp_server

__all__ = [
    "app",
    "manager",
]


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接。"""

    def __init__(self):
        """初始化 ConnectionManager。"""
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """接受一个新的 WebSocket 连接并将其加入活跃列表。"""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """从活跃列表中移除一个已断开的 WebSocket 连接。"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        """向所有活跃的连接广播一条消息。"""
        connections = list(self.active_connections)
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()
app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """在 FastAPI 应用启动时, 自动运行后台服务。"""
    loop = asyncio.get_running_loop()
    tcp_stop_event = asyncio.Event()

    app.state.tcp_stop_event = tcp_stop_event
    app.state.asyncio_loop = loop

    tcp_port = app.state.tcp_port
    loop.create_task(run_tcp_server(tcp_port, tcp_stop_event))
    print("Async TCP server task has been scheduled on the running event loop.")


def get_safe_path_and_share(
        share_name: str, sub_path: str = "/"
) -> Tuple[str, Dict[str, Any]]:
    """安全地解析请求的路径, 防止路径遍历。"""
    all_shares = load_config(force_reload=True).get('shares', [])
    target_share = next(
        (s for s in all_shares if s.get("name") == share_name), None
    )

    if not target_share:
        raise HTTPException(
            status_code=404,
            detail=f"Share '{share_name}' not found"
        )

    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Path traversal attempt detected."
        )

    return full_path, target_share


# --- 【终极核心修正】使用最基础、最兼容的API调用方式 ---
def iter_folder_as_zip(folder_path: str) -> Generator[bytes, None, None]:
    """
    一个极其健壮的生成器函数, 使用最兼容的 API 来流式生成ZIP数据。
    """
    # 1. 创建一个空的 ZipStream, 明确指定压缩类型
    streamer = ZipStream(compress_type=ZIP_STORED)

    print(f"开始扫描并流式传输文件夹: {folder_path}")

    # 2. 遍历所有可读文件
    for root, _, files in os.walk(folder_path):
        for file in files:
            try:
                disk_path = os.path.join(root, file)
                if not os.access(disk_path, os.R_OK):
                    print(f"警告: 文件不可读, 已跳过: {disk_path}")
                    continue

                archive_path = os.path.relpath(disk_path, folder_path)

                # 3. 使用 .add() 方法将文件加入流中。
                # 这个方法本身不产出数据。
                streamer.add(disk_path, arcname=archive_path)

            except Exception as e:
                print(f"警告: 处理文件 '{file}' 时出错, 已跳过. 错误: {e}")
                continue

    # 4. 在所有文件都添加完毕后, 迭代 streamer 对象本身。
    # 这个迭代过程会按顺序产出所有文件的数据块和最后的中央目录。
    for chunk in streamer:
        yield chunk

    print("流式打包完成。")


@app.get("/api/v1/download_folder/{share_name}")
def download_folder(share_name: str, folder_path: str):
    """
    以最稳定的方式流式下载文件夹 (支持进度条并能智能降级)。
    """
    absolute_path, target_share = get_safe_path_and_share(share_name, folder_path)

    if "download" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Download permission denied.")
    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=404, detail="Folder not found.")

    # --- 1. “无害”的预计算过程 ---
    total_size = None
    try:
        # 创建一个临时的、仅用于计算的实例
        size_calculator_stream = ZipStream(compress_type=ZIP_STORED)

        # 模拟添加文件以计算大小
        for root, _, files in os.walk(absolute_path):
            for file in files:
                disk_path = os.path.join(root, file)
                archive_path = os.path.relpath(disk_path, absolute_path)
                size_calculator_stream.add(disk_path, arcname=archive_path)

        # 获取计算出的总大小
        total_size = size_calculator_stream.size
        print(f"预计算大小成功: {total_size} bytes")

    except Exception as e:
        # 如果计算过程中任何一个文件出问题，则放弃计算，并降级
        print(f"警告: 无法预计算文件夹大小，将降级为不确定进度条。原因: {e}")
        total_size = None

    # --- 预计算过程结束 ---

    # 2. 定义一个与您原始代码逻辑完全一致的、绝对可靠的生成器
    def robust_zip_generator():
        # 在生成器内部创建全新的实例，与计算过程完全隔离
        streamer = ZipStream(compress_type=ZIP_STORED)

        for root, _, files in os.walk(absolute_path):
            for file in files:
                try:
                    disk_path = os.path.join(root, file)
                    archive_path = os.path.relpath(disk_path, absolute_path)
                    streamer.add(disk_path, arcname=archive_path)
                except Exception as file_error:
                    # 在流式传输时，如果遇到错误，只跳过单个文件，不影响整体
                    print(f"警告: 流式传输时跳过文件 '{disk_path}'，原因: {file_error}")
                    continue

        # 迭代这个全新的实例，产出数据
        for chunk in streamer:
            yield chunk

    # 3. 构建安全的响应头
    folder_name = os.path.basename(os.path.normpath(absolute_path))

    encoded_filename = urllib.parse.quote(folder_name, safe='')
    ascii_fallback_filename = folder_name.encode('ascii', 'ignore').decode('ascii')
    if not ascii_fallback_filename:
        ascii_fallback_filename = "download"

    content_disposition = (
        f"attachment; filename=\"{ascii_fallback_filename}.zip\"; "
        f"filename*=UTF-8''{encoded_filename}.zip"
    )

    response_headers = {'Content-Disposition': content_disposition}
    if total_size is not None:
        response_headers['Content-Length'] = str(total_size)

    # 4. 返回最终的流式响应
    return StreamingResponse(
        content=robust_zip_generator(),
        media_type="application/zip",
        headers=response_headers
    )

# --- 所有其他API端点保持不变 ---
@app.get("/api/v1/ping")
async def ping():
    return JSONResponse(content={"message": "pong"})


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/v1/internal/notify_shares_changed")
async def notify_shares_changed(request: Request):
    try:
        controller = request.app.state.controller
        event_data = {
            "event": "shares_updated",
            "device_name": controller.device_name,
        }
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok", "message": "Broadcast for share update sent."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to broadcast: {e}")


@app.get("/api/v1/peers")
def get_peers():
    return JSONResponse(content=online_devices)


@app.get("/api/v1/shares")
def list_shares():
    shares = load_config(force_reload=True).get('shares', [])
    share_list = [
        {"name": s.get("name"), "permissions": s.get("permissions", [])}
        for s in shares
    ]
    return JSONResponse(content=share_list)


@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    request_path, target_share = get_safe_path_and_share(share_name, path)
    if "read" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403, detail="Read permission denied for this share."
        )
    if not os.path.isdir(request_path):
        raise HTTPException(status_code=404, detail="Directory not found")
    try:
        file_list = []
        for item_name in os.listdir(request_path):
            try:
                item_path = os.path.join(request_path, item_name)
                is_dir = os.path.isdir(item_path)
                size = os.path.getsize(item_path) if not is_dir else 0
                file_list.append(
                    {"name": item_name, "is_dir": is_dir, "size": size}
                )
            except (OSError, PermissionError):
                continue
        return JSONResponse(content=file_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {e}")


@app.get("/api/v1/download/{share_name}")
async def download_file(share_name: str, file_path: str):
    absolute_path, target_share = get_safe_path_and_share(share_name,
                                                          file_path)
    if "download" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Download permission denied for this share."
        )
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        absolute_path, filename=os.path.basename(absolute_path)
    )


@app.post("/api/v1/upload/{share_name}")
async def upload_file(
        share_name: str, dest_path: str = "/", file: UploadFile = File(...)
):
    upload_dir, target_share = get_safe_path_and_share(share_name, dest_path)
    if "upload" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403, detail="Upload permission denied for this share."
        )
    if not os.path.isdir(upload_dir):
        raise HTTPException(
            status_code=400,
            detail="Destination path is not a valid directory."
        )
    file_destination = os.path.join(upload_dir, file.filename)
    if not os.path.abspath(file_destination).startswith(
            os.path.abspath(upload_dir)):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Invalid destination filename."
        )
    try:
        with open(file_destination, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Could not save file: {e}"
        )
    return {"message": f"File '{file.filename}' uploaded successfully."}


@app.post("/api/v1/create_dir/{share_name}")
async def create_directory(share_name: str, path: str):
    dir_path, target_share = get_safe_path_and_share(share_name, path)
    if "upload" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Upload permission denied (cannot create directory)."
        )
    try:
        os.makedirs(dir_path, exist_ok=True)
        return {"message": f"Directory '{path}' created or already exists."}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Could not create directory: {e}"
        )