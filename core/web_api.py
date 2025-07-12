# 文件: core/web_api.py
# 描述: [最终修复版] 提供 FastAPI 应用实例，文件夹下载已完全替换为标准的 tarfile 实现。

import asyncio
import json
import os
import tarfile
import urllib.parse
import threading
from typing import Any, Dict, List, Tuple, Generator

from fastapi import (
    FastAPI, File, HTTPException, Request, UploadFile,
    WebSocket, WebSocketDisconnect
)
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from .config_loader import load_config
from .discovery import online_devices
from .tcp_server import run_tcp_server

__all__ = ["app", "manager"]


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


@app.on_event("startup")
async def startup_event():
    """在 FastAPI 应用启动时, 自动运行后台服务。"""
    loop = asyncio.get_running_loop()
    tcp_stop_event = asyncio.Event()
    app.state.tcp_stop_event = tcp_stop_event
    app.state.asyncio_loop = loop
    tcp_port = app.state.tcp_port
    loop.create_task(run_tcp_server(tcp_port, tcp_stop_event))


def get_safe_path_and_share(share_name: str, sub_path: str = "/") -> Tuple[str, Dict[str, Any]]:
    """安全地解析请求的路径, 防止路径遍历, 并返回共享配置。"""
    all_shares = load_config(force_reload=True).get('shares', [])
    target_share = next((s for s in all_shares if s.get("name") == share_name), None)

    if not target_share:
        raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(status_code=403, detail="Access denied: Path traversal attempt detected.")

    return full_path, target_share


def iter_folder_as_tar(folder_path: str) -> Generator[bytes, None, None]:
    """
    一个健壮的生成器函数, 使用标准库 `tarfile` 以非阻塞方式流式生成TAR数据。
    """
    read_fd, write_fd = os.pipe()

    def writer_thread():
        # 在一个独立的线程中进行写操作，防止阻塞FastAPI的事件循环
        try:
            with os.fdopen(write_fd, 'wb') as writer_pipe:
                # 【最终修复】同样在此处明确指定 format=tarfile.GNU_FORMAT
                with tarfile.open(
                    fileobj=writer_pipe,
                    mode='w|',
                    format=tarfile.GNU_FORMAT
                ) as tar:
                    tar.add(folder_path, arcname=os.path.basename(folder_path))
        finally:
            # 确保写端在完成后总是关闭，这会向读端发送EOF信号
            pass

    thread = threading.Thread(target=writer_thread)
    thread.start()

    # 在主线程中从管道的读端读取数据
    try:
        with os.fdopen(read_fd, 'rb') as reader_pipe:
            while True:
                chunk = reader_pipe.read(65536)  # 64KB
                if not chunk:
                    break
                yield chunk
    finally:
        thread.join()


@app.get("/api/v1/download_folder/{share_name}")
def download_folder(share_name: str, folder_path: str):
    """
    [最终修复] 以最健壮的 TAR 流式下载文件夹，彻底取代有问题的 zipstream 实现。
    """
    absolute_path, target_share = get_safe_path_and_share(share_name, folder_path)

    if "download" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Download permission denied.")
    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=404, detail="Folder not found.")

    folder_name = os.path.basename(os.path.normpath(absolute_path))
    encoded_filename = urllib.parse.quote(folder_name, safe='')
    ascii_fallback_filename = folder_name.encode('ascii', 'ignore').decode('ascii') or "download"

    content_disposition = (
        f"attachment; filename=\"{ascii_fallback_filename}.tar\"; "
        f"filename*=UTF-8''{encoded_filename}.tar"
    )
    headers = {'Content-Disposition': content_disposition}

    return StreamingResponse(
        iter_folder_as_tar(absolute_path),
        media_type="application/x-tar",
        headers=headers
    )


# --- 其余API端点保持不变 (为简洁省略) ---

@app.get("/api/v1/ping")
async def ping(): return JSONResponse(content={"message": "pong"})
@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)
@app.post("/api/v1/internal/notify_shares_changed")
async def notify_shares_changed(request: Request):
    try:
        event_data = {"event": "shares_updated", "device_name": request.app.state.controller.device_name}
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
@app.get("/api/v1/peers")
def get_peers(): return JSONResponse(content=online_devices)
@app.get("/api/v1/shares")
def list_shares():
    shares = load_config(force_reload=True).get('shares', [])
    return JSONResponse(content=[{"name": s.get("name"), "permissions": s.get("permissions", [])} for s in shares])
