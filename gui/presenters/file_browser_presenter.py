"""
文件浏览器Presenter类，连接文件模型和文件浏览器视图
"""

from typing import Dict, Any, List, Optional, Callable
import os

from PySide6.QtCore import QPoint
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QMenu, QMessageBox, QFileDialog, QInputDialog

from gui.models.connection_model import ConnectionModel
from gui.models.file_model import FileModel
from gui.models.share_model import RemoteShareModel
from gui.views.file_browser_view import FileBrowserView


class FileBrowserPresenter:
    """文件浏览器Presenter，连接文件模型和文件浏览器视图"""

    def __init__(
        self,
        file_model: FileModel,
        share_model: RemoteShareModel,
        connection_model: ConnectionModel,
        view: FileBrowserView,
    ):
        self.file_model = file_model
        self.share_model = share_model
        self.connection_model = connection_model
        self.view = view

        # 连接模型和视图
        self.file_model.on_files_changed(self._on_files_changed)
        self.share_model.on_shares_changed(self._on_shares_changed)
        self.share_model.on_path_changed(self._on_path_changed)

        self.view.share_selected.connect(self._on_share_selected)
        self.view.back_clicked.connect(self._on_back_clicked)
        self.view.upload_file_clicked.connect(self._on_upload_file_clicked)
        self.view.upload_folder_clicked.connect(self._on_upload_folder_clicked)
        self.view.download_clicked.connect(self._on_download_clicked)
        self.view.item_double_clicked.connect(self._on_item_double_clicked)
        self.view.files_dropped.connect(self._on_files_dropped)
        self.view.context_menu_requested.connect(self._on_context_menu_requested)

        # 回调函数
        self._on_upload_file_callback = None
        self._on_upload_folder_callback = None
        self._on_download_callback = None
        self._on_rename_callback = None
        self._on_delete_callback = None
        self._on_new_folder_callback = None

    def set_icons(
        self,
        back_icon: QIcon,
        upload_icon: QIcon,
        download_icon: QIcon,
        folder_icon: QIcon,
        file_icon: QIcon,
        upload_file_icon: QIcon = None,
        upload_folder_icon: QIcon = None,
    ):
        """设置图标"""
        self.view.set_icons(
            back_icon,
            upload_icon,
            download_icon,
            folder_icon,
            file_icon,
            upload_file_icon,
            upload_folder_icon,
        )

    def _on_files_changed(self):
        """处理文件列表变化"""
        self.view.update_files(self.file_model.get_files())
        self._update_download_button_state()

    def _on_shares_changed(self):
        """处理共享列表变化"""
        self.view.set_shares(self.share_model.get_share_names())
        self._update_upload_button_state()

    def _on_path_changed(self):
        """处理路径变化"""
        current_path = self.share_model.get_current_path()
        self.view.set_current_path(current_path)
        self.view.set_back_button_enabled(len(self.share_model.get_path_stack()) > 0)
        self.file_model.set_current_path(current_path)
        self._refresh_files()

    def _on_share_selected(self, share_name: str):
        """处理共享选择"""
        self.share_model.set_current_share(share_name)
        self._update_upload_button_state()

    def _on_back_clicked(self):
        """处理返回按钮点击"""
        self.share_model.pop_path()

    def _on_upload_file_clicked(self):
        """处理上传文件按钮点击"""
        if not self._check_upload_permission():
            return

        file_paths, _ = QFileDialog.getOpenFileNames(self.view, "选择要上传的文件", "")
        if not file_paths:
            return

        if self._on_upload_file_callback:
            self._on_upload_file_callback(
                file_paths,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
            )

    def _on_upload_folder_clicked(self):
        """处理上传文件夹按钮点击"""
        if not self._check_upload_permission():
            return

        folder_path = QFileDialog.getExistingDirectory(
            self.view, "选择要上传的文件夹", ""
        )
        if not folder_path:
            return

        if self._on_upload_folder_callback:
            self._on_upload_folder_callback(
                folder_path,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
            )

    def _on_download_clicked(self):
        """处理下载按钮点击"""
        if not self._check_download_permission():
            return

        # 获取选中或勾选的文件
        files_to_download = self._get_selected_files()
        if not files_to_download:
            QMessageBox.information(
                self.view,
                "提示",
                "请先勾选或选中要下载的文件/文件夹。",
                QMessageBox.StandardButton.Ok,
            )
            return

        save_dir = QFileDialog.getExistingDirectory(self.view, "选择保存下载内容的位置")
        if not save_dir:
            return

        if self._on_download_callback:
            self._on_download_callback(
                files_to_download,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
                save_dir,
            )

    def _on_item_double_clicked(self, row: int, col: int):
        """处理双击事件"""
        if col == 0:
            return

        file_info = self.file_model.get_selected_files([row])
        if not file_info:
            return

        file_info = file_info[0]
        if file_info["is_dir"]:
            self.share_model.push_path(file_info["name"])

    def _on_files_dropped(self, urls):
        """处理文件拖放"""
        if not self._check_upload_permission():
            return

        file_paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if not file_paths:
            return

        # 分类为文件和文件夹
        files = []
        folders = []

        for path in file_paths:
            if os.path.isdir(path):
                folders.append(path)
            elif os.path.isfile(path):
                files.append(path)

        # 处理上传
        if files and self._on_upload_file_callback:
            self._on_upload_file_callback(
                files,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
            )

        for folder in folders:
            if self._on_upload_folder_callback:
                self._on_upload_folder_callback(
                    folder,
                    self.share_model.get_current_share(),
                    self.share_model.get_current_path(),
                )

    def _on_context_menu_requested(self, pos: QPoint, selected_rows: List[int]):
        """处理右键菜单请求"""
        menu = QMenu()

        # 新建文件夹选项 (始终显示)
        new_folder_action = QAction("新建文件夹", menu)
        new_folder_action.setIcon(self.view.folder_icon)
        new_folder_action.triggered.connect(self._on_new_folder_clicked)
        menu.addAction(new_folder_action)
        menu.addSeparator()

        if selected_rows:
            # 下载选项
            if self._check_download_permission():
                download_action = QAction("下载选中项", menu)
                download_action.setIcon(self.view.download_icon)
                download_action.triggered.connect(self._on_download_clicked)
                menu.addAction(download_action)

            # 只有一个选中项时才显示重命名选项
            if len(selected_rows) == 1 and self.share_model.has_permission("rename"):
                rename_action = QAction("重命名", menu)
                rename_action.setIcon(
                    self.view.style().standardIcon(
                        self.view.style().StandardPixmap.SP_FileDialogDetailedView
                    )
                )
                rename_action.triggered.connect(
                    lambda: self._on_rename_clicked(selected_rows[0])
                )
                menu.addAction(rename_action)

            # 删除选项
            if self.share_model.has_permission("delete"):
                delete_action = QAction("删除选中项", menu)
                delete_action.setIcon(
                    self.view.style().standardIcon(
                        self.view.style().StandardPixmap.SP_TrashIcon
                    )
                )
                delete_action.triggered.connect(
                    lambda: self._on_delete_clicked(selected_rows)
                )
                menu.addAction(delete_action)

        menu.exec(pos)

    def _on_rename_clicked(self, row: int):
        """处理重命名操作"""
        file_info = self.file_model.get_selected_files([row])
        if not file_info:
            return

        file_info = file_info[0]
        old_name = file_info["name"]

        from PySide6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(
            self.view, "重命名", "请输入新名称:", text=old_name
        )

        if not ok or not new_name or new_name == old_name:
            return

        if self._on_rename_callback:
            self._on_rename_callback(
                old_name,
                new_name,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
            )

            # 延迟刷新文件列表
            from PySide6.QtCore import QTimer

            QTimer.singleShot(500, self._refresh_files)

    def _on_delete_clicked(self, rows: List[int]):
        """处理删除操作"""
        files_to_delete = self.file_model.get_selected_files(rows)
        if not files_to_delete:
            return

        # 确认删除
        msg = f"确定要删除选中的 {len(files_to_delete)} 个项目吗？此操作不可恢复。"
        reply = QMessageBox.question(
            self.view,
            "确认删除",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        if self._on_delete_callback:
            file_names = [file_info["name"] for file_info in files_to_delete]
            self._on_delete_callback(
                file_names,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
            )

            # 延迟刷新文件列表
            from PySide6.QtCore import QTimer

            QTimer.singleShot(500, self._refresh_files)

    def _refresh_files(self):
        """刷新文件列表"""
        if (
            not self.connection_model.get_active_peer_client()
            or not self.share_model.get_current_share()
        ):
            self.file_model.clear()
            return

        client = self.connection_model.get_active_peer_client()
        share_name = self.share_model.get_current_share()
        path = self.share_model.get_current_path()

        files = client.get_files(share_name, path)

        if files is not None:
            self.file_model.set_files(files)
        else:
            self.file_model.clear()

    def _check_upload_permission(self) -> bool:
        """检查是否有上传权限"""
        if not self.share_model.has_permission("upload"):
            QMessageBox.warning(
                self.view,
                "权限不足",
                "对方未授予上传权限。",
                QMessageBox.StandardButton.Ok,
            )
            return False
        return True

    def _check_download_permission(self) -> bool:
        """检查是否有下载权限"""
        if not self.share_model.has_permission("download"):
            QMessageBox.warning(
                self.view,
                "权限不足",
                "对方未授予下载权限。",
                QMessageBox.StandardButton.Ok,
            )
            return False
        return True

    def _update_upload_button_state(self):
        """更新上传按钮状态"""
        has_client = self.connection_model.get_active_peer_client() is not None
        has_share = self.share_model.get_current_share() is not None
        has_permission = (
            self.share_model.has_permission("upload") if has_share else False
        )

        enabled = has_client and has_share and has_permission

        self.view.set_upload_button_enabled(enabled)

    def _update_download_button_state(self):
        """更新下载按钮状态"""
        has_files = self.file_model.get_file_count() > 0
        has_permission = self.share_model.has_permission("download")
        self.view.set_download_button_enabled(has_files and has_permission)

    def _get_selected_files(self) -> List[Dict[str, Any]]:
        """获取用户选择的文件"""
        # 优先使用勾选的文件
        checked_rows = self.view.get_checked_rows()
        if checked_rows:
            return self.file_model.get_selected_files(checked_rows)

        # 其次使用选中的文件
        selected_rows = self.view.get_selected_rows()
        return self.file_model.get_selected_files(selected_rows)

    def on_upload_file(self, callback: Callable[[List[str], str, str], None]):
        """设置上传文件回调"""
        self._on_upload_file_callback = callback

    def on_upload_folder(self, callback: Callable[[str, str, str], None]):
        """设置上传文件夹回调"""
        self._on_upload_folder_callback = callback

    def on_download(
        self, callback: Callable[[List[Dict[str, Any]], str, str, str], None]
    ):
        """设置下载回调"""
        self._on_download_callback = callback

    def on_rename(self, callback: Callable[[str, str, str, str], None]):
        """设置重命名回调"""
        self._on_rename_callback = callback

    def on_delete(self, callback: Callable[[List[str], str, str], None]):
        """设置删除回调"""
        self._on_delete_callback = callback

    def _on_new_folder_clicked(self):
        """处理新建文件夹操作"""
        if not self._check_upload_permission():
            return

        new_name, ok = QInputDialog.getText(
            self.view, "新建文件夹", "请输入文件夹名称:"
        )
        if not ok or not new_name:
            return

        if self._on_new_folder_callback:
            self._on_new_folder_callback(
                new_name,
                self.share_model.get_current_share(),
                self.share_model.get_current_path(),
            )

    def on_new_folder(self, callback: Callable[[str, str, str], None]):
        """设置新建文件夹回调"""
        self._on_new_folder_callback = callback
