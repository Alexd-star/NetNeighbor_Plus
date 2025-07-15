"""
设置窗口，用于配置应用程序参数和共享文件夹
"""

import copy
import os
import toml

from typing import Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLineEdit,
    QCheckBox,
    QLabel,
    QListWidgetItem,
    QWidget,
    QFrame,
    QGroupBox,
)

from core.config_loader import CONFIG_PATH
from .app_controller import AppController


class SettingsWindow(QDialog):
    """
    设置窗口类, 允许用户修改应用配置。

    包括服务设置（设备名、端口）和共享文件夹管理（添加、移除、修改权限）。
    """

    def __init__(self, controller: AppController, parent: QWidget = None):
        """
        初始化设置窗口。

        Args:
            controller: 应用主控制器实例, 用于获取当前配置和状态。
            parent: 父窗口部件。
        """
        super().__init__(parent)
        self.controller = controller
        self.config_data_copy = copy.deepcopy(self.controller.running_config)
        self.normalize_permissions_on_load()
        # --- 【核心修正】使用 Union 替换 | 语法 ---
        self.current_selected_path: Union[str, None] = None

        self.setWindowTitle("设置中心")
        self.setMinimumSize(600, 400)
        self.setup_ui()
        self.load_config_to_ui()

    def normalize_permissions_on_load(self):
        """加载时规整共享文件夹的权限数据, 确保兼容性和一致性。"""
        if "shares" in self.config_data_copy:
            for share in self.config_data_copy["shares"]:
                if "permissions" not in share:
                    share["permissions"] = ["read", "download", "upload"]
                elif "read" not in share["permissions"]:
                    share["permissions"].append("read")

    def setup_ui(self):
        """创建并布局窗口中的所有UI组件。"""
        main_layout = QVBoxLayout(self)

        service_box = QGroupBox("服务设置")
        service_layout = QHBoxLayout(service_box)
        service_layout.addWidget(QLabel("<b>本机设备名:</b>"))
        self.device_name_edit = QLineEdit()
        service_layout.addWidget(self.device_name_edit)
        service_layout.addSpacing(20)
        service_layout.addWidget(QLabel("<b>端口:</b>"))
        self.port_edit = QLineEdit()
        self.port_edit.setFixedWidth(60)
        service_layout.addWidget(self.port_edit)
        main_layout.addWidget(service_box)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        share_management_box = QGroupBox("共享文件夹管理")
        share_layout = QHBoxLayout(share_management_box)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("<b>共享的文件夹:</b>"))
        self.share_list_widget = QListWidget()
        self.share_list_widget.itemClicked.connect(self.on_share_selected)
        left_layout.addWidget(self.share_list_widget)

        add_remove_layout = QHBoxLayout()
        self.add_button = QPushButton("添加共享")
        self.remove_button = QPushButton("移除选中")
        self.add_button.clicked.connect(self.add_share)
        self.remove_button.clicked.connect(self.remove_share)
        add_remove_layout.addWidget(self.add_button)
        add_remove_layout.addWidget(self.remove_button)
        left_layout.addLayout(add_remove_layout)
        share_layout.addWidget(left_widget, stretch=1)

        right_widget = QGroupBox("共享详情")
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("共享别名:"))
        self.share_name_edit = QLineEdit()
        self.share_name_edit.setPlaceholderText("例如：我的文档")
        right_layout.addWidget(self.share_name_edit)
        self.share_path_label = QLabel("路径: (不可修改)")
        right_layout.addWidget(self.share_path_label)

        permissions_group = QGroupBox("权限设置")
        permissions_layout = QVBoxLayout(permissions_group)
        self.allow_download_checkbox = QCheckBox("允许其他设备下载文件")
        self.allow_upload_checkbox = QCheckBox("允许其他设备上传文件")
        self.allow_delete_checkbox = QCheckBox("允许其他设备删除文件")
        self.allow_rename_checkbox = QCheckBox("允许其他设备重命名文件")
        permissions_layout.addWidget(self.allow_download_checkbox)
        permissions_layout.addWidget(self.allow_upload_checkbox)
        permissions_layout.addWidget(self.allow_delete_checkbox)
        permissions_layout.addWidget(self.allow_rename_checkbox)
        right_layout.addWidget(permissions_group)
        right_layout.addStretch()
        share_layout.addWidget(right_widget, stretch=1)

        main_layout.addWidget(share_management_box)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.save_button = QPushButton("保存并应用")
        self.cancel_button = QPushButton("取消")
        self.save_button.clicked.connect(self.save_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.share_name_edit.textChanged.connect(self.update_config_in_memory)
        self.allow_download_checkbox.stateChanged.connect(self.update_config_in_memory)
        self.allow_upload_checkbox.stateChanged.connect(self.update_config_in_memory)
        self.allow_delete_checkbox.stateChanged.connect(self.update_config_in_memory)
        self.allow_rename_checkbox.stateChanged.connect(self.update_config_in_memory)

        self._set_details_enabled(False)

    def _set_details_enabled(self, enabled: bool):
        """启用或禁用右侧的共享详情编辑控件。"""
        self.share_name_edit.setEnabled(enabled)
        self.allow_download_checkbox.setEnabled(enabled)
        self.allow_upload_checkbox.setEnabled(enabled)
        self.allow_delete_checkbox.setEnabled(enabled)
        self.allow_rename_checkbox.setEnabled(enabled)

    def load_config_to_ui(self):
        """将内存中的配置数据加载到UI界面上。"""
        service_conf = self.config_data_copy.get("service", {})
        self.device_name_edit.setText(service_conf.get("name", "auto"))
        self.port_edit.setText(str(service_conf.get("port", 8080)))

        self.device_name_edit.setToolTip("设备名更改需要重启应用才能生效。")
        if self.controller.port_override:
            self.port_edit.setEnabled(False)
            self.port_edit.setToolTip("当前端口由命令行参数覆盖, 无法在此修改。")
        else:
            self.port_edit.setEnabled(True)
            self.port_edit.setToolTip("端口更改需要重启应用才能生效。")

        self.share_list_widget.clear()
        self._clear_details()
        for share in self.config_data_copy.get("shares", []):
            item_text = share.get("name", os.path.basename(share.get("path")))
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, share.get("path"))
            self.share_list_widget.addItem(item)

    def _clear_details(self):
        """清空并禁用右侧共享详情区域。"""
        for widget in [
            self.share_name_edit,
            self.allow_download_checkbox,
            self.allow_upload_checkbox,
            self.allow_delete_checkbox,
            self.allow_rename_checkbox,
        ]:
            widget.blockSignals(True)

        self.share_name_edit.clear()
        self.share_path_label.setText("路径: (请在左侧选择一项)")
        self.allow_download_checkbox.setChecked(False)
        self.allow_upload_checkbox.setChecked(False)
        self.allow_delete_checkbox.setChecked(False)
        self.allow_rename_checkbox.setChecked(False)
        self._set_details_enabled(False)
        self.current_selected_path = None

        for widget in [
            self.share_name_edit,
            self.allow_download_checkbox,
            self.allow_upload_checkbox,
            self.allow_delete_checkbox,
            self.allow_rename_checkbox,
        ]:
            widget.blockSignals(False)

    def on_share_selected(self, item: QListWidgetItem):
        """处理共享项被选中的事件，更新右侧详情区域。"""
        path = item.data(Qt.ItemDataRole.UserRole)
        self.current_selected_path = path

        # 查找对应的共享配置
        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == path:
                # 阻止信号，避免在设置值时触发更新
                for widget in [
                    self.share_name_edit,
                    self.allow_download_checkbox,
                    self.allow_upload_checkbox,
                    self.allow_delete_checkbox,
                    self.allow_rename_checkbox,
                ]:
                    widget.blockSignals(True)

                # 更新UI
                self.share_name_edit.setText(share.get("name", ""))
                self.share_path_label.setText(f"路径: {path}")

                permissions = share.get("permissions", ["read"])
                self.allow_download_checkbox.setChecked("download" in permissions)
                self.allow_upload_checkbox.setChecked("upload" in permissions)
                self.allow_delete_checkbox.setChecked("delete" in permissions)
                self.allow_rename_checkbox.setChecked("rename" in permissions)

                # 恢复信号
                for widget in [
                    self.share_name_edit,
                    self.allow_download_checkbox,
                    self.allow_upload_checkbox,
                    self.allow_delete_checkbox,
                    self.allow_rename_checkbox,
                ]:
                    widget.blockSignals(False)

                # 启用详情区域
                self._set_details_enabled(True)
                break

    def update_config_in_memory(self):
        """当UI控件值改变时，更新内存中的配置。"""
        if not self.current_selected_path:
            return

        # 查找当前选中的共享项
        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == self.current_selected_path:
                # 更新共享名称
                share["name"] = self.share_name_edit.text()

                # 更新权限
                permissions = ["read"]  # 读取权限始终保留
                if self.allow_download_checkbox.isChecked():
                    permissions.append("download")
                if self.allow_upload_checkbox.isChecked():
                    permissions.append("upload")
                if self.allow_delete_checkbox.isChecked():
                    permissions.append("delete")
                if self.allow_rename_checkbox.isChecked():
                    permissions.append("rename")

                share["permissions"] = permissions

                # 更新列表项显示
                for i in range(self.share_list_widget.count()):
                    item = self.share_list_widget.item(i)
                    if (
                        item
                        and item.data(Qt.ItemDataRole.UserRole)
                        == self.current_selected_path
                    ):
                        item.setText(share["name"])
                        break

                break

    def add_share(self):
        """添加新的共享文件夹。"""
        folder_path = QFileDialog.getExistingDirectory(
            self, "选择要共享的文件夹", os.path.expanduser("~")
        )

        if not folder_path:
            return

        # 检查是否已存在相同路径的共享
        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == folder_path:
                QMessageBox.warning(
                    self, "添加失败", f"文件夹 '{folder_path}' 已经在共享列表中。"
                )
                return

        # 创建新的共享配置
        new_share = {
            "name": os.path.basename(folder_path),
            "path": folder_path,
            "permissions": ["read", "download", "upload"],
        }

        # 添加到配置
        if "shares" not in self.config_data_copy:
            self.config_data_copy["shares"] = []
        self.config_data_copy["shares"].append(new_share)

        # 添加到UI
        item = QListWidgetItem(new_share["name"])
        item.setData(Qt.ItemDataRole.UserRole, folder_path)
        self.share_list_widget.addItem(item)

    def remove_share(self):
        """移除选中的共享文件夹。"""
        current_item = self.share_list_widget.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择要移除的共享项。")
            return

        path = current_item.data(Qt.ItemDataRole.UserRole)

        # 从配置中移除
        self.config_data_copy["shares"] = [
            share
            for share in self.config_data_copy.get("shares", [])
            if share.get("path") != path
        ]

        # 从UI中移除
        self.share_list_widget.takeItem(self.share_list_widget.row(current_item))

        # 清空详情区域
        self._clear_details()

    def save_and_accept(self):
        """保存配置并关闭窗口。"""
        try:
            # 更新服务配置
            if "service" not in self.config_data_copy:
                self.config_data_copy["service"] = {}

            self.config_data_copy["service"]["name"] = self.device_name_edit.text()

            # 仅当端口未被命令行参数覆盖时才更新端口
            if not self.controller.port_override:
                try:
                    port = int(self.port_edit.text())
                    if port < 1 or port > 65535:
                        raise ValueError("端口必须在1-65535范围内")
                    self.config_data_copy["service"]["port"] = port
                except ValueError as e:
                    QMessageBox.warning(self, "输入错误", f"端口设置无效: {e}")
                    return

            # 保存配置到文件
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                toml.dump(self.config_data_copy, f)

            # 更新控制器中的运行时配置
            self.controller.running_config = self.config_data_copy
            # reload_shares 方法在 ShareModel 中，不在 AppController 中
            # 这里不需要调用，因为配置已经更新，ShareModel 会自动重新加载

            # 提示用户某些设置需要重启才能生效
            QMessageBox.information(
                self,
                "设置已保存",
                "设置已保存。\n\n注意：设备名和端口更改需要重启应用才能生效。",
            )

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存设置时出错: {e}")
