import os
import toml
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
                               QFileDialog, QMessageBox, QLineEdit, QCheckBox, QLabel, QListWidgetItem)
from PySide6.QtCore import Qt
from typing import Dict, Any


class SettingsWindow(QDialog):
    """
    一个用于管理共享文件夹和应用设置的对话框窗口。
    """

    def __init__(self, config_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置中心")
        self.setMinimumSize(600, 400)

        # 将主窗口的配置数据通过深拷贝传递进来，防止取消时意外修改
        import copy
        self.config_data = copy.deepcopy(config_data)

        # 初始化UI
        self.setup_ui()
        # 加载当前配置到UI
        self.load_config_to_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # --- 左侧：共享文件夹列表 ---
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_layout.addWidget(QLabel("共享的文件夹:"))
        self.share_list_widget = QListWidget()
        self.share_list_widget.itemClicked.connect(self.on_share_selected)
        left_panel_layout.addWidget(self.share_list_widget)

        add_remove_layout = QHBoxLayout()
        self.add_button = QPushButton("[+] 添加共享")
        self.remove_button = QPushButton("[-] 移除选中")
        self.add_button.clicked.connect(self.add_share)
        self.remove_button.clicked.connect(self.remove_share)
        add_remove_layout.addWidget(self.add_button)
        add_remove_layout.addWidget(self.remove_button)
        left_panel_layout.addLayout(add_remove_layout)

        main_layout.addWidget(left_panel_widget)

        # --- 右侧：选中项的详细设置 ---
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        right_panel_layout.addWidget(QLabel("共享详情:"))
        self.share_name_edit = QLineEdit()
        self.share_name_edit.setPlaceholderText("共享别名 (例如：我的文档)")
        self.share_path_label = QLabel("路径: (不可修改)")
        self.allow_upload_checkbox = QCheckBox("允许上传/写入到此共享")

        # 失能控件，直到用户选中一项
        self.share_name_edit.setEnabled(False)
        self.allow_upload_checkbox.setEnabled(False)

        # 将控件添加到右侧布局
        right_panel_layout.addWidget(QLabel("别名:"))
        right_panel_layout.addWidget(self.share_name_edit)
        right_panel_layout.addWidget(self.share_path_label)
        right_panel_layout.addWidget(self.allow_upload_checkbox)
        right_panel_layout.addStretch()  # 添加一个伸缩项，让控件都靠上

        main_layout.addWidget(right_panel_widget)

        # --- 底部：保存和取消按钮 ---
        # 我们需要在主布局之外创建按钮布局，以确保它总在底部
        # 所以我们需要一个顶层的垂直布局
        top_level_layout = QVBoxLayout(self)
        top_level_layout.addLayout(main_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()  # 让按钮靠右
        self.save_button = QPushButton("保存并重启生效")
        self.cancel_button = QPushButton("取消")
        self.save_button.clicked.connect(self.save_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        top_level_layout.addLayout(button_layout)

    def load_config_to_ui(self):
        """将传入的配置数据加载到UI组件中"""
        self.share_list_widget.clear()
        self.share_name_edit.clear()
        self.share_path_label.setText("路径: (请在左侧选择一项)")
        self.allow_upload_checkbox.setChecked(False)
        self.share_name_edit.setEnabled(False)
        self.allow_upload_checkbox.setEnabled(False)

        shares = self.config_data.get("shares", [])
        for share in shares:
            item = QListWidgetItem(share.get("name", share.get("path")))
            item.setData(Qt.UserRole, share.get("path"))
            self.share_list_widget.addItem(item)

    def on_share_selected(self, item: QListWidgetItem):
        """当用户点击左侧列表中的一项时，在右侧显示其详情"""
        self.save_current_details()  # 先保存上一项的修改

        path = item.data(Qt.UserRole)
        for share in self.config_data.get("shares", []):
            if share.get("path") == path:
                self.share_name_edit.setText(share.get("name", ""))
                self.share_path_label.setText(f"路径: {path}")
                allow_write = "write" in share.get("permissions", [])
                self.allow_upload_checkbox.setChecked(allow_write)
                self.share_name_edit.setEnabled(True)
                self.allow_upload_checkbox.setEnabled(True)
                break

    def add_share(self):
        path = QFileDialog.getExistingDirectory(self, "选择要共享的文件夹")
        if not path: return

        if any(s['path'] == path for s in self.config_data.get("shares", [])):
            QMessageBox.warning(self, "错误", "这个文件夹已经被共享了。")
            return

        new_share = {"name": os.path.basename(path), "path": path, "permissions": ["read"]}
        if "shares" not in self.config_data: self.config_data["shares"] = []
        self.config_data["shares"].append(new_share)
        self.load_config_to_ui()

    def remove_share(self):
        current_item = self.share_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在左侧选择一个要移除的共享。")
            return

        path_to_remove = current_item.data(Qt.UserRole)
        self.config_data["shares"] = [s for s in self.config_data["shares"] if s["path"] != path_to_remove]
        self.load_config_to_ui()

    def save_current_details(self):
        """一个辅助函数，用于将右侧详情区的内容保存到内存中的config_data"""
        # 这个函数确保在切换选项或最终保存前，当前编辑的内容不会丢失
        current_item = self.share_list_widget.currentItem()
        if current_item and self.share_name_edit.isEnabled():
            path_to_update = current_item.data(Qt.UserRole)
            for share in self.config_data.get("shares", []):
                if share.get("path") == path_to_update:
                    share["name"] = self.share_name_edit.text()
                    permissions = ["read"]
                    if self.allow_upload_checkbox.isChecked(): permissions.append("write")
                    share["permissions"] = permissions
                    # 更新列表项的显示文本
                    current_item.setText(share["name"])
                    break

    def save_and_accept(self):
        """保存当前UI上的修改到config_data，并写回文件"""
        self.save_current_details()

        try:
            with open("config.toml", "w", encoding='utf-8') as f:
                toml.dump(self.config_data, f)
            QMessageBox.information(self, "成功", "设置已保存。请重启应用以使所有更改生效。")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")