"""
日志视图类，用于显示日志消息
"""

from typing import Dict, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit


class LogView(QWidget):
    """日志视图，显示日志消息"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)

        # 标题
        title_label = QLabel("<h4>事件日志</h4>")
        layout.addWidget(title_label)

        # 日志文本框
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        layout.addWidget(self.log_text_edit)

        # 设置最小高度
        self.setMinimumHeight(150)

    def add_log(self, log_entry: Dict[str, Any]):
        """添加日志条目"""
        formatted_log = (
            f"{log_entry['icon']} [{log_entry['timestamp']}] {log_entry['message']}"
        )
        self.log_text_edit.append(formatted_log)

    def add_log_message(
        self, message: str, icon: str = "ℹ️", timestamp: Optional[str] = None
    ):
        """直接添加日志消息"""
        if timestamp:
            formatted_log = f"{icon} [{timestamp}] {message}"
        else:
            formatted_log = f"{icon} {message}"
        self.log_text_edit.append(formatted_log)

    def clear_logs(self):
        """清空日志"""
        self.log_text_edit.clear()
