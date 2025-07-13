"""
传输任务管理器类，管理所有传输任务
"""

from typing import Dict, Any, List, Optional, Callable
import os
import time
import uuid

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QHBoxLayout,
    QMessageBox,
)
from PySide6.QtGui import QIcon

from gui.models.transfer_model import TransferModel
from gui.models.log_model import LogModel
from gui.models.connection_model import ConnectionModel
from gui.views.transfer_list_view import TransferListView
from gui.worker_thread import WorkerThread


class MinimizableProgressDialog(QDialog):
    """可最小化的进度对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文件传输")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)

        # 进度信息
        self.label = QLabel("准备开始...")
        layout.addWidget(self.label)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")  # 设置进度条格式为百分比
        layout.addWidget(self.progress_bar)

        # 按钮区域
        button_layout = QHBoxLayout()

        # 取消按钮
        self.cancel_button = QPushButton("取消")
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()

        # 后台运行按钮
        self.background_button = QPushButton("后台运行")
        self.background_button.setToolTip("最小化到状态栏")
        button_layout.addWidget(self.background_button)

        layout.addLayout(button_layout)

    def set_progress(self, value: int):
        """设置进度值"""
        self.progress_bar.setValue(value)
        # 确保进度条显示准确的百分比值
        self.progress_bar.setFormat(f"{value}%")

    def set_text(self, text: str):
        """设置文本"""
        self.label.setText(text)

    def set_indeterminate_mode(self, indeterminate: bool):
        """设置是否为不确定模式（适用于未知大小的传输）"""
        if indeterminate:
            # 将进度条设置为不确定模式
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("传输中...")
        else:
            # 恢复确定模式
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("%p%")
            self.progress_bar.setValue(0)


class TransferManager(QObject):
    """传输任务管理器，管理所有传输任务"""

    task_added = Signal(str, dict)  # 任务ID, 任务信息
    task_progress = Signal(str, int)  # 任务ID, 进度值
    task_status = Signal(str, str)  # 任务ID, 状态文本
    task_speed = Signal(str, str)  # 任务ID, 速度文本
    task_completed = Signal(str)  # 任务ID
    task_error = Signal(str, str)  # 任务ID, 错误信息

    all_tasks_completed = Signal()  # 所有任务完成信号

    def __init__(
        self,
        transfer_model: TransferModel,
        log_model: LogModel,
        connection_model: ConnectionModel,
    ):
        super().__init__()
        self.transfer_model = transfer_model
        self.log_model = log_model
        self.connection_model = connection_model

        # 任务队列
        self.task_queue = []  # 等待执行的任务
        self.active_tasks = {}  # 正在执行的任务 {task_id: task_info}
        self.completed_tasks = {}  # 已完成的任务 {task_id: task_info}

        # 当前工作线程
        self.worker_thread = None

        # 进度对话框
        self.progress_dialog = None

        # 是否静默模式
        self.silent_mode = False

        # 悬浮传输列表视图
        self.floating_transfer_view = None

    def set_transfer_list_view(self, view: TransferListView):
        """设置传输列表视图（兼容旧接口，实际使用悬浮窗口）"""
        # 此方法保留但不再使用
        pass

    def set_floating_transfer_view(self, view: TransferListView):
        """设置悬浮传输列表视图"""
        self.floating_transfer_view = view

        # 连接信号
        view.task_cancelled.connect(self._on_task_cancelled)

    def set_icons(self, download_icon: QIcon, upload_icon: QIcon):
        """设置图标"""
        if self.floating_transfer_view:
            self.floating_transfer_view.set_icons(download_icon, upload_icon)

    def add_tasks(
        self, title: str, tasks: List[Dict[str, Any]], silent: bool = False
    ) -> bool:
        """添加传输任务，返回是否成功添加"""
        if not tasks:
            return False

        # 设置静默模式
        self.silent_mode = silent

        # 生成任务ID
        for task in tasks:
            task_id = str(uuid.uuid4())
            task["id"] = task_id
            task["title"] = title
            task["added_time"] = time.time()
            task["status"] = "queued"  # queued, running, completed, error
            task["progress"] = 0
            task["speed"] = ""

            # 添加到队列
            self.task_queue.append(task)

            # 发射任务添加信号
            self.task_added.emit(task_id, task)

            # 添加到悬浮传输列表视图
            if self.floating_transfer_view:
                self.floating_transfer_view.add_task(
                    task_id, task["name"], task["type"]
                )

        # 如果当前没有活动任务，则启动下一个任务
        if not self.worker_thread:
            self._start_next_task()

        return True

    def _start_next_task(self):
        """启动下一个任务"""
        if not self.task_queue:
            # 所有任务完成
            self.all_tasks_completed.emit()
            return

        # 获取下一个任务
        task = self.task_queue.pop(0)
        task_id = task["id"]

        # 更新任务状态
        task["status"] = "running"

        # 添加到活动任务
        self.active_tasks[task_id] = task

        # 设置传输模型状态为活动
        self.transfer_model.set_is_transfer_active(True)

        # 创建进度对话框
        if not self.silent_mode:
            self.progress_dialog = MinimizableProgressDialog()
            self.progress_dialog.setWindowTitle(task["title"])

            # 连接取消按钮
            self.progress_dialog.cancel_button.clicked.connect(self._on_cancel)

            # 连接后台运行按钮
            self.progress_dialog.background_button.clicked.connect(self._on_background)

            # 设置进度条模式
            is_folder_task = task["type"] == "download_folder_tcp"

            # 我们不再需要设置不确定模式，而是使用估计进度
            # 如果是文件夹下载任务，我们只需正常显示进度条即可

            # 显示对话框
            self.progress_dialog.show()

        # 创建工作线程
        self.worker_thread = WorkerThread([task])

        # 连接信号
        self.worker_thread.progress.connect(
            lambda value: self._on_progress(task_id, value)
        )
        self.worker_thread.progress_text_update.connect(
            lambda text: self._on_progress_text_update(task_id, text)
        )
        self.worker_thread.speed_update.connect(
            lambda speed: self._on_speed_update(task_id, speed)
        )
        self.worker_thread.file_finished.connect(
            lambda msg: self._on_file_finished(task_id, msg)
        )
        self.worker_thread.all_finished.connect(lambda: self._on_all_finished(task_id))
        self.worker_thread.error.connect(lambda error: self._on_error(task_id, error))
        self.worker_thread.conflict_resolution_needed.connect(
            self._on_conflict_resolution_needed
        )

        # 启动线程
        self.worker_thread.start()

    def _on_progress(self, task_id: str, value: int):
        """处理进度更新"""
        # 更新任务进度
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["progress"] = value

        # 更新进度对话框
        if self.progress_dialog and not self.silent_mode:
            self.progress_dialog.set_progress(value)

        # 更新悬浮传输列表视图
        if self.floating_transfer_view:
            self.floating_transfer_view.update_task_progress(task_id, value)

        # 发射进度信号
        self.task_progress.emit(task_id, value)

    def _on_progress_text_update(self, task_id: str, text: str):
        """处理进度文本更新"""
        # 更新任务进度文本
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["progress_text"] = text

        # 更新进度对话框
        if self.progress_dialog and not self.silent_mode:
            self.progress_dialog.set_text(text)

        # 更新悬浮传输列表视图
        if self.floating_transfer_view:
            self.floating_transfer_view.update_task_status(task_id, text)

        # 发射状态信号
        self.task_status.emit(task_id, text)

    def _on_speed_update(self, task_id: str, speed_text: str):
        """处理速度更新"""
        # 更新任务速度
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["speed"] = speed_text

        # 更新进度对话框
        if self.progress_dialog and not self.silent_mode:
            current_text = self.progress_dialog.label.text()
            if "\n" in current_text:
                main_text = current_text.split("\n")[0]
                self.progress_dialog.set_text(f"{main_text}\n传输速度: {speed_text}")
            else:
                self.progress_dialog.set_text(f"{current_text}\n传输速度: {speed_text}")

        # 发射速度信号
        self.task_speed.emit(task_id, speed_text)

    def _on_file_finished(self, task_id: str, message: str):
        """处理文件完成"""
        # 添加日志
        self.log_model.add_log(message, "✅")

    def _on_all_finished(self, task_id: str):
        """处理所有任务完成事件"""
        # 更新任务状态
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task["status"] = "completed"

            # 确保进度显示为100%
            self._on_progress(task_id, 100)

            # 移动到已完成任务
            self.completed_tasks[task_id] = task
            del self.active_tasks[task_id]

        # 关闭进度对话框
        if self.progress_dialog and not self.silent_mode:
            self.progress_dialog.accept()
            self.progress_dialog = None

        # 添加日志
        self.log_model.add_log("传输任务已完成。", "🎉")

        # 从悬浮传输列表视图中移除
        if self.floating_transfer_view:
            self.floating_transfer_view.remove_task(task_id)

        # 发射任务完成信号
        self.task_completed.emit(task_id)

        # 清理工作线程
        if self.worker_thread:
            self.worker_thread.deleteLater()
        self.worker_thread = None

        # 如果没有更多任务，更新传输模型状态
        if not self.task_queue:
            self.transfer_model.set_is_transfer_active(False)
        else:
            # 启动下一个任务
            self._start_next_task()

    def _on_error(self, task_id: str, error_message: str):
        """处理错误"""
        # 更新任务状态
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task["status"] = "error"
            task["error"] = error_message

            # 移动到已完成任务
            self.completed_tasks[task_id] = task
            del self.active_tasks[task_id]

        # 关闭进度对话框
        if self.progress_dialog and not self.silent_mode:
            self.progress_dialog.reject()
            self.progress_dialog = None

        # 添加日志
        title = "传输错误"
        friendly_message = f"发生错误: {error_message}"
        error_lower = str(error_message).lower()

        if "403" in error_lower or "permission denied" in error_lower:
            title = "权限不足"
            friendly_message = "操作失败：对方未授予相应权限。"
        elif "404" in error_lower or "not found" in error_lower:
            title = "未找到"
            friendly_message = "操作失败：文件或文件夹在对方设备上已不存在。"
        elif "connectionrefusederror" in error_lower or "timed out" in error_lower:
            title = "连接失败"
            friendly_message = "无法连接到对方设备，请检查网络。"
        elif "cancelled" in error_lower:
            title = "任务取消"
            friendly_message = "任务已被用户取消。"

        self.log_model.add_log(friendly_message, "❌")

        # 从悬浮传输列表视图中移除
        if self.floating_transfer_view:
            self.floating_transfer_view.remove_task(task_id)

        # 显示错误消息
        if not self.silent_mode and "cancelled" not in error_lower:
            QMessageBox.critical(None, title, friendly_message, QMessageBox.Ok)

        # 发射错误信号
        self.task_error.emit(task_id, friendly_message)

        # 清理工作线程
        self.worker_thread = None

        # 如果没有更多任务，更新传输模型状态
        if not self.task_queue:
            self.transfer_model.set_is_transfer_active(False)

        # 启动下一个任务
        self._start_next_task()

    def _on_cancel(self):
        """处理取消操作"""
        if self.worker_thread:
            self.worker_thread.stop()

    def _on_background(self):
        """处理后台运行操作"""
        if self.progress_dialog:
            self.progress_dialog.hide()
            self.silent_mode = True

            # 显示悬浮传输列表视图
            if self.floating_transfer_view:
                # 设置传输模型状态为活动
                self.transfer_model.set_is_transfer_active(True)

                # 先发出位置更新请求
                from PySide6.QtCore import QTimer

                self.task_added.emit("update_position", {})

                # 延迟显示窗口，确保位置已更新
                QTimer.singleShot(100, lambda: self._show_floating_view())

            # 添加日志
            self.log_model.add_log("传输任务已最小化到状态栏", "ℹ️")

    def _show_floating_view(self):
        """显示悬浮窗口并确保其位置正确"""
        if self.floating_transfer_view:
            # 显示窗口
            self.floating_transfer_view.setVisible(True)

            # 确保所有任务项都显示正确的进度
            for task_id, task in self.active_tasks.items():
                progress = task.get("progress", 0)
                status = task.get("status", "")
                speed = task.get("speed", "")

                # 更新进度和状态
                self.floating_transfer_view.update_task_progress(task_id, progress)
                if status == "running":
                    status_text = task.get("progress_text", "准备中...")
                    if speed:
                        status_text += f" - {speed}"
                    self.floating_transfer_view.update_task_status(task_id, status_text)

            # 再次发送位置更新请求
            self.task_added.emit("update_position", {})

    def _on_conflict_resolution_needed(
        self, file_info: Dict[str, Any], event_obj: object
    ):
        """处理冲突解决请求"""
        if not self.worker_thread:
            return

        try:
            file_name = file_info.get("file_name", "未知文件")
            is_folder = file_info.get("is_folder", False)

            # 创建对话框
            msg_box = QMessageBox()
            msg_box.setWindowTitle("文件冲突")

            if is_folder:
                msg_box.setText(f"文件夹 '{file_name}' 已存在于目标位置。")
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel
                )
                msg_box.setButtonText(QMessageBox.StandardButton.Yes, "合并内容")
                msg_box.setButtonText(QMessageBox.StandardButton.No, "重命名")
                msg_box.setButtonText(QMessageBox.StandardButton.Cancel, "跳过")
            else:
                msg_box.setText(f"文件 '{file_name}' 已存在于目标位置。")
                msg_box.setInformativeText("请选择如何处理此冲突：")
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel
                )
                msg_box.setButtonText(QMessageBox.StandardButton.Yes, "覆盖")
                msg_box.setButtonText(QMessageBox.StandardButton.No, "重命名")
                msg_box.setButtonText(QMessageBox.StandardButton.Cancel, "跳过")

                # 添加"应用到所有冲突"复选框
                from PySide6.QtWidgets import QCheckBox

                apply_to_all_cb = QCheckBox("应用到所有冲突")
                msg_box.setCheckBox(apply_to_all_cb)

            # 显示对话框并获取用户选择
            result = msg_box.exec()

            # 处理结果
            resolution = {}

            if result == QMessageBox.StandardButton.Yes:
                resolution["action"] = "merge" if is_folder else "overwrite"
            elif result == QMessageBox.StandardButton.No:
                resolution["action"] = "rename"
            elif result == QMessageBox.StandardButton.Cancel:
                resolution["action"] = "skip"
            else:
                resolution["action"] = "cancelled"

            # 如果有"应用到所有冲突"选项并且被选中
            if (
                not is_folder
                and "apply_to_all_cb" in locals()
                and apply_to_all_cb.isChecked()
            ):
                resolution["apply_to_all"] = True

            # 设置结果并通知工作线程
            self.worker_thread.conflict_resolution_result = resolution
            event_obj.set()

        except Exception as e:
            print(f"处理冲突对话框时出错: {e}")
            # 设置默认结果并通知工作线程
            self.worker_thread.conflict_resolution_result = {"action": "skip"}
            event_obj.set()

    def _on_task_cancelled(self, task_index: int):
        """处理任务取消"""
        # 如果是活动任务
        if self.worker_thread and task_index == 0:
            self.worker_thread.stop()
            # 添加日志
            if self.active_tasks:
                task_id = list(self.active_tasks.keys())[0]
                task = self.active_tasks[task_id]
                self.log_model.add_log(f"已取消任务: {task['name']}", "❌")
            return

        # 如果是队列中的任务
        if task_index - 1 < len(self.task_queue):
            task = self.task_queue.pop(task_index - 1)
            task_id = task["id"]

            # 更新任务状态
            task["status"] = "cancelled"

            # 移动到已完成任务
            self.completed_tasks[task_id] = task

            # 从悬浮传输列表视图中移除
            if self.floating_transfer_view:
                self.floating_transfer_view.remove_task(task_id)

            # 添加日志
            self.log_model.add_log(f"已取消任务: {task['name']}", "❌")

    def _show_all_tasks(self):
        """显示所有任务"""
        # 此方法保留但不再使用
        pass

    def create_upload_file_tasks(
        self, file_paths: List[str], share_name: str, dest_path: str
    ) -> List[Dict[str, Any]]:
        """创建上传文件任务"""
        tasks = []
        for file_path in file_paths:
            task = {
                "type": "upload_file",
                "name": os.path.basename(file_path),
                "local_path": file_path,
                "peer_client": self.connection_model.get_active_peer_client(),
                "share_name": share_name,
                "dest_path": dest_path,
                "conflict_action": "ask",
            }
            tasks.append(task)
        return tasks

    def create_upload_folder_task(
        self, folder_path: str, share_name: str, dest_path: str
    ) -> Dict[str, Any]:
        """创建上传文件夹任务"""
        folder_name = os.path.basename(folder_path)
        return {
            "type": "upload_folder",
            "name": os.path.basename(folder_path),
            "local_path": folder_path,
            "peer_client": self.connection_model.get_active_peer_client(),
            "share_name": share_name,
            "dest_path": dest_path,
            "conflict_action": "ask",
        }

    def create_download_tasks(
        self,
        files: List[Dict[str, Any]],
        share_name: str,
        remote_path: str,
        save_dir: str,
    ) -> List[Dict[str, Any]]:
        """创建下载任务"""
        tasks = []
        for file_info in files:
            name = file_info["name"]
            is_dir = file_info["is_dir"]

            if is_dir:
                # 文件夹下载
                save_path = os.path.join(save_dir, f"{name}.tar")
                tasks.append(
                    {
                        "type": "download_folder_tcp",
                        "name": name,
                        "peer_client": self.connection_model.get_active_peer_client(),
                        "share_name": share_name,
                        "remote_path": f"{remote_path}/{name}".replace("//", "/"),
                        "save_path": save_path,
                    }
                )
            else:
                # 文件下载
                save_path = os.path.join(save_dir, name)
                tasks.append(
                    {
                        "type": "download_file",
                        "name": name,
                        "peer_client": self.connection_model.get_active_peer_client(),
                        "share_name": share_name,
                        "remote_path": f"{remote_path}/{name}".replace("//", "/"),
                        "save_path": save_path,
                    }
                )

        return tasks
