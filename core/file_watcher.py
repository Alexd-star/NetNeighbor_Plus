# 文件: core/file_watcher.py (全新轮询版)

import os
import time
from typing import List, Callable, Dict


def get_directory_snapshot(path: str) -> Dict[str, float]:
    """
    获取一个目录的快照，包含所有文件名及其最后修改时间。
    """
    snapshot = {}
    try:
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            try:
                # 我们只关心文件和文件夹本身的存在与否及其修改时间
                snapshot[item] = os.path.getmtime(item_path)
            except FileNotFoundError:
                # 文件可能在列出和获取状态之间被删除，忽略即可
                continue
    except FileNotFoundError:
        # 整个目录可能被删除了
        pass
    return snapshot


def start_file_watcher(paths_to_watch: List[str], change_callback: Callable):
    """
    启动文件系统轮询监视器。
    :param paths_to_watch: 一个包含所有需要监视的文件夹路径的列表。
    :param change_callback: 当检测到变化时要调用的回调函数。
    """
    print("文件监视器已启动 (轮询模式)。")
    # 为每个要监视的路径创建一个初始快照
    snapshots = {path: get_directory_snapshot(path) for path in paths_to_watch}

    while True:
        time.sleep(2)  # 每2秒检查一次
        for path in paths_to_watch:
            current_snapshot = get_directory_snapshot(path)

            # 如果快照与上一次不同（文件数量或修改时间变化），则认为发生了变化
            if current_snapshot != snapshots.get(path):
                print(f"轮询检测到文件夹 '{path}' 发生变化。")
                # 更新快照
                snapshots[path] = current_snapshot
                # 调用回调函数，通知前端刷新
                change_callback()
                # 跳出内层循环，避免因一次改动触发多次回调
                break