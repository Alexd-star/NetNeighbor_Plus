# 文件: core/web_api.py
# 描述: 提供 FastAPI 应用实例，文件夹下载使用标准的 tarfile 实现。

import asyncio
import json
import os
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Tuple, Generator

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
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


def get_safe_path_and_share(
    share_name: str, sub_path: str = "/"
) -> Tuple[str, Dict[str, Any]]:
    """安全地解析请求的路径, 防止路径遍历, 并返回共享配置。"""
    all_shares = load_config(force_reload=True).get("shares", [])
    target_share = next((s for s in all_shares if s.get("name") == share_name), None)

    if not target_share:
        raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")

    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip("/\\"))
    full_path = os.path.join(base_path, safe_sub_path)

    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(
            status_code=403, detail="Access denied: Path traversal attempt detected."
        )

    return full_path, target_share


def iter_folder_as_tar(folder_path: str) -> Generator[bytes, None, None]:
    """
    一个健壮的生成器函数, 使用标准库 `tarfile` 以非阻塞方式流式生成TAR数据。
    """
    read_fd, write_fd = os.pipe()

    def writer_thread():
        # 在一个独立的线程中进行写操作，防止阻塞FastAPI的事件循环
        try:
            with os.fdopen(write_fd, "wb") as writer_pipe:
                with tarfile.open(
                    fileobj=writer_pipe, mode="w|", format=tarfile.GNU_FORMAT
                ) as tar:
                    tar.add(folder_path, arcname=os.path.basename(folder_path))
        finally:
            # 确保写端在完成后总是关闭，这会向读端发送EOF信号
            pass

    thread = threading.Thread(target=writer_thread)
    thread.start()

    # 在主线程中从管道的读端读取数据
    try:
        with os.fdopen(read_fd, "rb") as reader_pipe:
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
    以TAR流式下载文件夹。
    """
    absolute_path, target_share = get_safe_path_and_share(share_name, folder_path)

    if "download" not in target_share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Download permission denied.")
    if not os.path.isdir(absolute_path):
        raise HTTPException(status_code=404, detail="Folder not found.")

    folder_name = os.path.basename(os.path.normpath(absolute_path))
    encoded_filename = urllib.parse.quote(folder_name, safe="")
    ascii_fallback_filename = (
        folder_name.encode("ascii", "ignore").decode("ascii") or "download"
    )

    content_disposition = (
        f'attachment; filename="{ascii_fallback_filename}.tar"; '
        f"filename*=UTF-8''{encoded_filename}.tar"
    )
    headers = {"Content-Disposition": content_disposition}

    return StreamingResponse(
        iter_folder_as_tar(absolute_path),
        media_type="application/x-tar",
        headers=headers,
    )


# --- 其余API端点保持不变 (为简洁省略) ---


@app.get("/api/v1/ping")
async def ping():
    """简单的ping端点，用于测量延迟"""
    return {"status": "ok", "timestamp": time.time()}


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
        event_data = {
            "event": "shares_updated",
            "device_name": request.app.state.controller.device_name,
        }
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/notify_shares_changed")
async def notify_shares_changed_external():
    """外部API端点，用于客户端通知共享变更"""
    try:
        event_data = {"event": "shares_updated", "device_name": "external_client"}
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/notify_file_changed")
async def notify_file_changed_external(request: Request):
    """外部API端点，用于客户端通知文件变更"""
    try:
        # 使用静态变量存储最近的事件，用于防抖
        if not hasattr(notify_file_changed_external, "last_events"):
            notify_file_changed_external.last_events = {}

        data = await request.json()
        share_name = data.get("share_name")
        path = data.get("path")

        if not share_name or path is None:
            raise HTTPException(
                status_code=400,
                detail="Missing required parameters: share_name or path",
            )

        # 创建事件键
        event_key = f"{share_name}:{path}"

        # 检查是否是重复事件（1秒内的相同事件）
        current_time = time.time()
        if event_key in notify_file_changed_external.last_events:
            last_time = notify_file_changed_external.last_events[event_key]
            if current_time - last_time < 1.0:  # 1秒防抖
                return {"status": "debounced"}

        # 更新最后事件时间
        notify_file_changed_external.last_events[event_key] = current_time

        # 清理旧事件（超过10秒的事件）
        notify_file_changed_external.last_events = {
            k: v
            for k, v in notify_file_changed_external.last_events.items()
            if current_time - v < 10.0
        }

        event_data = {"event": "refresh_files", "share_name": share_name, "path": path}
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/peers")
def get_peers():
    return JSONResponse(content=online_devices)


@app.get("/api/v1/shares")
def list_shares():
    shares = load_config(force_reload=True).get("shares", [])
    return JSONResponse(
        content=[
            {"name": s.get("name"), "permissions": s.get("permissions", [])}
            for s in shares
        ]
    )


@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    req_path, share = get_safe_path_and_share(share_name, path)
    if "read" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Read permission denied.")
    if not os.path.isdir(req_path):
        raise HTTPException(status_code=404, detail="Directory not found")
    try:
        file_list = []
        for name in os.listdir(req_path):
            try:
                p = os.path.join(req_path, name)
                is_dir = os.path.isdir(p)
                file_list.append(
                    {
                        "name": name,
                        "is_dir": is_dir,
                        "size": os.path.getsize(p) if not is_dir else 0,
                    }
                )
            except (OSError, PermissionError):
                continue
        return JSONResponse(content=file_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/download/{share_name}")
async def download_file(share_name: str, file_path: str):
    abs_path, share = get_safe_path_and_share(share_name, file_path)
    if "download" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Download permission denied.")
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(abs_path, filename=os.path.basename(abs_path))


@app.post("/api/v1/upload/{share_name}")
async def upload_file(
    share_name: str,
    dest_path: str = "/",
    conflict_action: str = "overwrite",
    file: UploadFile = File(...),
):
    up_dir, share = get_safe_path_and_share(share_name, dest_path)
    if "upload" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Upload permission denied.")
    dest = os.path.join(up_dir, file.filename)
    if not os.path.abspath(dest).startswith(os.path.abspath(up_dir)):
        raise HTTPException(status_code=403, detail="Invalid destination filename.")

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
            while content := await file.read(1024 * 1024):
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 返回上传结果，包括实际使用的文件名
    return {
        "message": "File uploaded.",
        "filename": os.path.basename(dest),
        "action": (
            "renamed"
            if conflict_action == "rename" and os.path.basename(dest) != file.filename
            else "overwrite"
        ),
    }


@app.post("/api/v1/create_dir/{share_name}")
async def create_directory(share_name: str, path: str):
    dir_path, share = get_safe_path_and_share(share_name, path)
    if "upload" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Upload permission denied.")
    try:
        os.makedirs(dir_path, exist_ok=True)
        return {"message": "Directory created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/delete/{share_name}")
async def delete_file(share_name: str, file_path: str):
    """删除文件或文件夹的API端点"""
    try:
        # 验证路径安全性
        full_path, target_share = get_safe_path_and_share(share_name, file_path)

        # 检查权限
        if "delete" not in target_share.get("permissions", []):
            raise HTTPException(
                status_code=403,
                detail="Permission denied: Delete operation not allowed",
            )

        # 执行删除操作
        if os.path.isdir(full_path):
            # 删除文件夹及其内容
            shutil.rmtree(full_path)
        else:
            # 删除单个文件
            os.remove(full_path)

        # 触发文件变更事件
        event_data = {
            "event": "refresh_files",
            "share_name": share_name,
            "path": os.path.dirname(file_path),
            "deleted_files": [
                {
                    "share_name": share_name,
                    "path": file_path,
                    "is_directory": os.path.isdir(full_path),
                }
            ],
        }
        await manager.broadcast(json.dumps(event_data))

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@app.post("/api/v1/rename/{share_name}")
async def rename_file(share_name: str, file_path: str, new_name: str):
    """重命名文件或文件夹的API端点"""
    try:
        # 验证路径安全性
        full_path, target_share = get_safe_path_and_share(share_name, file_path)

        # 检查权限
        if "rename" not in target_share.get("permissions", []):
            raise HTTPException(
                status_code=403,
                detail="Permission denied: Rename operation not allowed",
            )

        # 获取目录和文件名
        dir_path = os.path.dirname(full_path)
        new_full_path = os.path.join(dir_path, new_name)

        # 检查新名称是否已存在
        if os.path.exists(new_full_path):
            raise HTTPException(
                status_code=409, detail="A file or folder with this name already exists"
            )

        # 执行重命名操作
        os.rename(full_path, new_full_path)

        # 触发文件变更事件
        event_data = {
            "event": "refresh_files",
            "share_name": share_name,
            "path": os.path.dirname(file_path),
        }
        await manager.broadcast(json.dumps(event_data))

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename file: {str(e)}")


@app.post("/api/v1/upload_folder_tar/{share_name}")
async def upload_folder_tar(
    share_name: str,
    dest_path: str = "/",
    conflict_action: str = "overwrite",
    file: UploadFile = File(...),
):
    """
    处理tar格式的文件夹上传请求。
    接收一个tar文件流，解压到目标路径，并处理文件冲突。
    """
    up_dir, share = get_safe_path_and_share(share_name, dest_path)
    if "upload" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Upload permission denied.")

    # 创建临时文件保存上传的tar数据
    temp_tar = tempfile.NamedTemporaryFile(delete=False, suffix=".tar")
    temp_tar_path = temp_tar.name
    temp_tar.close()

    try:
        # 将上传的tar文件保存到临时文件
        with open(temp_tar_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)

        # 创建临时目录用于解压tar文件
        temp_dir = tempfile.mkdtemp()

        # 解压tar文件到临时目录
        with tarfile.open(temp_tar_path) as tar:
            tar.extractall(path=temp_dir)

        # 获取tar文件中的顶级目录/文件
        extracted_items = os.listdir(temp_dir)
        if not extracted_items:
            return {"message": "Empty tar file uploaded.", "action": "completed"}

        # 假设tar文件只包含一个顶级目录（文件夹上传的情况）
        folder_name = extracted_items[0]
        source_path = os.path.join(temp_dir, folder_name)
        target_path = os.path.join(up_dir, folder_name)

        # 处理冲突
        if os.path.exists(target_path):
            if conflict_action == "skip":
                return {"message": "Folder skipped.", "action": "skipped"}
            elif conflict_action == "rename":
                # 自动重命名文件夹
                counter = 1
                base_name = folder_name
                while os.path.exists(target_path):
                    new_folder_name = f"{base_name}_{counter}"
                    target_path = os.path.join(up_dir, new_folder_name)
                    counter += 1
                folder_name = os.path.basename(target_path)
            elif conflict_action == "merge":
                # 合并模式，保持target_path不变，后续会逐个文件复制
                pass
            # overwrite模式下，会删除已存在的目标文件夹
            elif conflict_action == "overwrite" and os.path.exists(target_path):
                shutil.rmtree(target_path)

        # 复制解压后的文件到目标位置
        if os.path.isdir(source_path):
            if conflict_action == "merge" and os.path.exists(target_path):
                # 合并模式：递归复制文件，保留已存在的文件
                for root, dirs, files in os.walk(source_path):
                    rel_path = os.path.relpath(root, source_path)
                    target_dir = os.path.join(target_path, rel_path)
                    os.makedirs(target_dir, exist_ok=True)
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_dir, file)
                        if not os.path.exists(dst_file):
                            shutil.copy2(src_file, dst_file)
            else:
                # 创建新文件夹或覆盖已有文件夹
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                shutil.copytree(source_path, target_path)
        else:
            # 单个文件的情况
            shutil.copy2(source_path, target_path)

        return {
            "message": "Folder uploaded successfully.",
            "folder_name": folder_name,
            "action": (
                "renamed"
                if conflict_action == "rename" and folder_name != extracted_items[0]
                else conflict_action
            ),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading folder: {str(e)}")
    finally:
        # 清理临时文件和目录
        if os.path.exists(temp_tar_path):
            os.unlink(temp_tar_path)
        if "temp_dir" in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
