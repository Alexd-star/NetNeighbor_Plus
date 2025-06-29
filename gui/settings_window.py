# 文件: gui/settings_window.py
# 描述: 提供应用设置窗口，用于修改设备名、端口和共享文件夹。

import os
import toml
import copy
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QFileDialog, QMessageBox, QLineEdit, QCheckBox, QLabel,
    QListWidgetItem, QWidget, QFrame, QGroupBox
)
from PySide6.QtCore import Qt

from core.config_loader import CONFIG_PATH
from .app_controller import AppController


class SettingsWindow(QDialog):
    """
    设置窗口类，允许用户修改应用配置。

    包括服务设置（设备名、端口）和共享文件夹管理（添加、移除、修改权限）。
    """

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None):
        """
        初始化设置窗口。

        Args:
            controller: 应用主控制器实例，用于获取当前配置和状态。
            parent: 父窗口部件。
        """
        super().__init__(parent)
        self.controller = controller
        # 创建配置的深拷贝，以便在不影响正在运行的服务的情况下进行修改
        self.config_data_copy = copy.deepcopy(self.controller.running_config)
        self.normalize_permissions_on_load()
        self.current_selected_path: Optional[str] = None

        self.setWindowTitle("设置中心")
        self.setMinimumSize(600, 400)
        self.setup_ui()
        self.load_config_to_ui()

    def normalize_permissions_on_load(self):
        """
        加载时规整共享文件夹的权限数据。

        确保每个共享项都包含一个 'permissions' 键。
        如果不存在，则赋予默认的完全权限，以兼容旧版配置。
        同时确保基础的 'read' 权限始终存在。
        """
        if "shares" in self.config_data_copy:
            for share in self.config_data_copy["shares"]:
                if "permissions" not in share:
                    share["permissions"] = ["read", "download", "upload"]
                elif "read" not in share["permissions"]:
                    share["permissions"].append("read")

    def setup_ui(self):
        """创建并布局窗口中的所有UI组件。"""
        main_layout = QVBoxLayout(self)

        # 服务设置区域
        service_box = QGroupBox("服务设置")
        service_layout = QHBoxLayout(service_box)
        service_layout.addWidget(QLabel("<b>本机设备名:</b>"))
        self.device_name_edit = QLineEdit()
        service_layout.addWidget(self.device_name_edit)
        service_layout.addWidget(QLabel("<b>端口:</b>"))
        self.port_edit = QLineEdit()
        self.port_edit.setFixedWidth(60)
        service_layout.addWidget(self.port_edit)
        main_layout.addWidget(service_box)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        # 共享管理区域
        share_management_box = QGroupBox("共享文件夹管理")
        share_layout = QHBoxLayout(share_management_box)

        # 左侧：共享列表和操作按钮
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
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

        # 右侧：共享详情
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
        permissions_layout.addWidget(self.allow_download_checkbox)
        permissions_layout.addWidget(self.allow_upload_checkbox)
        right_layout.addWidget(permissions_group)
        right_layout.addStretch()
        share_layout.addWidget(right_widget, stretch=1)

        main_layout.addWidget(share_management_box)

        # 底部保存/取消按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.save_button = QPushButton("保存并应用")
        self.cancel_button = QPushButton("取消")
        self.save_button.clicked.connect(self.save_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        # 连接信号到槽函数
        self.share_name_edit.textChanged.connect(self.update_config_in_memory)
        self.allow_download_checkbox.stateChanged.connect(
            self.update_config_in_memory
        )
        self.allow_upload_checkbox.stateChanged.connect(
            self.update_config_in_memory
        )

        self._set_details_enabled(False)

    def _set_details_enabled(self, enabled: bool):
        """启用或禁用右侧的共享详情编辑控件。"""
        self.share_name_edit.setEnabled(enabled)
        self.allow_download_checkbox.setEnabled(enabled)
        self.allow_upload_checkbox.setEnabled(enabled)

    def load_config_to_ui(self):
        """将内存中的配置数据加载到UI界面上。"""
        device_name_base = self.controller.device_name
        if self.controller.port_override:
            device_name_base = device_name_base.replace(
                f'-{self.controller.port}', ''
            )
        self.device_name_edit.setText(device_name_base)
        self.device_name_edit.setToolTip("设备名更改需要重启应用才能生效。")

        self.port_edit.setText(str(self.controller.port))
        if self.controller.port_override:
            self.port_edit.setEnabled(False)
            self.port_edit.setToolTip(
                "当前端口由命令行参数覆盖，无法在此修改。"
            )
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
        # 阻断信号，防止在清空UI时意外触发更新函数
        for widget in [self.share_name_edit, self.allow_download_checkbox,
                       self.allow_upload_checkbox]:
            widget.blockSignals(True)

        self.share_name_edit.clear()
        self.share_path_label.setText("路径: (请在左侧选择一项)")
        self.allow_download_checkbox.setChecked(False)
        self.allow_upload_checkbox.setChecked(False)
        self._set_details_enabled(False)
        self.current_selected_path = None

        for widget in [self.share_name_edit, self.allow_download_checkbox,
                       self.allow_upload_checkbox]:
            widget.blockSignals(False)

    def on_share_selected(self, item: QListWidgetItem):
        """当用户在左侧列表中选择一个共享项时，更新右侧详情。"""
        self.current_selected_path = item.data(Qt.ItemDataRole.UserRole)
        share_found = next(
            (s for s in self.config_data_copy.get("shares", [])
             if s.get("path") == self.current_selected_path),
            None
        )

        if share_found:
            for widget in [self.share_name_edit, self.allow_download_checkbox,
                           self.allow_upload_checkbox]:
                widget.blockSignals(True)

            self.share_name_edit.setText(share_found.get("name", ""))
            self.share_path_label.setText(f"路径: {self.current_selected_path}")
            permissions = share_found.get("permissions", [])
            self.allow_download_checkbox.setChecked("download" in permissions)
            self.allow_upload_checkbox.setChecked("upload" in permissions)
            self._set_details_enabled(True)

            for widget in [self.share_name_edit, self.allow_download_checkbox,
                           self.allow_upload_checkbox]:
                widget.blockSignals(False)

    def update_config_in_memory(self):
        """当用户修改共享详情时，实时更新内存中的配置副本。"""
        if not self.current_selected_path:
            return

        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == self.current_selected_path:
                share["name"] = self.share_name_edit.text()
                permissions = ["read"]  # 浏览是基础权限
                if self.allow_download_checkbox.isChecked():
                    permissions.append("download")
                if self.allow_upload_checkbox.isChecked():
                    permissions.append("upload")
                share["permissions"] = list(set(permissions))

                # 更新左侧列表的显示名称
                for i in range(self.share_list_widget.count()):
                    item = self.share_list_widget.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == self.current_selected_path:
                        item.setText(share["name"])
                        break
                break

    def add_share(self):
        """弹出一个文件对话框，让用户选择并添加一个新的共享文件夹。"""
        path = QFileDialog.getExistingDirectory(
            self, "选择要共享的文件夹", os.path.expanduser("~")
        )
        if not path:
            return

        path = os.path.normpath(path)
        if any(s['path'] == path for s in self.config_data_copy.get("shares", [])):
            QMessageBox.warning(self, "错误", "这个文件夹已经被共享了。")
            return

        new_share = {
            "name": os.path.basename(path),
            "path": path,
            "permissions": ["read", "download", "upload"]
        }
        if "shares" not in self.config_data_copy:
            self.config_data_copy["shares"] = []

        self.config_data_copy["shares"].append(new_share)
        self.load_config_to_ui()
        # 自动选中新添加的项
        self.share_list_widget.setCurrentRow(self.share_list_widget.count() - 1)
        self.on_share_selected(self.share_list_widget.currentItem())

    def remove_share(self):
        """移除当前在左侧列表中选中的共享文件夹。"""
        current_item = self.share_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在左侧选择一个要移除的共享。")
            return

        path_to_remove = current_item.data(Qt.ItemDataRole.UserRole)
        self.config_data_copy["shares"] = [
            s for s in self.config_data_copy["shares"]
            if s["path"] != path_to_remove
        ]
        self.load_config_to_ui()

    def save_and_accept(self):
        """校验用户输入，保存配置到文件，并关闭窗口。"""
        service_config = self.config_data_copy.setdefault("service", {})
        service_config["name"] = self.device_name_edit.text()

        # 只有在端口未被命令行覆盖时，才保存端口号
        if not self.controller.port_override:
            try:
                port_val = int(self.port_edit.text())
                if not (1024 <= port_val <= 65535):
                    QMessageBox.critical(self, "错误", "端口号必须在 1024 和 65535 之间！")
                    return
                service_config["port"] = port_val
            except (ValueError, KeyError):
                QMessageBox.critical(self, "错误", "端口必须是一个有效的数字！")
                return

        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(self.config_data_copy, f)
            self.accept()  # 关闭对话框并返回 QDialog.Accepted
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")