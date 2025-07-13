"""
文件浏览器视图类，用于显示和操作远程文件
"""
from typing import Dict, Any, List, Optional, Callable

from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, 
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu
)
from PySide6.QtGui import QIcon, QDragEnterEvent, QDropEvent, QAction


class FileTableWidget(QTableWidget):
    """自定义表格控件，支持拖拽上传并显示视觉反馈"""
    
    files_dropped = Signal(list)  # 发射拖放的文件URL列表
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.drop_overlay = None
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        """处理拖拽进入事件，无条件接受拖拽"""
        if event.mimeData().hasUrls():
            event.accept()
            self.showDropOverlay()
        else:
            event.ignore()
            
    def dragMoveEvent(self, event):
        """处理拖拽移动事件，始终接受拖拽"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()
            
    def dragLeaveEvent(self, event):
        """处理拖拽离开事件，隐藏视觉反馈"""
        self.hideDropOverlay()
        event.accept()
            
    def dropEvent(self, event: QDropEvent):
        """处理拖拽释放事件"""
        self.hideDropOverlay()
        
        if not event.mimeData().hasUrls():
            event.ignore()
            return
            
        # 获取所有拖拽的URL
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
            
        # 接受事件
        event.accept()
        
        # 发射信号
        self.files_dropped.emit(urls)
            
    def showDropOverlay(self):
        """显示全屏拖拽覆盖层"""
        if self.drop_overlay is None:
            # 创建一个半透明的全屏覆盖层
            self.drop_overlay = QLabel(self.viewport())
            self.drop_overlay.setObjectName("FileTableDropOverlay")
            self.drop_overlay.setAlignment(Qt.AlignCenter)
            self.drop_overlay.setText("拖放文件或文件夹到此处上传")
        
        # 确保覆盖层大小正确
        self.drop_overlay.setGeometry(0, 0, self.viewport().width(), self.viewport().height())
        self.drop_overlay.show()
        self.drop_overlay.raise_()  # 确保覆盖层在最上层
            
    def hideDropOverlay(self):
        """隐藏拖拽覆盖层"""
        if self.drop_overlay is not None:
            self.drop_overlay.hide()
            
    def resizeEvent(self, event):
        """处理大小变化事件，调整拖拽覆盖层大小"""
        super().resizeEvent(event)
        if self.drop_overlay is not None and self.drop_overlay.isVisible():
            self.drop_overlay.setGeometry(0, 0, self.viewport().width(), self.viewport().height())


class FileBrowserView(QWidget):
    """文件浏览器视图，显示和操作远程文件"""
    
    share_selected = Signal(str)  # 发射选中的共享名称
    back_clicked = Signal()  # 发射返回按钮点击事件
    upload_file_clicked = Signal()  # 发射上传文件按钮点击事件
    upload_folder_clicked = Signal()  # 发射上传文件夹按钮点击事件
    download_clicked = Signal()  # 发射下载按钮点击事件
    item_double_clicked = Signal(int, int)  # 发射双击项目事件（行，列）
    files_dropped = Signal(list)  # 发射拖放的文件URL列表
    context_menu_requested = Signal(QPoint, list)  # 发射右键菜单请求（全局位置，选中的行）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 0, 0)
        
        # 工具栏
        toolbar_layout = QHBoxLayout()
        
        # 共享选择器
        self.share_selector_combo = QComboBox()
        self.share_selector_combo.currentIndexChanged.connect(
            lambda index: self.share_selected.emit(self.share_selector_combo.currentText())
        )
        
        # 返回按钮
        self.back_button = QPushButton()
        self.back_button.setToolTip("返回上一级目录")
        self.back_button.clicked.connect(self.back_clicked)
        
        # 当前路径
        self.current_path_label = QLineEdit("/")
        self.current_path_label.setObjectName("FilePathLabel")
        self.current_path_label.setReadOnly(True)
        self.current_path_label.setToolTip("当前正在浏览的远程路径")

        # 上传按钮
        self.upload_button = QPushButton()
        self.upload_button.setToolTip("向当前远程路径上传文件或文件夹")
        
        # 下载按钮
        self.download_button = QPushButton()
        self.download_button.setToolTip("下载选中的文件或文件夹")
        self.download_button.clicked.connect(self.download_clicked)

        # 添加到工具栏
        toolbar_layout.addWidget(self.share_selector_combo)
        toolbar_layout.addWidget(self.back_button)
        toolbar_layout.addWidget(QLabel("当前路径:"))
        toolbar_layout.addWidget(self.current_path_label, stretch=1)
        toolbar_layout.addWidget(self.upload_button)
        toolbar_layout.addWidget(self.download_button)
        
        layout.addLayout(toolbar_layout)

        # 文件表格
        self.file_table_widget = FileTableWidget(self)
        self.file_table_widget.setColumnCount(4)
        self.file_table_widget.setHorizontalHeaderLabels(["", "文件名", "类型", "大小"])
        self.file_table_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        header = self.file_table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        
        self.file_table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table_widget.customContextMenuRequested.connect(self._on_context_menu_requested)
        self.file_table_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.file_table_widget.setAlternatingRowColors(True)
        self.file_table_widget.setShowGrid(False)
        self.file_table_widget.verticalHeader().setVisible(False)
        self.file_table_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_table_widget.files_dropped.connect(self.files_dropped)
        
        layout.addWidget(self.file_table_widget)
        
        # 设置上传按钮菜单
        upload_menu = QMenu(self)
        upload_files_action = QAction("上传文件...", self)
        upload_files_action.triggered.connect(self.upload_file_clicked)
        upload_folder_action = QAction("上传文件夹...", self)
        upload_folder_action.triggered.connect(self.upload_folder_clicked)
        upload_menu.addAction(upload_files_action)
        upload_menu.addAction(upload_folder_action)
        self.upload_button.setMenu(upload_menu)
        
    def _on_context_menu_requested(self, pos):
        """处理右键菜单请求"""
        global_pos = self.file_table_widget.mapToGlobal(pos)
        selected_rows = sorted(list(set(item.row() for item in self.file_table_widget.selectedItems())))
        self.context_menu_requested.emit(global_pos, selected_rows)
        
    def _on_item_double_clicked(self, item):
        """处理双击事件"""
        if item.column() == 0:
            return
        row = self.file_table_widget.row(item)
        col = self.file_table_widget.column(item)
        self.item_double_clicked.emit(row, col)
        
    def set_icons(self, back_icon: QIcon, upload_icon: QIcon, download_icon: QIcon, 
                 folder_icon: QIcon, file_icon: QIcon):
        """设置图标"""
        self.back_icon = back_icon
        self.upload_icon = upload_icon
        self.download_icon = download_icon
        self.folder_icon = folder_icon
        self.file_icon = file_icon
        
        # 设置按钮图标
        self.back_button.setIcon(back_icon)
        self.upload_button.setIcon(upload_icon)
        self.download_button.setIcon(download_icon)
        
        # 设置按钮文本
        self.back_button.setText("返回")
        self.upload_button.setText("上传")
        self.download_button.setText("下载")
        
    def set_shares(self, shares: List[str]):
        """设置共享列表"""
        self.share_selector_combo.blockSignals(True)
        self.share_selector_combo.clear()
        if shares:
            self.share_selector_combo.addItems(shares)
        self.share_selector_combo.blockSignals(False)
        
    def set_current_path(self, path: str):
        """设置当前路径"""
        self.current_path_label.setText(path)
        
    def set_back_button_enabled(self, enabled: bool):
        """设置返回按钮是否启用"""
        self.back_button.setEnabled(enabled)
        
    def set_upload_button_enabled(self, enabled: bool):
        """设置上传按钮是否启用"""
        self.upload_button.setEnabled(enabled)
        
    def set_download_button_enabled(self, enabled: bool):
        """设置下载按钮是否启用"""
        self.download_button.setEnabled(enabled)
        
    def clear_files(self):
        """清空文件列表"""
        self.file_table_widget.setRowCount(0)
        
    def update_files(self, files: List[Dict[str, Any]]):
        """更新文件列表"""
        self.file_table_widget.setRowCount(len(files))
        
        for row, file_info in enumerate(files):
            # 复选框
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)

            # 文件名
            name_item = QTableWidgetItem(file_info['name'])
            name_item.setIcon(self.folder_icon if file_info['is_dir'] else self.file_icon)

            # 类型
            type_item = QTableWidgetItem("文件夹" if file_info['is_dir'] else "文件")
            
            # 大小
            size_item = QTableWidgetItem(self._format_size(file_info['size']))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            # 设置所有项目为不可编辑
            for item in [name_item, type_item, size_item]:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # 添加到表格
            self.file_table_widget.setItem(row, 0, check_item)
            self.file_table_widget.setItem(row, 1, name_item)
            self.file_table_widget.setItem(row, 2, type_item)
            self.file_table_widget.setItem(row, 3, size_item)
            
    def get_selected_rows(self) -> List[int]:
        """获取选中的行"""
        return sorted(list(set(item.row() for item in self.file_table_widget.selectedItems())))
        
    def get_checked_rows(self) -> List[int]:
        """获取勾选的行"""
        checked_rows = []
        for row in range(self.file_table_widget.rowCount()):
            check_item = self.file_table_widget.item(row, 0)
            if check_item and check_item.checkState() == Qt.CheckState.Checked:
                checked_rows.append(row)
        return checked_rows
        
    def get_file_at_row(self, row: int) -> Dict[str, Any]:
        """获取指定行的文件信息"""
        if 0 <= row < self.file_table_widget.rowCount():
            name_item = self.file_table_widget.item(row, 1)
            type_item = self.file_table_widget.item(row, 2)
            size_item = self.file_table_widget.item(row, 3)
            
            if name_item and type_item:
                return {
                    'name': name_item.text(),
                    'is_dir': type_item.text() == '文件夹',
                    'size': self._parse_size(size_item.text() if size_item else "0")
                }
        return {}
        
    def _format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        import math
        
        if size_bytes <= 0:
            return ""
        if size_bytes < 1024:
            return f"{size_bytes} B"
            
        power_labels = ('KB', 'MB', 'GB', 'TB')
        i = int(math.floor(math.log(size_bytes, 1024)))
        i = min(i - 1, len(power_labels) - 1)

        p = math.pow(1024, i + 1)
        s = round(size_bytes / p, 2)
        return f"{s} {power_labels[i]}"
        
    def _parse_size(self, size_str: str) -> int:
        """解析文件大小字符串为字节数"""
        if not size_str:
            return 0
            
        try:
            parts = size_str.split()
            if len(parts) != 2:
                return 0
                
            value = float(parts[0])
            unit = parts[1]
            
            if unit == 'B':
                return int(value)
            elif unit == 'KB':
                return int(value * 1024)
            elif unit == 'MB':
                return int(value * 1024 * 1024)
            elif unit == 'GB':
                return int(value * 1024 * 1024 * 1024)
            elif unit == 'TB':
                return int(value * 1024 * 1024 * 1024 * 1024)
        except:
            pass
            
        return 0 