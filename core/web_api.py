# 文件: core/web_api.py (最终版)
# 描述: 提供 FastAPI 应用实例和所有 HTTP API 端点。

import asyncio
import io
import json
import os
import zipfile
import tempfile # 用于创建临时文件
from fastapi import BackgroundTasks # 用于在下载后删除临时文件
from typing import Any, Dict, List, Tuple

from fastapi import (FastAPI, File, HTTPException, Request, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config_loader import load_config
from .discovery import online_devices


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接。"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        connections = list(self.active_connections)
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()
app = FastAPI()


def get_safe_path_and_share(
        share_name: str, sub_path: str = "/"
) -> Tuple[str, Dict[str, Any]]:
    """
    安全地解析请求的路径，防止路径遍历，并返回路径和对应的共享配置。
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
    # 移除路径前缀的斜杠，然后进行规范化
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)

    # 再次检查最终路径是否在共享目录的基路径下
    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Path traversal attempt detected."
        )

    return full_path, target_share


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
            "device_name": controller.device_name
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
    absolute_path, target_share = get_safe_path_and_share(share_name, file_path)
    if "download" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403, detail="Download permission denied for this share."
        )
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        absolute_path, filename=os.path.basename(absolute_path)
    )


# 【新功能】下载文件夹为ZIP压缩包的API端点
# 【重大修正】重写文件夹下载逻辑，解决文件损坏和卡顿问题
@app.get("/api/v1/download_folder/{share_name}")
async def download_folder(
    share_name: str,
    folder_path: str,
    background_tasks: BackgroundTasks # 注入后台任务依赖
):
    """
    健壮的文件夹下载实现：
    1. 在服务器的临时目录中创建一个临时的ZIP文件。
    2. 使用 ZIP_STORED 模式，仅打包不压缩，速度极快。
    3. 使用 FileResponse 安全地将这个临时文件发送给客户端。
    4. 通过 BackgroundTasks 在文件发送完毕后自动删除服务器上的临时文件。
    """
    absolute_path, target_share = get_safe_path_and_share(share_name, folder_path)
    if "download" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403, detail="Download permission denied for this share."
        )
    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=404, detail="Folder not found.")

    folder_name = os.path.basename(os.path.normpath(absolute_path))

    try:
        # 创建一个带后缀的临时文件，方便识别
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            temp_zip_path = tmp.name

            # 使用 ZIP_STORED (仅打包) 模式，速度飞快
            with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_STORED) as zf:
                for root, _, files in os.walk(absolute_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, absolute_path)
                        zf.write(file_path, arcname)

        # 确保在发送响应后，后台任务会删除这个临时文件
        background_tasks.add_task(os.unlink, temp_zip_path)

        return FileResponse(
            path=temp_zip_path,
            media_type="application/zip",
            filename=f"{folder_name}.zip"
        )

    except Exception as e:
        # 如果打包过程出错，也需要清理可能已创建的临时文件
        if 'temp_zip_path' in locals() and os.path.exists(temp_zip_path):
            os.unlink(temp_zip_path)
        raise HTTPException(status_code=500, detail=f"Failed to create folder archive: {e}")

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
            status_code=400, detail="Destination path is not a valid directory."
        )

    file_destination = os.path.join(upload_dir, file.filename)
    # 再次进行安全检查，防止文件名包含 ".." 等导致路径穿越
    if not os.path.abspath(file_destination).startswith(os.path.abspath(upload_dir)):
        raise HTTPException(
            status_code=403, detail="Access denied: Invalid destination filename."
        )

    try:
        with open(file_destination, "wb") as buffer:
            # 以块的形式读取上传的文件内容，防止大文件撑爆内存
            while content := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")
    return {"message": f"File '{file.filename}' uploaded successfully."}


# 【新功能】在指定共享中创建新目录的API端点
@app.post("/api/v1/create_dir/{share_name}")
async def create_directory(share_name: str, path: str):
    """
    在指定的共享文件夹中，根据提供的相对路径创建新的目录。
    这是实现文件夹上传功能的基础。
    """
    # 同样使用get_safe_path_and_share来验证路径的合法性
    dir_path, target_share = get_safe_path_and_share(share_name, path)
    if "upload" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403, detail="Upload permission denied (cannot create directory)."
        )
    try:
        # exist_ok=True 表示如果目录已存在，则不会抛出错误
        os.makedirs(dir_path, exist_ok=True)
        return {"message": f"Directory '{path}' created or already exists."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not create directory: {e}")