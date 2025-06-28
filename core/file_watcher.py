# 文件: core/file_watcher.py (升级)
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class DebouncedChangeHandler(FileSystemEventHandler):
    """
    一个带有防抖功能的事件处理器。
    在短时间内接收到多个事件时，只触发一次回调。
    """

    def __init__(self, callback, debounce_interval=1.0):
        self.callback = callback
        self.debounce_interval = debounce_interval
        self.last_triggered_time = 0
        self.timer = None

    def on_any_event(self, event):
        # 忽略目录自身的修改事件，只关心内容变化
        if event.is_directory:
            return

        current_time = time.time()
        if current_time - self.last_triggered_time > self.debounce_interval:
            self.last_triggered_time = current_time
            print(f"Watchdog 检测到变化: {event.src_path}, 事件: {event.event_type}")
            self.callback()


def start_file_watcher(paths_to_watch: list, change_callback, stop_event):
    """
    使用 watchdog 启动一个高效的文件系统监视器。
    """
    if not paths_to_watch:
        print("文件监视器：没有路径可供监视。")
        return

    print(f"文件监视器 (Watchdog) 已启动，正在监视: {paths_to_watch}")
    observer = Observer()
    event_handler = DebouncedChangeHandler(change_callback)

    for path in paths_to_watch:
        try:
            # recursive=True 确保能监控所有子目录
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