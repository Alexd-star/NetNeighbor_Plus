# 文件: core/web_api.py (最终修复版)
import os
import json
import asyncio
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Tuple
from .config_loader import get_shares, load_config
from .discovery import online_devices


class ConnectionManager:
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


# --- 辅助函数：安全获取路径并返回共享配置 ---
def get_safe_path_and_share(share_name: str, sub_path: str = "/") -> Tuple[str, dict]:
    # 确保我们总能拿到最新的配置
    all_shares = load_config(force_reload=True).get('shares', [])
    target_share = next((s for s in all_shares if s["name"] == share_name), None)

    if not target_share:
        raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])

    if sub_path is None or sub_path.strip() in ['/', '']:
        full_path = base_path
    else:
        safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
        if safe_sub_path.startswith('..') or safe_sub_path == '.':
            full_path = base_path
        else:
            full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(status_code=403, detail="Access denied: Path traversal attempt detected.")

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
        await manager.broadcast(json.dumps({
            "event": "shares_updated",
            "device_name": controller.device_name
        }))
        return {"status": "ok", "message": "Broadcast sent."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/peers")
def get_peers():
    return JSONResponse(content=online_devices)


@app.get("/api/v1/shares")
def list_shares():
    # 始终从文件重新加载，以确保数据最新
    shares = load_config(force_reload=True).get('shares', [])
    share_list = [{"name": s.get("name"), "permissions": s.get("permissions", [])} for s in shares]
    return JSONResponse(content=share_list)


# --- 【核心修复】唯一、完整且正确的 list_files 函数 ---
@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    request_path, target_share = get_safe_path_and_share(share_name, path)

    if "read" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Read permission denied for this share.")

    if not os.path.isdir(request_path):
        raise HTTPException(status_code=404, detail="Directory not found")

    try:
        file_list = []
        for item in os.listdir(request_path):
            try:
                item_path = os.path.join(request_path, item)
                is_dir = os.path.isdir(item_path)
                size = os.path.getsize(item_path) if not is_dir else 0
                file_list.append({"name": item, "is_dir": is_dir, "size": size})
            except (OSError, PermissionError):
                continue
        return JSONResponse(content=file_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {e}")


@app.get("/api/v1/download/{share_name}")
async def download_file(share_name: str, file_path: str):
    absolute_path, target_share = get_safe_path_and_share(share_name, file_path)

    if "download" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Download permission denied for this share.")

    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(absolute_path, filename=os.path.basename(absolute_path))


@app.post("/api/v1/upload/{share_name}")
async def upload_file(share_name: str, dest_path: str = "/", file: UploadFile = File(...)):
    upload_dir, target_share = get_safe_path_and_share(share_name, dest_path)

    if "upload" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Upload permission denied for this share.")

    if not os.path.isdir(upload_dir):
        raise HTTPException(status_code=400, detail="Destination is not a valid directory.")

    file_destination = os.path.join(upload_dir, file.filename)
    if not os.path.abspath(file_destination).startswith(os.path.abspath(upload_dir)):
        raise HTTPException(status_code=403, detail="Invalid destination path.")

    try:
        with open(file_destination, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    return {"message": f"File '{file.filename}' uploaded successfully."}