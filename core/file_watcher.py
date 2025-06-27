# 文件: core/file_watcher.py
import os
import time
from typing import List, Callable, Dict

def get_directory_snapshot(path: str) -> Dict[str, float]:
    """获取一个目录的快照，包含所有文件名及其最后修改时间。"""
    snapshot = {}
    try:
        for item in os.listdir(path):
            try: snapshot[item] = os.path.getmtime(os.path.join(path, item))
            except FileNotFoundError: continue
    except FileNotFoundError: pass
    return snapshot

def start_file_watcher(paths_to_watch: List[str], change_callback: Callable, stop_event):
    """启动文件系统轮询监视器。"""
    print("文件监视器已启动 (轮询模式)。")
    snapshots = {path: get_directory_snapshot(path) for path in paths_to_watch}
    while not stop_event.is_set():
        time.sleep(2)
        for path in paths_to_watch:
            current_snapshot = get_directory_snapshot(path)
            if current_snapshot != snapshots.get(path):
                print(f"轮询检测到文件夹 '{path}' 发生变化。")
                snapshots[path] = current_snapshot
                change_callback()
                break 
    print("文件监视器已关闭。")