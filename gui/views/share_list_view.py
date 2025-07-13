"""
共享文件夹列表视图类，用于显示本地共享文件夹
"""
from typing import Dict, Any, List, Optional, Callable

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QWidget, QVBoxLayout, QLabel, 
    QHBoxLayout, QPushButton, QMenu
)
from PySide6.QtGui import QIcon


class ShareListView(QWidget):
    """共享文件夹列表视图，显示本地共享文件夹"""
    
    manage_shares_clicked = Signal()
    share_context_menu_requested = Signal(str, QPoint)  # 发射共享名称和全局位置
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        
        # 标题和管理按钮
        header_layout = QHBoxLayout()
        title_label = QLabel("<h4>本机共享</h4>")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        self.manage_shares_button = QPushButton("设置")
        self.manage_shares_button.setToolTip("打开设置窗口以添加、移除或修改本机共享")
        self.manage_shares_button.clicked.connect(self.manage_shares_clicked)
        header_layout.addWidget(self.manage_shares_button)
        
        layout.addLayout(header_layout)
        
        # 共享列表
        self.share_list_widget = QListWidget()
        self.share_list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.share_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.share_list_widget.customContextMenuRequested.connect(self._on_context_menu_requested)
        layout.addWidget(self.share_list_widget)
        
        # 设置最小高度
        self.setMinimumHeight(130)
        
    def _on_context_menu_requested(self, pos):
        """处理右键菜单请求"""
        item = self.share_list_widget.itemAt(pos)
        if not item or item.text() == "无共享文件夹" or "请点击右侧" in item.text():
            return
            
        share_name = item.text().split(' (')[0]
        global_pos = self.share_list_widget.mapToGlobal(pos)
        self.share_context_menu_requested.emit(share_name, global_pos)
        
    def update_shares(self, shares: List[Dict[str, Any]], folder_icon: QIcon):
        """更新共享文件夹列表"""
        self.share_list_widget.clear()
        
        if not shares:
            # 为新用户提供清晰的引导
            item = QListWidgetItem("👉 请点击右侧\"设置\"按钮\n    添加您的第一个共享文件夹")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
            item.setForeground(Qt.gray)
            self.share_list_widget.addItem(item)
            return
            
        for share in shares:
            name = share.get('name', '未命名')
            permissions = share.get("permissions", [])
            parts = []
            if "read" in permissions: parts.append("可读")
            if "download" in permissions: parts.append("可下载")
            if "upload" in permissions: parts.append("可上传")
            perm_text = "/".join(parts) if parts else "无权限"
            
            item = QListWidgetItem(f"{name} ({perm_text})")
            item.setToolTip(f"本地路径: {share.get('path')}")
            item.setIcon(folder_icon)
            self.share_list_widget.addItem(item) 