import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from .config import config
from .discovery import online_devices

app = FastAPI()

def get_safe_path(share_name: str, sub_path: str = "/") -> str:
    target_share = next((s for s in config.get("shares", []) if s["name"] == share_name), None)
    if not target_share:
        raise HTTPException(status_code=404, detail=f"Share '{share_name}' not found")
    base_path = os.path.abspath(target_share["path"])
    safe_sub_path = os.path.normpath(sub_path.lstrip('/\\'))
    full_path = os.path.join(base_path, safe_sub_path)
    if not os.path.abspath(full_path).startswith(base_path):
        raise HTTPException(status_code=403, detail="Access to this path is denied")
    return full_path

@app.get("/api/v1/peers")
def get_peers():
    return JSONResponse(content=online_devices)

@app.get("/api/v1/shares")
def get_shares():
    share_list = [{"name": s["name"], "permissions": s["permissions"]} for s in config.get("shares", [])]
    return JSONResponse(content=share_list)

@app.get("/api/v1/files/{share_name}")
def list_files(share_name: str, path: str = "/"):
    request_path = get_safe_path(share_name, path)
    if not os.path.isdir(request_path):
        raise HTTPException(status_code=404, detail="Directory not found")
    try:
        file_list = []
        for item in os.listdir(request_path):
            item_path = os.path.join(request_path, item)
            is_dir = os.path.isdir(item_path)
            file_list.append({
                "name": item, "is_dir": is_dir, "size": os.path.getsize(item_path) if not is_dir else 0,
            })
        return JSONResponse(content=file_list)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Path not found")

@app.get("/api/v1/download/{share_name}")
def download_file(share_name: str, file_path: str):
    absolute_path = get_safe_path(share_name, file_path)
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(absolute_path, filename=os.path.basename(absolute_path))

@app.post("/api/v1/upload/{share_name}")
async def upload_file(share_name: str, dest_path: str = "/", file: UploadFile = File(...)):
    upload_dir = get_safe_path(share_name, dest_path)
    if not os.path.isdir(upload_dir):
        raise HTTPException(status_code=400, detail="Destination path is not a directory or does not exist.")
    file_destination = os.path.join(upload_dir, file.filename)
    try:
        with open(file_destination, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")
    return {"message": f"File '{file.filename}' uploaded successfully to '{dest_path}'."}