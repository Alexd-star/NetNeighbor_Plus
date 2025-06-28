# 文件: core/web_api.py
import os
import json
import asyncio
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse
from typing import List
from .config_loader import get_shares
from .discovery import online_devices


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept(); self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # 创建一个当前连接的副本进行迭代，防止在迭代时列表被修改
        connections = list(self.active_connections)
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                # 如果发送失败（例如连接已意外断开），则将其从主列表中安全地移除
                self.disconnect(connection)


manager = ConnectionManager()
app = FastAPI()


@app.get("/api/v1/ping")
async def ping():
    return JSONResponse(content={"message": "pong"})


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 等待客户端消息，如果不需要处理可以留空，或者增加一个心跳机制
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/v1/internal/notify_shares_changed")
async def notify_shares_changed(request: Request):
    """
    一个内部端点，由客户端在更改设置后调用自己，
    以触发向所有其他连接到此设备的对等方广播“共享列表已更新”的事件。
    """
    try:
        # 从应用状态中获取controller实例
        controller = request.app.state.controller
        device_name = controller.device_name
        service_name = controller.service_name

        # 向所有连接到本机的客户端广播事件
        await manager.broadcast(json.dumps({
            "event": "shares_updated",
            "device_name": device_name,
            "service_name": service_name
        }))
        return {"status": "ok", "message": "Broadcast for share update sent."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send broadcast: {e}")


def get_safe_path(share_name: str, sub_path: str = "/") -> str:
    target_share = next((s for s in get_shares() if s["name"] == share_name), None)
    if not target_share:
        raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])

    if sub_path is None or sub_path.strip() in ['/', '']:
        return base_path

    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))

    if safe_sub_path.startswith('..') or safe_sub_path == '.':
        return base_path

    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(status_code=403, detail="Access denied: Path traversal attempt detected.")

    return full_path


@app.get("/api/v1/peers")
def get_peers():
    return JSONResponse(content=online_devices)


@app.get("/api/v1/shares")
def list_shares():
    share_list = [{"name": s.get("name"), "permissions": s.get("permissions", ["read"])} for s in get_shares()]
    return JSONResponse(content=share_list)


@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    request_path = get_safe_path(share_name, path)

    if not os.path.isdir(request_path):
        raise HTTPException(status_code=404, detail=f"Directory not found: {request_path}")

    try:
        file_list = []
        for item in os.listdir(request_path):
            try:
                item_path = os.path.join(request_path, item)
                is_dir = os.path.isdir(item_path)
                size = 0
                if not is_dir:
                    try:
                        size = os.path.getsize(item_path)
                    except OSError:
                        pass
                file_list.append({"name": item, "is_dir": is_dir, "size": size})
            except (FileNotFoundError, PermissionError):
                continue
        return JSONResponse(content=file_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files at '{path}': {str(e)}")


@app.get("/api/v1/download/{share_name}")
def download_file(share_name: str, file_path: str):
    absolute_path = get_safe_path(share_name, file_path)
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(absolute_path, filename=os.path.basename(absolute_path))


@app.post("/api/v1/upload/{share_name}")
async def upload_file(share_name: str, dest_path: str = "/", file: UploadFile = File(...)):
    target_share = next((s for s in get_shares() if s["name"] == share_name), None)
    if not target_share or "write" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Write permission denied for this share.")

    upload_dir = get_safe_path(share_name, dest_path)
    if not os.path.isdir(upload_dir):
        raise HTTPException(status_code=400, detail="Destination path is not a valid directory.")

    file_destination = os.path.join(upload_dir, file.filename)
    if not os.path.abspath(file_destination).startswith(os.path.abspath(upload_dir)):
        raise HTTPException(status_code=403, detail="Access denied: Invalid destination filename.")

    try:
        with open(file_destination, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    return {"message": f"File '{file.filename}' uploaded successfully to '{share_name}'."}