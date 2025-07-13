"""
传输Presenter类，管理文件传输任务
"""

import os
import time
from typing import Dict, Any, List, Optional, Callable

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QApplication

from gui.models.connection_model import ConnectionModel
from gui.models.log_model import LogModel
from gui.models.transfer_model import TransferModel
from gui.worker_thread import WorkerThread


class TransferPresenter(QObject):
    """传输Presenter，管理文件传输任务"""

    transfer_completed = Signal()  # 传输完成信号
    transfer_error = Signal(str)  # 传输错误信号

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

        self.progress_dialog = None
        self.worker_thread = None

    def start_transfer(self, title: str, tasks: List[Dict[str, Any]]):
        """启动传输任务"""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(
                None,
                "任务正在进行",
                "已有文件在传输中，请稍后重试。",
                QMessageBox.StandardButton.Ok,
            )
            return

        self.transfer_model.set_tasks(tasks)
        self.transfer_model.start_transfer()

        # 创建进度对话框
        self.progress_dialog = QProgressDialog()
        self.progress_dialog.setWindowTitle(title)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumWidth(400)  # 设置最小宽度
        self.progress_dialog.setMinimumDuration(0)  # 立即显示

        # 检查是否有文件夹下载任务
        is_downloading_folder = any(
            task.get("type") == "download_folder_tcp" for task in tasks
        )

        if is_downloading_folder:
            # 文件夹下载使用不确定模式
            self.progress_dialog.setRange(0, 0)
            self.transfer_model.set_progress_text("正在准备流式传输，总大小未知...")
        else:
            # 单个文件使用确定模式
            is_single_task = len(tasks) == 1
            self.progress_dialog.setRange(0, 100 if is_single_task else len(tasks))
            self.transfer_model.set_progress_text("准备开始...")

        # 设置对话框文本
        self.progress_dialog.setLabelText(self.transfer_model.get_progress_text())

        # 创建工作线程
        self.worker_thread = WorkerThread(tasks)

        # 连接信号
        self.worker_thread.progress.connect(self._on_progress)
        self.worker_thread.progress_text_update.connect(self._on_progress_text_update)
        self.worker_thread.speed_update.connect(self._on_speed_update)
        self.worker_thread.file_finished.connect(self._on_file_finished)
        self.worker_thread.all_finished.connect(self._on_all_finished)
        self.worker_thread.error.connect(self._on_error)
        self.worker_thread.conflict_resolution_needed.connect(
            self._on_conflict_resolution_needed
        )

        # 连接取消按钮
        self.progress_dialog.canceled.connect(self._on_cancel)

        # 显示进度对话框
        self.progress_dialog.show()

        # 启动线程
        self.worker_thread.start()

    def _on_progress(self, value: int):
        """处理进度更新"""
        self.transfer_model.set_progress(value)
        if self.progress_dialog:
            self.progress_dialog.setValue(value)

    def _on_progress_text_update(self, text: str):
        """处理进度文本更新"""
        self.transfer_model.set_progress_text(text)
        self._update_progress_dialog_text()

    def _on_speed_update(self, speed_text: str):
        """处理速度更新"""
        self.transfer_model.set_speed_text(speed_text)
        self._update_progress_dialog_text()

    def _update_progress_dialog_text(self):
        """更新进度对话框文本"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            progress_text = self.transfer_model.get_progress_text()
            speed_text = self.transfer_model.get_speed_text()
            if speed_text:
                self.progress_dialog.setLabelText(
                    f"{progress_text}\n传输速度: {speed_text}"
                )
            else:
                self.progress_dialog.setLabelText(progress_text)

    def _on_file_finished(self, message: str):
        """处理文件完成"""
        self.log_model.add_log(message, "✅")

    def _on_all_finished(self):
        """处理所有任务完成"""
        self.transfer_model.stop_transfer()

        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.log_model.add_log("所有传输任务已完成。", "🎉")
        QApplication.processEvents()  # 立即更新UI

        # 显示完成提示
        QMessageBox.information(
            None, "任务完成", "所有传输任务已成功完成。", QMessageBox.StandardButton.Ok
        )

        # 发射完成信号
        self.transfer_completed.emit()

        # 清理工作线程
        self.worker_thread = None

    def _on_error(self, error_message: str):
        """处理错误"""
        self.transfer_model.stop_transfer()

        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.close()

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

        if "cancelled" not in error_lower:
            QMessageBox.critical(
                None, title, friendly_message, QMessageBox.StandardButton.Ok
            )

        # 发射错误信号
        self.transfer_error.emit(friendly_message)

        # 清理工作线程
        self.worker_thread = None

    def _on_cancel(self):
        """处理取消操作"""
        if self.worker_thread:
            self.worker_thread.stop()

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
