"""
文件系统监控模块，监控文件变化并触发相应事件
"""

import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class DebouncedChangeHandler(FileSystemEventHandler):
    """一个带有防抖功能的事件处理器。"""

    def __init__(self, callback, debounce_interval=1.0):
        self.callback = callback
        self.debounce_interval = debounce_interval
        self.last_triggered_time = 0
        self.timer = None
        self.recent_delete_events = []
        self.recent_moved_events = []

    def on_any_event(self, event):
        # 处理删除事件
        if event.event_type == "deleted":
            self.recent_delete_events.append(
                {
                    "path": event.src_path,
                    "is_directory": event.is_directory,
                    "time": time.time(),
                }
            )
        # 处理重命名/移动事件
        elif event.event_type == "moved":
            self.recent_moved_events.append(
                {
                    "src_path": event.src_path,
                    "dest_path": event.dest_path,
                    "is_directory": event.is_directory,
                    "time": time.time(),
                }
            )

        current_time = time.time()
        if current_time - self.last_triggered_time > self.debounce_interval:
            self.last_triggered_time = current_time
            # 过滤删除事件，只保留顶级删除事件（文件夹删除时不包含其内部文件）
            filtered_delete_events = self._filter_delete_events(
                self.recent_delete_events
            )
            self.callback(filtered_delete_events, self.recent_moved_events)
            self.recent_delete_events = []
            self.recent_moved_events = []

    def _filter_delete_events(self, delete_events):
        """过滤删除事件，只保留顶级删除事件"""
        if not delete_events:
            return []

        # 按路径长度排序，短路径在前
        sorted_events = sorted(delete_events, key=lambda x: len(x["path"]))
        filtered_events = []

        for event in sorted_events:
            # 检查是否是其他已添加事件的子路径
            is_child = False
            for existing_event in filtered_events:
                if event["path"].startswith(existing_event["path"] + "/") or event[
                    "path"
                ].startswith(existing_event["path"] + "\\"):
                    is_child = True
                    break

            if not is_child:
                filtered_events.append(event)

        return filtered_events


def start_file_watcher(paths_to_watch: list, change_callback, stop_event):
    """使用 watchdog 启动一个高效的文件系统监视器。"""
    if not paths_to_watch:
        print("文件监视器：没有路径可供监视。")
        return

    print(f"文件监视器 (Watchdog) 已启动，正在监视: {paths_to_watch}")
    observer = Observer()
    event_handler = DebouncedChangeHandler(change_callback)

    for path in paths_to_watch:
        try:
            observer.schedule(event_handler, path, recursive=True)
        except Exception as e:
            print(f"错误: 无法监视路径 '{path}': {e}")

    if not observer.emitters:
        print("文件监视器：没有成功添加任何有效路径。")
        return

    observer.start()
    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
    print("文件监视器已关闭。")