@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    req_path, share = get_safe_path_and_share(share_name, path)
    if "read" not in share.get("permissions", []): raise HTTPException(status_code=403, detail="Read permission denied.")
    if not os.path.isdir(req_path): raise HTTPException(status_code=404, detail="Directory not found")
    try:
        file_list = []
        for name in os.listdir(req_path):
            try:
                p = os.path.join(req_path, name)
                is_dir = os.path.isdir(p)
                file_list.append({"name": name, "is_dir": is_dir, "size": os.path.getsize(p) if not is_dir else 0})
            except (OSError, PermissionError): continue
        return JSONResponse(content=file_list)
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
@app.get("/api/v1/download/{share_name}")
async def download_file(share_name: str, file_path: str):
    abs_path, share = get_safe_path_and_share(share_name, file_path)
    if "download" not in share.get("permissions", []): raise HTTPException(status_code=403, detail="Download permission denied.")
    if not os.path.isfile(abs_path): raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(abs_path, filename=os.path.basename(abs_path))
@app.post("/api/v1/upload/{share_name}")
async def upload_file(share_name: str, dest_path: str = "/", conflict_action: str = "overwrite", file: UploadFile = File(...)):
    up_dir, share = get_safe_path_and_share(share_name, dest_path)
    if "upload" not in share.get("permissions", []): raise HTTPException(status_code=403, detail="Upload permission denied.")
    dest = os.path.join(up_dir, file.filename)
    if not os.path.abspath(dest).startswith(os.path.abspath(up_dir)): raise HTTPException(status_code=403, detail="Invalid destination filename.")
    
    # 检查文件是否已存在
    if os.path.exists(dest):
        if conflict_action == "check":
            # 仅检查文件是否存在，返回冲突状态
            return {"exists": True, "filename": file.filename}
        elif conflict_action == "skip":
            # 跳过上传
            return {"message": "File skipped.", "action": "skipped"}
        elif conflict_action == "rename":
            # 自动重命名文件
            base_name, ext = os.path.splitext(file.filename)
            counter = 1
            while os.path.exists(dest):
                new_filename = f"{base_name}_{counter}{ext}"
                dest = os.path.join(up_dir, new_filename)
                counter += 1
    
    try:
        with open(dest, "wb") as buffer:
            while content := await file.read(1024 * 1024): buffer.write(content)
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    
    # 返回上传结果，包括实际使用的文件名
    return {
        "message": "File uploaded.",
        "filename": os.path.basename(dest),
        "action": "renamed" if conflict_action == "rename" and os.path.basename(dest) != file.filename else "overwrite"
    }
@app.post("/api/v1/create_dir/{share_name}")
async def create_directory(share_name: str, path: str):
    dir_path, share = get_safe_path_and_share(share_name, path)
    if "upload" not in share.get("permissions", []): raise HTTPException(status_code=403, detail="Upload permission denied.")
    try:
        os.makedirs(dir_path, exist_ok=True)
        return {"message": "Directory created."}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/delete/{share_name}")
async def delete_file(share_name: str, file_path: str):
    abs_path, share = get_safe_path_and_share(share_name, file_path)
    if "delete" not in share.get("permissions", []): raise HTTPException(status_code=403, detail="Delete permission denied.")
    
    try:
        if os.path.isdir(abs_path):
            import shutil
            shutil.rmtree(abs_path)
            return {"message": "Directory deleted."}
        elif os.path.isfile(abs_path):
            os.remove(abs_path)
            return {"message": "File deleted."}
        else:
            raise HTTPException(status_code=404, detail="File or directory not found.")
    except Exception as e: 
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/rename/{share_name}")
async def rename_file(share_name: str, file_path: str, new_name: str):
    abs_path, share = get_safe_path_and_share(share_name, file_path)
    if "rename" not in share.get("permissions", []): raise HTTPException(status_code=403, detail="Rename permission denied.")
    
    # 验证新名称是否有效
    if not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="Invalid new name.")
    
    try:
        # 获取父目录和新的完整路径
        parent_dir = os.path.dirname(abs_path)
        new_path = os.path.join(parent_dir, new_name)
        
        # 检查新路径是否已存在
        if os.path.exists(new_path):
            raise HTTPException(status_code=409, detail="A file or directory with that name already exists.")
        
        # 执行重命名
        os.rename(abs_path, new_path)
        return {"message": "File renamed."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))