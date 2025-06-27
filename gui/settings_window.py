# 文件: gui/settings_window.py (修复)
import os
import toml
import copy
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
                               QFileDialog, QMessageBox, QLineEdit, QCheckBox, QLabel, QListWidgetItem,
                               QWidget, QFrame)
from PySide6.QtCore import Qt
from core.config_loader import CONFIG_PATH
from .app_controller import AppController


class SettingsWindow(QDialog):
    # 【修复2】为 __init__ 方法添加 self 参数
    def __init__(self, controller: AppController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.config_data_copy = copy.deepcopy(self.controller.running_config)
        self.current_selected_path = None
        self.setWindowTitle("设置中心")
        self.setMinimumSize(600, 400)
        self.setup_ui()
        self.load_config_to_ui()

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

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("<b>共享详情:</b>"))
        right_layout.addWidget(QLabel("别名:"))
        self.share_name_edit = QLineEdit()
        self.share_name_edit.setPlaceholderText("共享别名 (例如：我的文档)")
        right_layout.addWidget(self.share_name_edit)
        self.share_path_label = QLabel("路径: (不可修改)")
        right_layout.addWidget(self.share_path_label)
        self.allow_upload_checkbox = QCheckBox("允许其他设备上传/写入到此共享")
        right_layout.addWidget(self.allow_upload_checkbox)
        right_layout.addStretch()
        share_layout.addWidget(right_widget, stretch=1)

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
        self.allow_upload_checkbox.stateChanged.connect(self.update_config_in_memory)

        self._set_details_enabled(False)

    def _set_details_enabled(self, enabled):
        self.share_name_edit.setEnabled(enabled)
        self.allow_upload_checkbox.setEnabled(enabled)

    def load_config_to_ui(self):
        # 显示 controller 中正在运行的配置值
        device_name_full = self.controller.device_name
        device_name_base = device_name_full.split(f'-{self.controller.port}')[
            0] if self.controller.port_override else device_name_full
        self.device_name_edit.setText(device_name_base)
        self.port_edit.setText(str(self.controller.port))
        self.port_edit.setToolTip("端口更改需要重启应用才能生效。")
        self.device_name_edit.setToolTip("设备名更改需要重启应用才能生效。")

        # 加载共享设置
        self.share_list_widget.clear()
        self._clear_details()
        for share in self.config_data_copy.get("shares", []):
            item = QListWidgetItem(share.get("name", os.path.basename(share.get("path"))))
            item.setData(Qt.UserRole, share.get("path"))
            self.share_list_widget.addItem(item)

    def _clear_details(self):
        self.share_name_edit.clear()
        self.share_path_label.setText("路径: (请在左侧选择一项)")
        self.allow_upload_checkbox.setChecked(False)
        self._set_details_enabled(False)
        self.current_selected_path = None

    def on_share_selected(self, item: QListWidgetItem):
        self.current_selected_path = item.data(Qt.UserRole)
        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == self.current_selected_path:
                self.share_name_edit.setText(share.get("name", ""))
                self.share_path_label.setText(f"路径: {self.current_selected_path}")
                self.allow_upload_checkbox.setChecked("write" in share.get("permissions", []))
                self._set_details_enabled(True)
                break

    def update_config_in_memory(self):
        if not self.current_selected_path: return
        for share in self.config_data_copy.get("shares", []):
            if share.get("path") == self.current_selected_path:
                share["name"] = self.share_name_edit.text()
                permissions = ["read"]
                if self.allow_upload_checkbox.isChecked(): permissions.append("write")
                share["permissions"] = list(set(permissions))
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

        new_share = {"name": os.path.basename(path), "path": path, "permissions": ["read"]}
        if "shares" not in self.config_data_copy: self.config_data_copy["shares"] = []
        self.config_data_copy["shares"].append(new_share)
        self.load_config_to_ui()
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
        service_config = self.config_data_copy.setdefault("service", {})
        service_config["name"] = self.device_name_edit.text()
        try:
            service_config["port"] = int(self.port_edit.text())
        except ValueError:
            QMessageBox.critical(self, "错误", "端口必须是一个有效的数字！")
            return

        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(self.config_data_copy, f)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")