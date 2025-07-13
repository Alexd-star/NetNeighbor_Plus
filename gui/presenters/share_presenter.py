"""
共享文件夹列表Presenter类，连接共享文件夹模型和视图
"""

from typing import Dict, Any, Optional, Callable

from PySide6.QtCore import QPoint
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QMenu, QMessageBox

from gui.models.share_model import ShareModel
from gui.views.share_list_view import ShareListView


class SharePresenter:
    """共享文件夹列表Presenter，连接共享文件夹模型和视图"""

    def __init__(self, model: ShareModel, view: ShareListView):
        self.model = model
        self.view = view
        self.folder_icon = None

        # 连接模型和视图
        self.model.on_shares_changed(self._on_shares_changed)
        self.view.manage_shares_clicked.connect(self._on_manage_shares_clicked)
        self.view.share_context_menu_requested.connect(
            self._on_share_context_menu_requested
        )

        # 回调函数
        self._on_manage_shares_callback = None
        self._on_permission_change_callback = None
        self._on_remove_share_callback = None

    def set_folder_icon(self, icon: QIcon):
        """设置文件夹图标"""
        self.folder_icon = icon
        self._update_view()

    def _on_shares_changed(self):
        """处理共享文件夹列表变化"""
        self._update_view()

    def _update_view(self):
        """更新视图"""
        if self.folder_icon:
            self.view.update_shares(self.model.get_shares(), self.folder_icon)

    def _on_manage_shares_clicked(self):
        """处理管理共享按钮点击事件"""
        if self._on_manage_shares_callback:
            self._on_manage_shares_callback()

    def _on_share_context_menu_requested(self, share_name: str, pos: QPoint):
        """处理共享文件夹右键菜单请求"""
        share = self.model.get_share_by_name(share_name)
        if not share:
            return

        menu = QMenu()

        # 权限子菜单
        permissions_menu = menu.addMenu("设置权限")
        current_perms = share.get("permissions", [])

        # 下载权限
        dl_action = QAction("可下载", menu, checkable=True)
        dl_action.setChecked("download" in current_perms)
        dl_action.toggled.connect(
            lambda checked: self._handle_permission_change(
                share_name, "download", checked
            )
        )
        permissions_menu.addAction(dl_action)

        # 上传权限
        ul_action = QAction("可上传", menu, checkable=True)
        ul_action.setChecked("upload" in current_perms)
        ul_action.toggled.connect(
            lambda checked: self._handle_permission_change(
                share_name, "upload", checked
            )
        )
        permissions_menu.addAction(ul_action)

        # 删除权限
        del_action = QAction("可删除", menu, checkable=True)
        del_action.setChecked("delete" in current_perms)
        del_action.toggled.connect(
            lambda checked: self._handle_permission_change(
                share_name, "delete", checked
            )
        )
        permissions_menu.addAction(del_action)

        # 重命名权限
        rename_action = QAction("可重命名", menu, checkable=True)
        rename_action.setChecked("rename" in current_perms)
        rename_action.toggled.connect(
            lambda checked: self._handle_permission_change(
                share_name, "rename", checked
            )
        )
        permissions_menu.addAction(rename_action)

        menu.addSeparator()

        # 移除共享
        remove_action = QAction("移除此共享", menu)
        remove_action.triggered.connect(lambda: self._handle_remove_share(share_name))
        menu.addAction(remove_action)

        menu.exec(pos)

    def _handle_permission_change(self, share_name: str, perm: str, checked: bool):
        """处理权限变更"""
        if self._on_permission_change_callback:
            self._on_permission_change_callback(share_name, perm, checked)

    def _handle_remove_share(self, share_name: str):
        """处理移除共享"""
        reply = QMessageBox.question(
            self.view,
            "确认移除",
            f"确定要停止共享 '{share_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes and self._on_remove_share_callback:
            self._on_remove_share_callback(share_name)

    def on_manage_shares(self, callback: Callable[[], None]):
        """设置管理共享回调"""
        self._on_manage_shares_callback = callback

    def on_permission_change(self, callback: Callable[[str, str, bool], None]):
        """设置权限变更回调"""
        self._on_permission_change_callback = callback

    def on_remove_share(self, callback: Callable[[str], None]):
        """设置移除共享回调"""
        self._on_remove_share_callback = callback
