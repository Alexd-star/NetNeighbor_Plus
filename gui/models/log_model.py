"""
日志模型类，用于管理日志消息
"""

import time
from typing import Dict, Any, List, Callable


class LogModel:
    """日志数据模型，管理日志消息"""

    def __init__(self):
        self._log_messages: List[Dict[str, Any]] = []
        self._on_log_added_callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def add_log(self, message: str, icon: str = "ℹ️") -> None:
        timestamp = time.strftime("%H:%M:%S")
        log_entry = {"timestamp": timestamp, "message": message, "icon": icon}
        self._log_messages.append(log_entry)
        for callback in self._on_log_added_callbacks:
            callback(log_entry)

    def get_logs(self) -> List[Dict[str, Any]]:
        return self._log_messages.copy()

    def clear_logs(self) -> None:
        self._log_messages.clear()

    def on_log_added(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._on_log_added_callbacks.append(callback)

    def format_log_entry(self, log_entry: Dict[str, Any]) -> str:
        return f"{log_entry['icon']} [{log_entry['timestamp']}] {log_entry['message']}"
