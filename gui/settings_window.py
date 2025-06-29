# 文件: gui/settings_window.py (修复)
import os
import toml
import copy
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
                               QFileDialog, QMessageBox, QLineEdit, QCheckBox, QLabel, QListWidgetItem,
                               QWidget, QFrame, QGroupBox)
from PySide6.QtCore import Qt
from core.config_loader import CONFIG_PATH
from .app_controller import AppController


class SettingsWindow(QDialog):
    def __init__(self, controller: AppController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.config_data_copy = copy.deepcopy(self.controller.running_config)

        # --- 【核心修复】修改权限正常化逻辑 ---
        self.normalize_permissions_on_load()

        self.current_selected_path = None
        self.setWindowTitle("设置中心")
        self.setMinimumSize(600, 400)
        self.setup_ui()
        self.load_config_to_ui()

    def normalize_permissions_on_load(self):
        """
        【修复】加载时规整权限数据。
        只确保每个共享都存在 permissions 键，如果不存在，则赋予默认权限。
        这可以兼容非常旧的、连 permissions 键都没有的配置。
        """
        if "shares" in self.config_data_copy:
            for share in self.config_data_copy["shares"]:
                # 如果一个共享完全没有 'permissions' 键，说明它是最旧的格式，
                # 或者数据已损坏，此时我们为其赋予所有默认权限。
                if "permissions" not in share:
                    share["permissions"] = ["read", "download", "upload"]
                # 确保 'read' 基础权限总是存在
                elif "read" not in share["permissions"]:
                    share["permissions"].append("read")

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        service_box = QWidget()
        service_layout = QHBoxLayout(service_box)
        service_layout.addWidget(QLabel("<b>本机设备名:</b>"))
        self.device_name_edit = QLineEdit()
        service_layout.addWidget(self.device_name_edit)
        service_layout.addWidget(QLabel("<b>端口:</b>"))
        self.port_edit = QLineEdit()
        self.port_edit.setFixedWidth(60)
        service_layout.addWidget(self.port_edit)
        main_layout.addWidget(service_box)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)

        share_layout = QHBoxLayout()
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

        # --- 【UI增强】重构右侧共享详情区域 ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("<b>共享详情:</b>"))

        right_layout.addWidget(QLabel("共享别名:"))
        self.share_name_edit = QLineEdit()
        self.share_name_edit.setPlaceholderText("共享别名 (例如：我的文档)")
        right_layout.addWidget(self.share_name_edit)

        self.share_path_label = QLabel("路径: (不可修改)")
        right_layout.addWidget(self.share_path_label)

        # 使用 GroupBox 美化权限设置
        permissions_group = QGroupBox("权限设置")
        permissions_layout = QVBoxLayout(permissions_group)

        self.allow_download_checkbox = QCheckBox("允许其他设备下载文件")
        self.allow_upload_checkbox = QCheckBox("允许其他设备上传文件")

        permissions_layout.addWidget(self.allow_download_checkbox)
        permissions_layout.addWidget(self.allow_upload_checkbox)

        right_layout.addWidget(permissions_group)
        right_layout.addStretch()
        share_layout.addWidget(right_widget, stretch=1)
        # ------------------------------------

        main_layout.addLayout(share_layout)

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
        # 将两个复选框的信号都连接到更新函数
        self.allow_download_checkbox.stateChanged.connect(self.update_config_in_memory)
        self.allow_upload_checkbox.stateChanged.connect(self.update_config_in_memory)

        self._set_details_enabled(False)

    def _set_details_enabled(self, enabled):
        self.share_name_edit.setEnabled(enabled)
        self.allow_download_checkbox.setEnabled(enabled)
        self.allow_upload_checkbox.setEnabled(enabled)

    def load_config_to_ui(self):
        device_name_base = self.controller.device_name
        if self.controller.port_override:
            device_name_base = device_name_base.replace(f'-{self.controller.port}', '')
        self.device_name_edit.setText(device_name_base)

        self.port_edit.setText(str(self.controller.port))
        # 如果端口被命令行覆盖，则禁用编辑，防止用户误操作
        self.port_edit.setEnabled(not self.controller.port_override)
        self.port_edit.setToolTip("端口更改需要重启应用才能生效。")
        self.device_name_edit.setToolTip("设备名更改需要重启应用才能生效。")

        self.share_list_widget.clear()
        self._clear_details()
        for share in self.config_data_copy.get("shares", []):
            item = QListWidgetItem(share.get("name", os.path.basename(share.get("path"))))
            item.setData(Qt.UserRole, share.get("path"))
            self.share_list_widget.addItem(item)

    def _clear_details(self):
        # 阻断信号，防止在清空UI时意外触发更新函数
        self.share_name_edit.blockSignals(True)
        self.allow_download_checkbox.blockSignals(True)
        self.allow_upload_checkbox.blockSignals(True)

        self.share_name_edit.clear()
        self.share_path_label.setText("路径: (请在左侧选择一项)")
        self.allow_download_checkbox.setChecked(False)
        self.allow_upload_checkbox.setChecked(False)
        self._set_details_enabled(False)
        self.current_selected_path = None

        # 恢复信号
        self.share_name_edit.blockSignals(False)
        self.allow_download_checkbox.blockSignals(False)
        self.allow_upload_checkbox.blockSignals(False)

    def on_share_selected(self, item: QListWidgetItem):
        self.current_selected_path = item.data(Qt.UserRole)
        share_found = next(
            (s for s in self.config_data_copy.get("shares", []) if s.get("path") == self.current_selected_path), None)

        if share_found:
            # 阻断信号，避免在设置UI时触发更新
            self.share_name_edit.blockSignals(True)
            self.allow_download_checkbox.blockSignals(True)
            self.allow_upload_checkbox.blockSignals(True)

            self.share_name_edit.setText(share_found.get("name", ""))
            self.share_path_label.setText(f"路径: {self.current_selected_path}")

            # ---【核心修复】直接根据配置文件的真实状态设置勾选 ---
            permissions = share_found.get("permissions", [])
            self.allow_download_checkbox.setChecked("download" in permissions)
            self.allow_upload_checkbox.setChecked("upload" in permissions)
            self._set_details_enabled(True)

            # 恢复信号
            self.share_name_edit.blockSignals(False)
            self.allow_download_checkbox.blockSignals(False)
            self.allow_upload_checkbox.blockSignals(False)

    def update_config_in_memory(self):
        if not self.current_selected_path: return

        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == self.current_selected_path:
                share["name"] = self.share_name_edit.text()

                # ---【核心修复】根据复选框状态精确构建权限列表 ---
                permissions = ["read"]  # 浏览权限是基础，始终需要
                if self.allow_download_checkbox.isChecked():
                    permissions.append("download")
                if self.allow_upload_checkbox.isChecked():
                    permissions.append("upload")

                share["permissions"] = list(set(permissions))  # 去重以防万一

                # 更新左侧列表的显示名称
                for i in range(self.share_list_widget.count()):
                    item = self.share_list_widget.item(i)
                    if item.data(Qt.UserRole) == self.current_selected_path:
                        item.setText(share["name"])
                        break
                break

    def add_share(self):
        path = QFileDialog.getExistingDirectory(self, "选择要共享的文件夹", os.path.expanduser("~"))
        if not path: return

        path = os.path.normpath(path)
        if any(s['path'] == path for s in self.config_data_copy.get("shares", [])):
            QMessageBox.warning(self, "错误", "这个文件夹已经被共享了。")
            return

        # --- 【需求实现】新添加的共享默认拥有所有权限 ---
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
        current_item = self.share_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在左侧选择一个要移除的共享。")
            return
        path_to_remove = current_item.data(Qt.UserRole)
        self.config_data_copy["shares"] = [s for s in self.config_data_copy["shares"] if s["path"] != path_to_remove]
        self.load_config_to_ui()

    def save_and_accept(self):
        # 3. 【核心修复】保存时，不写入被命令行覆盖的端口，防止污染配置文件
        service_config = self.config_data_copy.setdefault("service", {})
        service_config["name"] = self.device_name_edit.text()

        # 只有在端口未被命令行覆盖时，才允许从UI保存端口号
        if not self.controller.port_override:
            try:
                service_config["port"] = int(self.port_edit.text())
            except (ValueError, KeyError):
                QMessageBox.critical(self, "错误", "端口必须是一个有效的数字！")
                return

        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(self.config_data_copy, f)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")