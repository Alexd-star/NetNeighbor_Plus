"""
Web API服务，提供HTTP接口用于文件共享和设备通信
"""

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
from .path_utils import get_safe_path_and_share
from .discovery import online_devices
from .tcp_server import run_tcp_server


__all__ = ["app", "manager"]


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接"""

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


def iter_folder_as_tar(folder_path: str) -> Generator[bytes, None, None]:
    """
    一个健壮的生成器函数, 使用标准库 `tarfile` 以非阻塞方式流式生成TAR数据。
    """
    read_fd, write_fd = os.pipe()

    def writer_thread():
        try:
            with os.fdopen(write_fd, "wb") as writer_pipe:
                with tarfile.open(
                    fileobj=writer_pipe, mode="w|", format=tarfile.GNU_FORMAT
                ) as tar:
                    tar.add(folder_path, arcname=os.path.basename(folder_path))
        finally:
            pass

    thread = threading.Thread(target=writer_thread)
    thread.start()

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


@app.get("/api/v1/ping")
async def ping():
    return {"status": "ok", "timestamp": time.time()}


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def _notify_shares_changed(device_name: str = "external_client"):
    try:
        event_data = {
            "event": "shares_updated",
            "device_name": device_name,
        }
        await manager.broadcast(json.dumps(event_data))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/internal/notify_shares_changed")
async def notify_shares_changed_internal(request: Request):
    device_name = request.app.state.controller.device_name
    return await _notify_shares_changed(device_name)


@app.post("/api/v1/notify_shares_changed")
async def notify_shares_changed_external():
    return await _notify_shares_changed("external_client")


@app.post("/api/v1/notify_file_changed")
async def notify_file_changed_external(request: Request):
    try:
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

        event_key = f"{share_name}:{path}"
        current_time = time.time()
        if event_key in notify_file_changed_external.last_events:
            last_time = notify_file_changed_external.last_events[event_key]
            if current_time - last_time < 1.0:
                return {"status": "debounced"}

        notify_file_changed_external.last_events[event_key] = current_time
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
    shares = load_config().get("shares", [])
    return JSONResponse(
        content=[
            {"name": s.get("name"), "permissions": s.get("permissions", [])}
            for s in shares
        ]
    )


@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    req_path, share = get_safe_path_and_share(share_name, path)
    if "read" not in share.get("permissions", ["read"]):  # 默认添加read权限
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

    file_name = file.filename
    if not file_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty.")

    dest = os.path.join(up_dir, file_name)
    if not os.path.abspath(dest).startswith(os.path.abspath(up_dir)):
        raise HTTPException(status_code=403, detail="Invalid destination filename.")

    if os.path.exists(dest):
        if conflict_action == "check":
            return {"exists": True, "filename": file_name}
        elif conflict_action == "skip":
            return {"message": "File skipped.", "action": "skipped"}
        elif conflict_action == "rename":
            base_name, ext = os.path.splitext(file_name)
            counter = 1
            new_filename = file_name  # 初始化为原文件名
            while os.path.exists(dest):
                new_filename = f"{base_name}_{counter}{ext}"
                dest = os.path.join(up_dir, new_filename)
                counter += 1
            # 更新file_name为重命名后的文件名
            file_name = new_filename

    try:
        with open(dest, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": "File uploaded.",
        "filename": os.path.basename(dest),
        "action": (
            "renamed"
            if conflict_action == "rename" and os.path.basename(dest) != file_name
            else "overwrite"
        ),
    }


# 新建文件夹的API端点
@app.post("/api/v1/create_dir/{share_name}")
async def create_directory(share_name: str, path: str, dir_name: str):
    dir_path, share = get_safe_path_and_share(share_name, path)
    if "upload" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Upload permission denied.")

    new_dir_path = os.path.join(dir_path, dir_name)
    if not os.path.abspath(new_dir_path).startswith(os.path.abspath(dir_path)):
        raise HTTPException(status_code=403, detail="Invalid directory name.")

    if os.path.exists(new_dir_path):
        raise HTTPException(
            status_code=409, detail=f"Directory '{dir_name}' already exists."
        )

    try:
        os.makedirs(new_dir_path, exist_ok=True)
        return {"message": "Directory created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/delete/{share_name}")
async def delete_file(share_name: str, file_path: str):
    try:
        full_path, target_share = get_safe_path_and_share(share_name, file_path)

        if "delete" not in target_share.get("permissions", []):
            raise HTTPException(
                status_code=403,
                detail="Permission denied: Delete operation not allowed",
            )

        is_directory = os.path.isdir(full_path)

        if is_directory:
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)

        event_data = {
            "event": "refresh_files",
            "share_name": share_name,
            "path": os.path.dirname(file_path),
            "source": "api",
            "deleted_files": [
                {
                    "share_name": share_name,
                    "path": file_path,
                    "is_directory": is_directory,
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
    try:
        full_path, target_share = get_safe_path_and_share(share_name, file_path)

        if "rename" not in target_share.get("permissions", []):
            raise HTTPException(
                status_code=403,
                detail="Permission denied: Rename operation not allowed",
            )

        dir_path = os.path.dirname(full_path)
        new_full_path = os.path.join(dir_path, new_name)

        if os.path.exists(new_full_path):
            raise HTTPException(
                status_code=409, detail="A file or folder with this name already exists"
            )

        os.rename(full_path, new_full_path)

        event_data = {
            "event": "refresh_files",
            "share_name": share_name,
            "path": os.path.dirname(file_path),
            "source": "api",
            "renamed_files": [
                {
                    "share_name": share_name,
                    "old_path": file_path,
                    "new_path": os.path.join(
                        os.path.dirname(file_path), new_name
                    ).replace("\\", "/"),
                    "is_directory": os.path.isdir(new_full_path),
                }
            ],
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
    up_dir, share = get_safe_path_and_share(share_name, dest_path)
    if "upload" not in share.get("permissions", []):
        raise HTTPException(status_code=403, detail="Upload permission denied.")

    temp_tar = tempfile.NamedTemporaryFile(delete=False, suffix=".tar")
    temp_tar_path = temp_tar.name
    temp_tar.close()

    try:
        with open(temp_tar_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)

        temp_dir = tempfile.mkdtemp()

        with tarfile.open(temp_tar_path) as tar:
            tar.extractall(path=temp_dir)

        extracted_items = os.listdir(temp_dir)
        if not extracted_items:
            return {"message": "Empty tar file uploaded.", "action": "completed"}

        source_folder_name = extracted_items[0]
        source_path = os.path.join(temp_dir, source_folder_name)
        target_path = os.path.join(up_dir, source_folder_name)
        final_folder_name = source_folder_name

        # 重构冲突处理逻辑
        action_taken = conflict_action

        if os.path.exists(target_path):
            if conflict_action == "skip":
                return {"message": "Folder skipped.", "action": "skipped"}

            elif conflict_action == "rename":
                counter = 1
                base_name = source_folder_name
                new_target_path = target_path
                while os.path.exists(new_target_path):
                    new_folder_name = f"{base_name}_{counter}"
                    new_target_path = os.path.join(up_dir, new_folder_name)
                    counter += 1
                final_folder_name = os.path.basename(new_target_path)
                shutil.copytree(source_path, new_target_path)
                action_taken = "renamed"

            elif conflict_action == "merge":
                for root, dirs, files in os.walk(source_path):
                    rel_path = os.path.relpath(root, source_path)
                    target_dir = os.path.join(target_path, rel_path)
                    os.makedirs(target_dir, exist_ok=True)
                    for file_item in files:
                        src_file = os.path.join(root, file_item)
                        dst_file = os.path.join(target_dir, file_item)
                        if not os.path.exists(dst_file):
                            shutil.copy2(src_file, dst_file)
                action_taken = "merged"

            elif conflict_action == "overwrite":
                shutil.rmtree(target_path)
                shutil.copytree(source_path, target_path)
                action_taken = "overwritten"
        else:
            shutil.copytree(source_path, target_path)
            action_taken = "created"

        return {
            "message": "Folder uploaded successfully.",
            "folder_name": final_folder_name,
            "action": action_taken,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading folder: {str(e)}")
    finally:
        if os.path.exists(temp_tar_path):
            os.unlink(temp_tar_path)
        if "temp_dir" in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
