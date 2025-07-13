"""
传输列表视图类，用于显示当前的传输任务
"""

from typing import Dict, Any, List, Optional

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QFrame,
)
from PySide6.QtGui import QIcon, QFont, QColor


class TransferTaskItem(QWidget):
    """单个传输任务项的UI组件"""

    def __init__(self, task_name: str, task_type: str, parent=None):
        super().__init__(parent)
        self.task_name = task_name
        self.task_type = task_type
        self._setup_ui()

    def _setup_ui(self):
        """设置UI组件"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 12, 10, 12)  # 缩小内边距
        main_layout.setSpacing(8)  # 缩小间距

        # 任务名称和类型
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)  # 缩小间距
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 设置任务图标
        self.icon_label = QLabel()
        self.icon_label.setMinimumSize(29, 29)  # 缩小图标尺寸40%
        self.icon_label.setMaximumSize(29, 29)  # 缩小图标尺寸40%
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setObjectName("TransferTaskIcon")
        top_layout.addWidget(self.icon_label)

        # 任务名称 - 使用省略模式显示长文件名
        name_container = QWidget()
        name_layout = QVBoxLayout(name_container)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(1)  # 微调间距

        # 使用QLabel显示文件名，截断过长的文本
        if len(self.task_name) > 30:
            display_name = self.task_name[:15] + "..." + self.task_name[-12:]
        else:
            display_name = self.task_name

        self.name_label = QLabel(display_name)
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)  # 缩小字体
        self.name_label.setFont(font)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.name_label.setWordWrap(False)
        self.name_label.setToolTip(self.task_name)
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.name_label.setMinimumHeight(26)  # 缩小高度
        self.name_label.setObjectName("TransferTaskName")

        name_layout.addWidget(self.name_label)
        top_layout.addWidget(name_container, 1)

        # 任务类型标签
        type_text = "下载中" if "download" in self.task_type else "上传中"
        self.type_label = QLabel(type_text)
        self.type_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.type_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        self.type_label.setMinimumHeight(26)  # 缩小高度
        self.type_label.setObjectName("TransferTaskType")
        top_layout.addWidget(self.type_label)

        main_layout.addLayout(top_layout)

        # 状态标签 - 截断过长的文本
        self.status_label = QLabel("准备中...")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setWordWrap(False)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.status_label.setMinimumHeight(25)  # 缩小高度
        self.status_label.setObjectName("TransferTaskStatus")
        main_layout.addWidget(self.status_label)

        # 进度条和取消按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)  # 缩小间距
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")  # 设置进度条格式为百分比
        self.progress_bar.setMinimumHeight(12)  # 缩小高度
        self.progress_bar.setMaximumHeight(12)  # 缩小高度
        self.progress_bar.setObjectName("TransferTaskProgressBar")
        bottom_layout.addWidget(self.progress_bar, 1)

        # 取消按钮
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setMinimumSize(42, 19)  # 缩小按钮尺寸
        self.cancel_button.setObjectName("TransferTaskCancelButton")
        bottom_layout.addWidget(self.cancel_button)

        main_layout.addLayout(bottom_layout)

    def update_status(self, text: str):
        """更新状态文本"""
        # 截断过长的状态文本
        if len(text) > 40:
            text = text[:37] + "..."
        self.status_label.setText(text)
        self.status_label.setToolTip(text)

    def set_icons(self, download_icon: QIcon, upload_icon: QIcon):
        """设置图标"""
        if "download" in self.task_type:
            # 确保图标有效
            if download_icon and not download_icon.isNull():
                self.icon_label.setPixmap(
                    download_icon.pixmap(29, 29)
                )  # 缩小图标尺寸40%
                self.progress_bar.setObjectName("TransferTaskProgressBarDownload")
            else:
                self.icon_label.setText("⬇️")
                self.icon_label.setProperty("iconType", "text")
        else:
            # 确保图标有效
            if upload_icon and not upload_icon.isNull():
                self.icon_label.setPixmap(upload_icon.pixmap(29, 29))  # 缩小图标尺寸40%
                self.progress_bar.setObjectName("TransferTaskProgressBarUpload")
            else:
                self.icon_label.setText("⬆️")
                self.icon_label.setProperty("iconType", "text")

    def update_progress(self, value: int):
        """更新进度条"""
        # 如果进度条处于不确定模式（范围为0,0），则先恢复确定模式
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        self.progress_bar.setValue(value)
        # 确保进度条显示准确的百分比值
        self.progress_bar.setFormat(f"{value}%")

    def get_cancel_button(self) -> QPushButton:
        """获取取消按钮"""
        return self.cancel_button


class TransferListView(QWidget):
    """传输列表视图，显示当前的传输任务"""

    task_cancelled = Signal(int)  # 发射任务索引
    position_update_needed = Signal()  # 新增信号，用于通知需要更新位置

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task_items = {}  # 存储任务项组件
        self.download_icon = None
        self.upload_icon = None
        self.floating_mode = False  # 是否为悬浮模式
        self.position_set = False  # 是否已设置位置
        self.setObjectName("TransferListView")
        self._setup_ui()

        # 设置定时器，定期检查位置更新
        from PySide6.QtCore import QTimer

        self.position_timer = QTimer(self)
        self.position_timer.setInterval(500)  # 每500毫秒检查一次
        self.position_timer.timeout.connect(self._check_position_update)

    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建一个带边框的框架
        self.frame = QFrame()
        self.frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame.setFrameShadow(QFrame.Shadow.Raised)
        self.frame.setObjectName("TransferListFrame")
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(12, 12, 12, 12)  # 缩小内边距
        frame_layout.setSpacing(10)  # 缩小间距

        # 标题栏
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 10)  # 缩小底部间距
        header_layout.setSpacing(10)  # 缩小间距

        title_label = QLabel("传输任务")
        title_label.setMinimumHeight(22)  # 缩小高度
        title_label.setObjectName("TransferListTitle")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # 添加关闭按钮
        self.close_button = QPushButton("×")
        self.close_button.setMinimumSize(22, 22)  # 缩小按钮尺寸
        self.close_button.setMaximumSize(22, 22)  # 缩小按钮尺寸
        self.close_button.setToolTip("关闭传输列表")
        self.close_button.clicked.connect(self.hide)
        self.close_button.setObjectName("TransferListCloseButton")
        header_layout.addWidget(self.close_button)

        frame_layout.addLayout(header_layout)

        # 任务列表
        self.task_list = QListWidget()
        self.task_list.setAlternatingRowColors(True)
        self.task_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.task_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.task_list.setSpacing(5)  # 缩小项目间距
        self.task_list.setObjectName("TransferTaskList")
        frame_layout.addWidget(self.task_list)

        # 添加框架到主布局
        layout.addWidget(self.frame)

        # 设置最小宽度而不是固定宽度，允许窗口根据内容调整大小
        self.setMinimumWidth(276)  # 缩小最小宽度40%
        self.setMinimumHeight(192)  # 缩小最小高度40%

        # 设置窗口阴影
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _check_position_update(self):
        """检查是否需要更新位置"""
        if self.isVisible() and self.floating_mode:
            self.position_update_needed.emit()

    def set_floating_mode(self, floating: bool):
        """设置是否为悬浮模式"""
        self.floating_mode = floating
        if floating:
            # 设置窗口标志，使其成为独立窗口
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

            # 设置布局边距，为阴影留出空间
            layout = self.layout()
            if layout:
                layout.setContentsMargins(6, 6, 6, 6)  # 缩小阴影空间

            # 设置悬浮模式类
            self.frame.setProperty("floating", "true")
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)
        else:
            # 恢复为普通窗口
            self.setWindowFlags(Qt.WindowType.Widget)
            # 停止位置更新定时器
            self.position_timer.stop()

            # 移除悬浮模式类
            self.frame.setProperty("floating", "false")
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)

    def showEvent(self, event):
        """显示事件处理"""
        super().showEvent(event)

        # 发出位置更新请求
        if self.floating_mode:
            # 立即更新位置
            self._emit_position_update()

            # 确保窗口完全显示后再次更新位置
            from PySide6.QtCore import QTimer

            QTimer.singleShot(50, self._emit_position_update)

            # 启动位置更新定时器
            self.position_timer.start()

    def hideEvent(self, event):
        """隐藏事件处理"""
        super().hideEvent(event)
        # 停止位置更新定时器
        self.position_timer.stop()

    def _emit_position_update(self):
        """发出位置更新请求"""
        if self.parent():
            # 查找MainWindowMVC实例
            from gui.main_window_mvc import MainWindowMVC

            parent = self.parent()
            while parent:
                if isinstance(parent, MainWindowMVC):
                    parent._update_floating_window_position()
                    break
                parent = parent.parent()

    def set_icons(self, download_icon: QIcon, upload_icon: QIcon):
        """设置图标"""
        self.download_icon = download_icon
        self.upload_icon = upload_icon

        # 更新现有任务项的图标
        for task_id, item in self.task_items.items():
            item.set_icons(download_icon, upload_icon)

    def add_task(self, task_id: str, task_name: str, task_type: str) -> int:
        """添加任务到列表，返回任务项索引"""
        # 创建任务项组件
        task_item = TransferTaskItem(task_name, task_type)

        # 设置图标
        if self.download_icon and self.upload_icon:
            task_item.set_icons(self.download_icon, self.upload_icon)

        # 连接取消按钮信号
        item_index = self.task_list.count()
        task_item.get_cancel_button().clicked.connect(
            lambda: self.task_cancelled.emit(item_index)
        )

        # 创建列表项
        list_item = QListWidgetItem()
        self.task_list.addItem(list_item)

        # 设置列表项大小
        task_item.adjustSize()  # 先调整组件大小
        size_hint = task_item.sizeHint()
        # 确保高度足够
        size_hint.setHeight(max(size_hint.height(), 96))  # 缩小最小高度40%
        list_item.setSizeHint(size_hint)

        # 设置自定义组件
        self.task_list.setItemWidget(list_item, task_item)

        # 存储任务项
        self.task_items[task_id] = task_item

        return item_index

    def update_task_progress(self, task_id: str, value: int):
        """更新任务进度"""
        if task_id in self.task_items:
            self.task_items[task_id].update_progress(value)

    def update_task_status(self, task_id: str, text: str):
        """更新任务状态"""
        if task_id in self.task_items:
            self.task_items[task_id].update_status(text)

    def remove_task(self, task_id: str):
        """从列表中移除任务"""
        if task_id in self.task_items:
            # 找到对应的列表项
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                if self.task_list.itemWidget(item) == self.task_items[task_id]:
                    # 移除列表项
                    self.task_list.takeItem(i)
                    break

            # 从字典中移除
            del self.task_items[task_id]

    def clear_tasks(self):
        """清空任务列表"""
        self.task_list.clear()
        self.task_items.clear()

    def get_task_count(self) -> int:
        """获取任务数量"""
        return self.task_list.count()

    def paintEvent(self, event):
        """绘制事件，用于添加阴影效果"""
        super().paintEvent(event)
        if self.floating_mode:
            from PySide6.QtGui import QPainter, QColor, QPainterPath

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 绘制阴影
            shadow_color = QColor(0, 0, 0, 40)
            shadow_radius = 7  # 缩小阴影半径

            path = QPainterPath()
            path.addRoundedRect(
                6, 6, self.width() - 12, self.height() - 12, 5, 5
            )  # 缩小圆角

            for i in range(1, shadow_radius + 1):
                shadow_color.setAlpha(40 - i * 3)  # 调整渐变阴影
                painter.setPen(shadow_color)
                painter.drawPath(path.translated(0, i))
