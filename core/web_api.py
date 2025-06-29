# 文件: core/web_api.py
# 描述: 提供 FastAPI 应用实例和所有 HTTP API 端点。

import os
import json
import asyncio
from typing import List, Tuple, Dict, Any

from fastapi import (
    FastAPI, HTTPException, UploadFile, File, WebSocket,
    WebSocketDisconnect, Request
)
from fastapi.responses import JSONResponse, FileResponse

from .config_loader import load_config
from .discovery import online_devices


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接。"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """接受一个新的 WebSocket 连接并将其添加到活动列表中。"""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """从活动列表中移除一个已断开的 WebSocket 连接。"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        """向所有活跃的连接广播一条消息。"""
        # 创建连接列表的副本进行迭代，以防在广播期间列表被修改
        connections_to_broadcast = list(self.active_connections)
        for connection in connections_to_broadcast:
            try:
                await connection.send_text(message)
            except Exception:
                # 如果发送失败（例如连接已意外断开），安全地移除
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

    if sub_path is None or sub_path.strip() in ['/', '']:
        full_path = base_path
    else:
        # 清理并规范化子路径
        safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
        if safe_sub_path.startswith('..') or safe_sub_path == '.':
            full_path = base_path
        else:
            full_path = os.path.join(base_path, safe_sub_path)

    # 最终的安全检查，确保解析后的路径在共享根目录之内
    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Path traversal attempt detected."
        )

    return full_path, target_share


@app.get("/api/v1/ping")
async def ping():
    """一个简单的健康检查端点。"""
    return JSONResponse(content={"message": "pong"})


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    """处理 WebSocket 事件连接。"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # 保持连接活跃
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/v1/internal/notify_shares_changed")
async def notify_shares_changed(request: Request):
    """内部API，用于在配置更改后触发向所有对等方广播通知。"""
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
    """返回当前发现的所有在线设备列表。"""
    return JSONResponse(content=online_devices)


@app.get("/api/v1/shares")
def list_shares():
    """返回本机所有共享文件夹的列表及其权限。"""
    shares = load_config(force_reload=True).get('shares', [])
    share_list = [
        {"name": s.get("name"), "permissions": s.get("permissions", [])}
        for s in shares
    ]
    return JSONResponse(content=share_list)


@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    """列出指定共享文件夹下特定路径的文件和目录。"""
    request_path, target_share = get_safe_path_and_share(share_name, path)

    if "read" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Read permission denied for this share."
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
                file_list.append({"name": item_name, "is_dir": is_dir, "size": size})
            except (OSError, PermissionError):
                # 忽略无法访问的文件或目录
                continue
        return JSONResponse(content=file_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {e}")


@app.get("/api/v1/download/{share_name}")
async def download_file(share_name: str, file_path: str):
    """下载指定共享中的单个文件。"""
    absolute_path, target_share = get_safe_path_and_share(share_name, file_path)

    if "download" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Download permission denied for this share."
        )

    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(absolute_path, filename=os.path.basename(absolute_path))


@app.post("/api/v1/upload/{share_name}")
async def upload_file(
    share_name: str, dest_path: str = "/", file: UploadFile = File(...)
):
    """上传单个文件到指定的共享目录中。"""
    upload_dir, target_share = get_safe_path_and_share(share_name, dest_path)

    if "upload" not in target_share.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Upload permission denied for this share."
        )

    if not os.path.isdir(upload_dir):
        raise HTTPException(
            status_code=400,
            detail="Destination path is not a valid directory."
        )

    file_destination = os.path.join(upload_dir, file.filename)
    if not os.path.abspath(file_destination).startswith(os.path.abspath(upload_dir)):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Invalid destination filename."
        )

    try:
        with open(file_destination, "wb") as buffer:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    return {"message": f"File '{file.filename}' uploaded successfully."}