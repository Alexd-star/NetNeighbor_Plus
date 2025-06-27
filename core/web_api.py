# 文件: core/web_api.py (修复)
import os
import asyncio
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from typing import List
from .config_loader import get_shares
from .discovery import online_devices


class ConnectionManager:
    def __init__(self): self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket): await websocket.accept(); self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket): self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections: await connection.send_text(message)


manager = ConnectionManager()
app = FastAPI()


@app.get("/api/v1/ping")
async def ping():
    return JSONResponse(content={"message": "pong"})


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def get_safe_path(share_name: str, sub_path: str = "/") -> str:
    target_share = next((s for s in get_shares() if s["name"] == share_name), None)
    if not target_share:
        raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])

    # 【修复2】对子路径处理进行加固
    if sub_path is None or sub_path.strip() in ['/', '']:
        # 如果是请求根目录，直接返回基础路径
        return base_path

    # 对于非根目录的请求，进行规范化和安全检查
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))

    # 再次检查，防止 '..' 或 '.' 等特殊情况
    if safe_sub_path.startswith('..') or safe_sub_path == '.':
        # 如果清理后路径变为无效或有问题的，视为请求根目录
        return base_path

    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(status_code=403, detail="Access denied: Path traversal attempt detected.")

    return full_path


@app.get("/api/v1/peers")
def get_peers(): return JSONResponse(content=online_devices)


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