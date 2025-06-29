# 文件: core/web_api.py
# 描述: 提供 FastAPI 应用实例和所有 HTTP API 端点。
# (已按 PEP 8 规范格式化, 并修复跨线程事件循环问题)

import asyncio
import io
import json
import os
import tempfile
import zipfile
from typing import Any, Dict, List, Tuple

from fastapi import (
    BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile,
    WebSocket, WebSocketDisconnect
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

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
    """
    在 FastAPI 应用启动时, 自动运行后台服务。
    """
    # --- 【核心修正】在这里创建属于当前事件循环的 Event ---
    loop = asyncio.get_running_loop()
    tcp_stop_event = asyncio.Event()

    # 将新创建的 event 和 loop 存入 app.state, 供 AppController 使用
    app.state.tcp_stop_event = tcp_stop_event
    app.state.asyncio_loop = loop

    # 从 AppController 之前存入的 app.state 中获取 tcp_port
    tcp_port = app.state.tcp_port

    # 在当前事件循环中创建并运行TCP服务器任务
    loop.create_task(run_tcp_server(tcp_port, tcp_stop_event))
    print("Async TCP server task has been scheduled on the running event loop.")


def get_safe_path_and_share(
    share_name: str, sub_path: str = "/"
) -> Tuple[str, Dict[str, Any]]:
    """
    安全地解析请求的路径, 防止路径遍历。
    """
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

# (为了简洁，这里省略了所有API端点，您无需改动它们, 它们和上一版完全一样)
@app.get("/api/v1/ping")
async def ping():
    """一个简单的健康检查端点。"""
    return JSONResponse(content={"message": "pong"})


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    """处理事件通知的 WebSocket 端点。"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"WebSocket client {websocket.client} disconnected.")


@app.post("/api/v1/internal/notify_shares_changed")
async def notify_shares_changed(request: Request):
    """(内部API) 当本机共享变化时, 通知所有WebSocket客户端。"""
    try:
        controller = request.app.state.controller
        event_data = {
            "event": "shares_updated",
            "device_name": controller.device_name,
        }
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok", "message": "Broadcast for share update sent."}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to broadcast: {e}"
        )


@app.get("/api/v1/peers")
def get_peers():
    """获取当前发现的所有在线设备列表。"""
    return JSONResponse(content=online_devices)


@app.get("/api/v1/shares")
def list_shares():
    """列出本机所有配置的共享文件夹及其权限。"""
    shares = load_config(force_reload=True).get('shares', [])
    share_list = [
        {"name": s.get("name"), "permissions": s.get("permissions", [])}
        for s in shares
    ]
    return JSONResponse(content=share_list)


@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    """列出指定共享文件夹内指定路径下的文件和目录。"""
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
        raise HTTPException(
            status_code=500, detail=f"Failed to list files: {e}"
        )


@app.get("/api/v1/download/{share_name}")
async def download_file(share_name: str, file_path: str):
    """下载单个文件。"""
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


@app.get("/api/v1/download_folder/{share_name}")
async def download_folder(
    share_name: str,
    folder_path: str,
    background_tasks: BackgroundTasks
):
    """将文件夹打包成ZIP并提供下载。"""
    absolute_path, target_share = get_safe_path_and_share(share_name,
                                                          folder_path)

    if "download" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Download permission denied for this share."
        )

    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=404, detail="Folder not found.")

    folder_name = os.path.basename(os.path.normpath(absolute_path))
    temp_zip_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            temp_zip_path = tmp.name

        with zipfile.ZipFile(temp_zip_path, 'w',
                             compression=zipfile.ZIP_STORED) as zf:
            for root, _, files in os.walk(absolute_path):
                for file in files:
                    file_path_on_disk = os.path.join(root, file)
                    archive_name = os.path.relpath(file_path_on_disk,
                                                   absolute_path)
                    zf.write(file_path_on_disk, archive_name)

        background_tasks.add_task(os.unlink, temp_zip_path)

        return FileResponse(
            path=temp_zip_path,
            media_type="application/zip",
            filename=f"{folder_name}.zip"
        )
    except Exception as e:
        if temp_zip_path and os.path.exists(temp_zip_path):
            os.unlink(temp_zip_path)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create folder archive: {e}"
        )


@app.post("/api/v1/upload/{share_name}")
async def upload_file(
    share_name: str, dest_path: str = "/", file: UploadFile = File(...)
):
    """上传单个文件到指定的共享目录。"""
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
    """在指定的共享文件夹中创建新的子目录。"""
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