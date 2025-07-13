"""
日志Presenter类，连接日志模型和视图
"""

from gui.models.log_model import LogModel
from gui.views.log_view import LogView


class LogPresenter:
    """日志Presenter，连接日志模型和视图"""

    def __init__(self, model: LogModel, view: LogView):
        self.model = model
        self.view = view

        # 连接模型和视图
        self.model.on_log_added(self._on_log_added)

    def _on_log_added(self, log_entry):
        """处理日志添加事件"""
        self.view.add_log(log_entry)

    def add_log(self, message: str, icon: str = "ℹ️"):
        """添加日志消息"""
        self.model.add_log(message, icon)

    def clear_logs(self):
        """清空日志"""
        self.model.clear_logs()
        self.view.clear_logs()
