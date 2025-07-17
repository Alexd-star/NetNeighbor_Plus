"""
主窗口MVC架构实现，应用程序的主界面
"""

import os
import socket
import time
import math
from typing import Dict, Any, List, Optional

from PySide6.QtCore import Qt, QTimer, QSize, QPoint
from PySide6.QtGui import QCloseEvent, QIcon, QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QStackedWidget,
    QLabel,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QStyle,
    QFrame,
)

from core.config_loader import load_config, CONFIG_PATH
from gui.app_controller import AppController


from gui.models.device_model import DeviceModel
from gui.models.file_model import FileModel
from gui.models.connection_model import ConnectionModel
from gui.models.log_model import LogModel
from gui.models.share_model import ShareModel, RemoteShareModel
from gui.models.transfer_model import TransferModel


from gui.views.device_list_view import DeviceListView
from gui.views.share_list_view import ShareListView
from gui.views.status_view import StatusView
from gui.views.welcome_view import WelcomeView

from gui.presenters.device_presenter import DevicePresenter
from gui.presenters.share_presenter import SharePresenter
from gui.presenters.status_presenter import StatusPresenter
from gui.presenters.connection_presenter import ConnectionPresenter


class MainWindowMVC(QMainWindow):
    """使用MVC架构的主窗口类"""

    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller

        # 初始化延迟加载的组件为None，避免引用错误
        self.log_view = None
        self.file_browser_view = None
        self.floating_transfer_view = None
        self.log_presenter = None
        self.file_browser_presenter = None
        self.transfer_manager = None

        # 防抖机制相关变量
        self._last_device_count_update = 0
        self._device_count_update_timer = None
        self._pending_device_count = 0

        # UI批量更新机制
        self._pending_ui_updates = set()
        self._ui_update_timer = None
        self._max_ui_updates_per_second = 10  # 限制UI更新频率

        # 自适应性能调整
        self._adaptive_performance_enabled = True

        # 设备发现限流机制
        self._device_batch_size = 10  # 批量处理设备数量
        self._device_batch_timer = None
        self._pending_device_events = []

        # 创建关键模型
        self.device_model = DeviceModel()
        self.share_model = ShareModel()
        self.remote_share_model = RemoteShareModel()
        self.connection_model = ConnectionModel()
        self.transfer_model = TransferModel()
        self.log_model = LogModel()
        self.file_model = FileModel()  # 文件模型需要在初始化时创建

        # 创建关键视图
        self.device_list_view = DeviceListView()
        self.share_list_view = ShareListView()
        self.welcome_view = WelcomeView()
        self.status_view = StatusView()

        # 创建关键Presenter
        self.device_presenter = DevicePresenter(
            self.device_model, self.device_list_view
        )
        self.share_presenter = SharePresenter(self.share_model, self.share_list_view)
        self.status_presenter = StatusPresenter(
            self.controller, self.connection_model, self.status_view
        )
        self.connection_presenter = ConnectionPresenter(
            self.connection_model, self.remote_share_model, self.log_model
        )

        # 设置关键UI组件
        self._setup_ui()
        self._setup_status_bar()  # 状态栏优先显示

        # 延迟设置非关键UI组件
        QTimer.singleShot(10, self._setup_menu)
        QTimer.singleShot(20, self._setup_icons)

        # 延迟更新本地共享列表，避免阻塞UI显示
        QTimer.singleShot(30, self.share_model.reload_shares)

        # 使用QTimer延迟初始化非关键组件，减少延迟时间
        QTimer.singleShot(80, self._delayed_init)

    def _delayed_init(self):
        """延迟初始化非关键组件"""
        # 懒导入非关键视图
        from gui.views.log_view import LogView
        from gui.views.file_browser_view import FileBrowserView
        from gui.views.transfer_list_view import TransferListView

        # 创建非关键视图
        self.log_view = LogView()
        self.file_browser_view = FileBrowserView()
        self.floating_transfer_view = TransferListView()

        # 添加日志视图到UI
        left_panel = self.findChild(QSplitter).widget(0)
        if left_panel:
            left_layout = left_panel.layout()
            left_layout.addWidget(self.log_view, stretch=3)

        # 添加文件浏览器视图到堆叠窗口
        self.stacked_widget.addWidget(self.file_browser_view)

        # 懒导入非关键Presenter
        from gui.presenters.log_presenter import LogPresenter
        from gui.presenters.file_browser_presenter import FileBrowserPresenter
        from gui.presenters.transfer_manager import TransferManager

        # 创建非关键Presenter
        self.log_presenter = LogPresenter(self.log_model, self.log_view)
        self.file_browser_presenter = FileBrowserPresenter(
            self.file_model,
            self.remote_share_model,
            self.connection_model,
            self.file_browser_view,
        )

        # 设置文件浏览器图标
        self.file_browser_presenter.set_icons(
            self.back_icon,
            self.upload_icon,
            self.download_icon,
            self.folder_icon,
            self.file_icon,
            self.upload_file_icon,
            self.upload_folder_icon,
        )

        # 创建传输管理器
        self.transfer_manager = TransferManager(
            self.transfer_model, self.log_model, self.connection_model
        )

        # 创建悬浮传输列表窗口
        self.floating_transfer_view.set_floating_mode(True)
        self.floating_transfer_view.setVisible(False)

        # 设置传输列表图标
        self.floating_transfer_view.set_icons(self.download_icon, self.upload_icon)

        # 设置传输管理器的悬浮视图
        self.transfer_manager.set_floating_transfer_view(self.floating_transfer_view)
        self.transfer_manager.set_icons(self.download_icon, self.upload_icon)

        # 设置连接
        self._setup_connections()

        # 添加初始日志
        self.log_presenter.add_log("系统初始化完成", "✅")

    def _setup_ui(self):
        """设置UI布局"""
        self.setWindowTitle("邻里+ (NetNeighbor Plus)")
        self.setGeometry(100, 100, 1100, 680)
        self.setWindowIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )

        # 居中显示
        try:
            center = self.screen().availableGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())
        except AttributeError:
            self.setGeometry(100, 100, 1100, 680)

        # 延迟加载样式表，避免阻塞UI显示
        QTimer.singleShot(5, self._load_stylesheet)

    def _load_stylesheet(self):
        """延迟加载样式表"""
        import os
        import sys

        # 确定样式文件路径（支持打包后的应用）
        if getattr(sys, "frozen", False):
            # 打包后的应用
            base_path = sys._MEIPASS
            style_path = os.path.join(base_path, "gui", "style.qss")
        else:
            # 开发环境
            style_path = "gui/style.qss"

        try:
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            print(f"样式表加载成功: {style_path}")
        except Exception as e:
            print(f"加载样式表失败: {e}")
            print(f"尝试的路径: {style_path}")
            # 如果加载失败，尝试备用路径
            try:
                with open("style.qss", "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
                print("使用备用样式表路径成功")
            except:
                print("所有样式表路径都失败，使用默认样式")

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 添加状态视图
        main_layout.addWidget(self.status_view)

        # 创建主分割器
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧设备列表
        left_layout.addWidget(self.device_list_view, stretch=4)

        # 左侧共享列表
        left_layout.addWidget(self.share_list_view, stretch=3)

        # 右侧面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 右侧堆叠视图
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.welcome_view)
        self.stacked_widget.setCurrentWidget(self.welcome_view)
        right_layout.addWidget(self.stacked_widget, stretch=1)

        # 添加到主分割器
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)

        # 设置初始分割位置（左侧占整个宽度的30%）
        main_splitter.setSizes([300, 650])

        # 添加到主布局
        main_layout.addWidget(main_splitter, stretch=1)

    def _setup_menu(self):
        """设置菜单栏"""
        menu_bar = self.menuBar()

        # 文件菜单
        file_menu = menu_bar.addMenu("文件")
        settings_action = file_menu.addAction("设置...")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)

        # 帮助菜单
        help_menu = menu_bar.addMenu("帮助")
        about_action = help_menu.addAction("关于...")
        about_action.triggered.connect(self._show_about)

        # 存储菜单动作以便后续设置图标
        self.settings_action = settings_action
        self.exit_action = exit_action
        self.about_action = about_action

    def _setup_status_bar(self):
        """设置状态栏"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar_label = QLabel("正在初始化...")
        self.status_bar.addWidget(self.status_bar_label, 1)

        # 添加传输状态按钮到状态栏右侧
        self.transfer_status_button = QPushButton("传输: 0")
        self.transfer_status_button.setStyleSheet(
            """
            QPushButton {
                border: none;
                padding: 2px 8px;
                background-color: #f0f0f0;
                border-radius: 3px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """
        )
        self.transfer_status_button.setToolTip("点击查看传输任务")
        self.transfer_status_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.transfer_status_button.clicked.connect(self._toggle_transfer_list)
        self.transfer_status_button.setVisible(False)  # 初始隐藏
        self.status_bar.addPermanentWidget(self.transfer_status_button)

    def _setup_icons(self):
        """设置图标 - 批量获取以提高效率"""
        style = self.style()

        # 批量获取所有需要的图标
        icon_mappings = {
            "folder_icon": QStyle.StandardPixmap.SP_DirIcon,
            "file_icon": QStyle.StandardPixmap.SP_FileIcon,
            "back_icon": QStyle.StandardPixmap.SP_ArrowLeft,
            "upload_icon": QStyle.StandardPixmap.SP_ArrowUp,
            "download_icon": QStyle.StandardPixmap.SP_ArrowDown,
            "device_icon": QStyle.StandardPixmap.SP_DriveNetIcon,
            "refresh_icon": QStyle.StandardPixmap.SP_BrowserReload,
            "settings_icon": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "delete_icon": QStyle.StandardPixmap.SP_TrashIcon,
            "rename_icon": QStyle.StandardPixmap.SP_FileDialogContentsView,
            # 菜单图标
            "exit_icon": QStyle.StandardPixmap.SP_DialogCloseButton,
            "about_icon": QStyle.StandardPixmap.SP_MessageBoxInformation,
            # 上传菜单图标
            "upload_file_icon": QStyle.StandardPixmap.SP_FileIcon,
            "upload_folder_icon": QStyle.StandardPixmap.SP_DirIcon,
        }

        # 一次性设置所有图标
        for attr_name, pixmap in icon_mappings.items():
            setattr(self, attr_name, style.standardIcon(pixmap))

        # 设置图标到关键Presenter
        self.device_presenter.set_device_icon(self.device_icon)
        self.share_presenter.set_folder_icon(self.folder_icon)

        # 设置菜单项图标
        if hasattr(self, "settings_action"):
            self.settings_action.setIcon(self.settings_icon)
        if hasattr(self, "exit_action"):
            self.exit_action.setIcon(self.exit_icon)
        if hasattr(self, "about_action"):
            self.about_action.setIcon(self.about_icon)

    def _setup_connections(self):
        """设置信号连接"""
        # 设备选择
        self.device_presenter.on_device_selected(self._on_device_selected)

        # 共享管理
        self.share_presenter.on_manage_shares(self._open_settings)
        self.share_presenter.on_permission_change(self._on_permission_change)
        self.share_presenter.on_remove_share(self._on_remove_share)

        # 文件操作 - 只有在file_browser_presenter已初始化时才设置
        if self.file_browser_presenter:
            self.file_browser_presenter.on_upload_file(self._on_upload_file)
            self.file_browser_presenter.on_upload_folder(self._on_upload_folder)
            self.file_browser_presenter.on_download(self._on_download)
            self.file_browser_presenter.on_rename(self._on_rename)
            self.file_browser_presenter.on_delete(self._on_delete)
            self.file_browser_presenter.on_new_folder(self._on_new_folder)

        # 连接事件
        self.connection_presenter.connection_successful.connect(
            self._on_connection_successful
        )
        self.connection_presenter.connection_failed.connect(self._on_connection_failed)
        self.connection_presenter.on_websocket_message(self._on_websocket_message)

        # 传输事件 - 只有在transfer_manager已初始化时才设置
        if self.transfer_manager:
            self.transfer_manager.task_added.connect(self._on_task_added)
            self.transfer_manager.task_progress.connect(self._on_task_progress)
            self.transfer_manager.task_status.connect(self._on_task_status)
            self.transfer_manager.task_completed.connect(self._on_task_completed)
            self.transfer_manager.task_error.connect(self._on_task_error)
            self.transfer_manager.all_tasks_completed.connect(
                self._on_all_tasks_completed
            )

        # 设置悬浮传输列表视图
        if self.floating_transfer_view:
            self.transfer_manager.set_floating_transfer_view(
                self.floating_transfer_view
            )

        # 连接悬浮窗位置更新信号 - 只有在floating_transfer_view已初始化时才设置
        if self.floating_transfer_view:
            self.floating_transfer_view.position_update_needed.connect(
                self._update_floating_window_position
            )

    def _write_debug_log(self, message):
        """写入调试日志到文件"""
        try:
            import os
            import datetime

            log_file = os.path.join(os.path.expanduser("~"), "netneighbor_debug.log")
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {message}\n")
                f.flush()
        except:
            pass  # 忽略日志写入错误

    def post_init_setup(self):
        """在后台服务启动后进行网络相关的初始化"""
        try:
            self._write_debug_log("=== post_init_setup 开始 ===")

            # 确保日志组件已初始化
            if not self.log_presenter:
                # 如果log_presenter尚未初始化，则先添加到状态栏
                self.status_bar_label.setText("后端服务已就绪, UI开始进行网络初始化...")
                print("后端服务已就绪, UI开始进行网络初始化...")
                self._write_debug_log("log_presenter 未初始化，使用状态栏显示")
            else:
                self.log_presenter.add_log("后端服务已就绪, UI开始进行网络初始化...")
                self._write_debug_log("log_presenter 已初始化，添加日志")

            # 设置本地API客户端
            self._write_debug_log(f"设置本地API客户端，端口: {self.controller.port}")
            print(f"设置本地API客户端，端口: {self.controller.port}")
            base_url = (
                f"http://{self.connection_model.get_my_ip()}:{self.controller.port}"
            )
            self.connection_model.set_local_api_client(base_url)
            print(f"本地API客户端已设置: {base_url}")
            self._write_debug_log(f"本地API客户端已设置: {base_url}")

            # 设置本机服务名称
            my_service_name = f"{self.controller.service_name}._netneighbor._tcp.local."
            self.device_model.set_my_service_name(my_service_name)
            print(f"本机服务名称已设置: {my_service_name}")
            self._write_debug_log(f"本机服务名称已设置: {my_service_name}")

            # 延迟设置WebSocket连接，避免阻塞
            print("准备设置WebSocket连接...")
            self._write_debug_log("准备设置WebSocket连接...")
            QTimer.singleShot(100, lambda: self._setup_websocket_delayed())

            # 获取初始设备列表
            print("获取初始设备列表...")
            self._write_debug_log("获取初始设备列表...")
            self._populate_initial_devices()

            # 更新状态栏
            device_count = self.device_model.get_device_count()
            self._write_debug_log(f"当前设备数量: {device_count}")
            if device_count == 0:
                self.status_bar_label.setText("初始化完成，正在扫描局域网设备...")
                self._write_debug_log("状态栏更新为：正在扫描局域网设备...")

            # 添加日志（如果日志组件已初始化）
            if self.log_presenter:
                self.log_presenter.add_log("系统初始化完成", "✅")
                self._write_debug_log("添加系统初始化完成日志")

            print("post_init_setup 完成")
            self._write_debug_log("=== post_init_setup 完成 ===")

        except Exception as e:
            error_msg = f"post_init_setup 出错: {e}"
            print(error_msg)
            self._write_debug_log(error_msg)
            import traceback

            traceback_str = traceback.format_exc()
            print(traceback_str)
            self._write_debug_log(f"异常堆栈: {traceback_str}")

    def _setup_websocket_delayed(self):
        """延迟设置WebSocket连接"""
        try:
            self._write_debug_log(
                f"=== 开始设置WebSocket连接，端口: {self.controller.port} ==="
            )
            print(f"开始设置WebSocket连接，端口: {self.controller.port}")

            # 设置WebSocket连接
            self.connection_presenter.setup_local_websocket(self.controller.port)

            print("WebSocket连接设置完成")
            self._write_debug_log("WebSocket连接设置完成")

            # 设置一个超时检查，如果5秒后还没有连接成功，记录警告
            QTimer.singleShot(5000, self._check_websocket_status)

        except Exception as e:
            error_msg = f"WebSocket连接设置失败: {e}"
            print(error_msg)
            self._write_debug_log(error_msg)
            import traceback

            traceback_str = traceback.format_exc()
            print(traceback_str)
            self._write_debug_log(f"WebSocket异常堆栈: {traceback_str}")

    def _check_websocket_status(self):
        """检查WebSocket连接状态"""
        try:
            # 检查是否已经收到WebSocket连接成功的日志
            if self.log_presenter:
                # 如果日志中没有WebSocket连接成功的消息，说明可能卡住了
                self._write_debug_log("检查WebSocket状态：5秒超时检查")
                # 这里可以添加更多的状态检查逻辑
            else:
                self._write_debug_log("检查WebSocket状态：log_presenter未初始化")
        except Exception as e:
            self._write_debug_log(f"检查WebSocket状态时出错: {e}")

    def _populate_initial_devices(self):
        """获取初始设备列表"""
        client = self.connection_model.get_local_api_client()
        if not client:
            return

        peers = client.get_peers()
        if not peers:
            return

        # 启用批量更新模式以提高性能
        self.device_model.enable_batch_updates()

        try:
            my_service_name = f"{self.controller.service_name}._netneighbor._tcp.local."
            for name, data in peers.items():
                if name != my_service_name:
                    self.device_model.add_device(name, data)
        finally:
            # 禁用批量更新模式，触发视图更新
            self.device_model.disable_batch_updates()

        # 更新状态栏显示设备数量
        self._update_device_count_status()

    def _on_device_selected(self, service_name: str, device_data: Dict[str, Any]):
        """处理设备选择"""
        # 获取设备显示名称
        display_name = service_name.split("._netneighbor._tcp.local.")[0]

        # 切换到欢迎页面
        self.stacked_widget.setCurrentWidget(self.welcome_view)

        # 更新状态栏
        self.status_bar_label.setText(f"正在连接到 {display_name}...")

        # 添加日志
        if self.log_presenter:
            self.log_presenter.add_log(f"正在尝试连接到 {display_name}...", "⏳")

        # 连接到设备
        self.connection_presenter.connect_to_device(service_name, device_data)

    def _on_connection_successful(self, client, shares):
        """处理连接成功"""
        # 更新状态栏
        display_name = self.connection_model.get_active_device_name()
        self.status_bar_label.setText(f"已连接到 {display_name}")

        # 添加日志
        if self.log_presenter:
            self.log_presenter.add_log(f"已连接到设备: {display_name}", "🔌")

        # 切换到文件浏览器页面（如果已初始化）
        if (
            self.file_browser_view
            and self.stacked_widget.indexOf(self.file_browser_view) != -1
        ):
            self.stacked_widget.setCurrentWidget(self.file_browser_view)

        # 强制刷新文件列表
        # 1. 确保共享选择器有选项
        share_names = self.remote_share_model.get_share_names()

        if self.log_presenter:
            self.log_presenter.add_log(f"获取到共享列表: {share_names}", "📂")

        if share_names:
            # 2. 设置当前共享为第一个共享
            current_share = share_names[0]
            self.remote_share_model.set_current_share(current_share)

            if self.log_presenter:
                self.log_presenter.add_log(f"选择共享: {current_share}", "📁")

            # 更新上传按钮状态（如果文件浏览器已初始化）
            if self.file_browser_presenter:
                self.file_browser_presenter._update_upload_button_state()

            # 3. 强制刷新文件列表
            if self.log_presenter:
                self.log_presenter.add_log("正在刷新文件列表...", "🔄")

            # 延迟刷新，确保UI已更新
            QTimer.singleShot(500, lambda: self._refresh_files())
        else:
            if self.log_presenter:
                self.log_presenter.add_log("没有可用的共享文件夹", "⚠️")

    def _on_connection_failed(self, error_message):
        """处理连接失败"""
        # 保持在欢迎页面
        self.stacked_widget.setCurrentWidget(self.welcome_view)

    def _on_websocket_message(self, data, event, source):
        """处理WebSocket消息 - 使用批量处理优化性能"""
        if event in ["peer_online", "peer_offline"]:
            # 将设备事件加入批量处理队列
            self._pending_device_events.append((event, data))

            # 启动批量处理定时器
            self._schedule_device_batch_processing()
        elif event == "refresh_files":
            # 判断事件来源，避免重复日志
            event_source = data.get("source", "")

            # 处理文件删除通知
            if "deleted_files" in data and self.log_presenter:
                # 如果是API操作（远程操作），不显示日志，因为操作方已经显示了
                # 如果是文件监控器检测到的变化，显示为远程操作日志
                if event_source == "file_watcher":
                    for deleted_file in data["deleted_files"]:
                        file_path = deleted_file.get("path", "")
                        file_name = (
                            os.path.basename(file_path) if file_path else "未知文件"
                        )
                        file_type = (
                            "文件夹"
                            if deleted_file.get("is_directory", False)
                            else "文件"
                        )
                        self.log_presenter.add_log(
                            f"远程{file_type}已删除: {file_name}", "🗑️"
                        )

            # 处理文件重命名通知
            if "renamed_files" in data and self.log_presenter:
                # 如果是API操作（远程操作），不显示日志，因为操作方已经显示了
                # 如果是文件监控器检测到的变化，显示为远程操作日志
                if event_source == "file_watcher":
                    for renamed_file in data["renamed_files"]:
                        old_path = renamed_file.get("old_path", "")
                        new_path = renamed_file.get("new_path", "")
                        old_name = (
                            os.path.basename(old_path) if old_path else "未知文件"
                        )
                        new_name = (
                            os.path.basename(new_path) if new_path else "未知文件"
                        )
                        file_type = (
                            "文件夹"
                            if renamed_file.get("is_directory", False)
                            else "文件"
                        )
                        self.log_presenter.add_log(
                            f"远程{file_type}已重命名: {old_name} -> {new_name}", "✏️"
                        )

            # 防抖处理，避免短时间内重复刷新
            if not hasattr(self, "_last_refresh_time"):
                self._last_refresh_time = 0

            current_time = time.time()
            if current_time - self._last_refresh_time > 0.5:  # 500毫秒防抖
                self._last_refresh_time = current_time

                # 检查是否正在传输文件
                if not self.transfer_model.is_transfer_active():
                    # 仅在非传输状态下刷新文件列表
                    QTimer.singleShot(500, self._refresh_files)
        elif event == "shares_updated":
            # 刷新共享列表
            if self.log_presenter:
                self.log_presenter.add_log(
                    f"设备 {data.get('device_name')} 共享已更新。", "🔄"
                )
            if self.connection_model.get_active_peer_client():
                self._refresh_shares()

    def _update_device_count_status(self):
        """更新状态栏中的设备计数 - 使用防抖机制避免频繁更新"""
        devices_count = self.device_model.get_device_count()
        self._pending_device_count = devices_count

        # 立即更新状态栏（不防抖）
        if devices_count > 0:
            self.status_bar_label.setText(f"已发现 {devices_count} 个设备")
        else:
            self.status_bar_label.setText("正在扫描局域网设备...")

        # 防抖日志输出 - 500ms内只输出一次
        current_time = time.time()
        if current_time - self._last_device_count_update < 0.5:
            # 取消之前的定时器
            if self._device_count_update_timer:
                self._device_count_update_timer.stop()

        # 设置新的定时器
        self._device_count_update_timer = QTimer()
        self._device_count_update_timer.setSingleShot(True)
        self._device_count_update_timer.timeout.connect(self._delayed_device_count_log)
        self._device_count_update_timer.start(500)  # 500ms延迟

        self._last_device_count_update = current_time

    def _delayed_device_count_log(self):
        """延迟输出设备计数日志"""
        if self._pending_device_count > 0 and self.log_presenter:
            log_message = f"网络中有 {self._pending_device_count} 个设备在线"
            self.log_presenter.add_log(log_message, "🔍")

    def _schedule_ui_update(self, update_type: str):
        """调度UI更新 - 批量处理以提高性能"""
        self._pending_ui_updates.add(update_type)

        # 如果已有定时器在运行，不需要重新创建
        if self._ui_update_timer and self._ui_update_timer.isActive():
            return

        # 自适应调整更新频率
        update_interval = self._get_adaptive_update_interval()

        self._ui_update_timer = QTimer()
        self._ui_update_timer.setSingleShot(True)
        self._ui_update_timer.timeout.connect(self._process_pending_ui_updates)
        self._ui_update_timer.start(update_interval)

    def _get_adaptive_update_interval(self) -> int:
        """固定快速更新间隔，不再自适应调整"""
        return 16  # 约60 FPS，提供流畅的用户体验

    def _process_pending_ui_updates(self):
        """处理待处理的UI更新"""
        if not self._pending_ui_updates:
            return

        # 批量处理所有待处理的更新
        updates_to_process = self._pending_ui_updates.copy()
        self._pending_ui_updates.clear()

        for update_type in updates_to_process:
            if update_type == "device_count":
                self._update_device_count_status()
            # 可以在这里添加其他类型的UI更新

        # 如果还有待处理的更新，继续调度
        if self._pending_ui_updates:
            self._schedule_ui_update(next(iter(self._pending_ui_updates)))

    def _schedule_device_batch_processing(self):
        """调度设备批量处理"""
        # 如果已有定时器在运行，不需要重新创建
        if self._device_batch_timer and self._device_batch_timer.isActive():
            return

        # 使用固定的快速处理间隔，不再根据设备数量调整
        batch_interval = 10  # 10ms快速处理，提高响应速度

        self._device_batch_timer = QTimer()
        self._device_batch_timer.setSingleShot(True)
        self._device_batch_timer.timeout.connect(self._process_device_batch)
        self._device_batch_timer.start(batch_interval)

    def _process_device_batch(self):
        """批量处理设备事件"""
        if not self._pending_device_events:
            return

        # 启用批量更新模式
        self.device_model.enable_batch_updates()

        try:
            # 处理所有待处理的设备事件
            events_to_process = self._pending_device_events.copy()
            self._pending_device_events.clear()

            my_service_name = f"{self.controller.service_name}._netneighbor._tcp.local."

            for event, data in events_to_process:
                if event == "peer_online":
                    # 检查是否为本机设备
                    if data["name"] != my_service_name:
                        # 添加设备（非本机）
                        self.device_model.add_device(data["name"], data["data"])

                        # 添加设备上线日志通知
                        device_display_name = data["name"].split(
                            "._netneighbor._tcp.local."
                        )[0]
                        if self.log_presenter:
                            self.log_presenter.add_log(
                                f"设备上线: {device_display_name}", "🟢"
                            )

                elif event == "peer_offline":
                    # 获取设备显示名称（在移除前）
                    device_display_name = data["name"].split(
                        "._netneighbor._tcp.local."
                    )[0]

                    # 移除设备
                    self.device_model.remove_device(data["name"])

                    # 添加设备下线日志通知
                    if self.log_presenter:
                        self.log_presenter.add_log(
                            f"设备下线: {device_display_name}", "🔴"
                        )

        finally:
            # 禁用批量更新模式，触发UI更新
            self.device_model.disable_batch_updates()

            # 批量更新UI
            self._schedule_ui_update("device_count")

    def _is_transferring(self):
        """检查是否正在传输文件"""
        return self.transfer_model.is_transfer_active()

    def _refresh_files(self):
        """刷新文件列表"""
        # 延迟刷新文件列表，避免频繁刷新
        if self.file_browser_presenter:
            self.file_browser_presenter._refresh_files()
        elif self.log_presenter:
            self.log_presenter.add_log("文件浏览器Presenter未初始化", "❌")
        else:
            print("警告: 文件浏览器和日志组件均未初始化")

    def _refresh_shares(self):
        """刷新共享列表"""
        client = self.connection_model.get_active_peer_client()
        if not client:
            return

        shares = client.get_shares()
        if shares is not None:
            self.remote_share_model.set_shares(shares)

    def _on_permission_change(self, share_name: str, perm: str, checked: bool):
        """处理权限变更"""
        config = load_config(force_reload=True)
        if not config:
            return

        for share in config.get("shares", []):
            if share.get("name") == share_name:
                if "permissions" not in share:
                    share["permissions"] = ["read"]
                if checked and perm not in share["permissions"]:
                    share["permissions"].append(perm)
                elif not checked and perm in share["permissions"]:
                    share["permissions"].remove(perm)
                break

        try:
            import toml

            # 使用CONFIG_PATH而不是controller.config_path
            from core.config_loader import CONFIG_PATH

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                toml.dump(config, f)
            self.controller.running_config = config
            self.share_model.reload_shares()

            # 通知共享变更
            client = self.connection_model.get_local_api_client()
            if client:
                client.notify_shares_changed()

            self.log_presenter.add_log(f"共享 '{share_name}' 的权限已更新。", "🔧")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")

    def _on_remove_share(self, share_name: str):
        """处理移除共享"""
        reply = QMessageBox.question(
            self,
            "确认移除",
            f"确定要停止共享 '{share_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        config = load_config(force_reload=True)
        config["shares"] = [
            s for s in config.get("shares", []) if s.get("name") != share_name
        ]

        try:
            import toml

            # 使用CONFIG_PATH而不是controller.config_path
            from core.config_loader import CONFIG_PATH

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                toml.dump(config, f)

            self.controller.running_config = config
            self.share_model.reload_shares()
            self.controller.restart_file_watcher()

            # 通知共享变更
            client = self.connection_model.get_local_api_client()
            if client:
                client.notify_shares_changed()

            self.log_presenter.add_log(f"已停止共享: {share_name}", "️")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")

    def _on_upload_file(self, file_paths: List[str], share_name: str, dest_path: str):
        """处理上传文件"""
        tasks = self.transfer_manager.create_upload_file_tasks(
            file_paths, share_name, dest_path
        )
        if tasks:
            # 显示传输列表视图
            self._show_transfer_dialog(f"上传 {len(file_paths)} 个文件", tasks)

    def _on_upload_folder(self, folder_path: str, share_name: str, dest_path: str):
        """处理上传文件夹"""
        task = self.transfer_manager.create_upload_folder_task(
            folder_path, share_name, dest_path
        )
        if task:
            # 显示传输列表视图
            self._show_transfer_dialog("上传文件夹", [task])

    def _on_download(
        self,
        files: List[Dict[str, Any]],
        share_name: str,
        remote_path: str,
        save_dir: str,
    ):
        """处理下载"""
        tasks = self.transfer_manager.create_download_tasks(
            files, share_name, remote_path, save_dir
        )
        if tasks:
            # 显示传输列表视图
            self._show_transfer_dialog(f"下载 {len(files)} 个项目", tasks)

    def _on_rename(self, old_name: str, new_name: str, share_name: str, path: str):
        """处理重命名"""
        client = self.connection_model.get_active_peer_client()
        if not client:
            return

        try:
            remote_path = f"{path}/{old_name}".replace("//", "/")
            result = client.rename_file(share_name, remote_path, new_name)

            if result:
                self.log_presenter.add_log(f"已重命名: {old_name} -> {new_name}", "✏️")

                # 刷新文件列表
                self._refresh_files()

                # 不需要手动通知文件变更，因为远程服务器的重命名API会自动广播事件
            else:
                QMessageBox.critical(
                    self, "错误", f"重命名失败: {old_name}", QMessageBox.Ok
                )
        except Exception as e:
            self.log_presenter.add_log(f"重命名时出错: {e}", "❌")
            QMessageBox.critical(self, "错误", f"重命名失败: {str(e)}", QMessageBox.Ok)

    def _on_delete(self, file_names: List[str], share_name: str, path: str):
        """处理删除"""
        client = self.connection_model.get_active_peer_client()
        if not client:
            return

        success_count = 0
        error_count = 0

        for name in file_names:
            try:
                remote_path = f"{path}/{name}".replace("//", "/")
                result = client.delete_file(share_name, remote_path)

                if result:
                    self.log_presenter.add_log(f"已删除: {name}", "🗑️")
                    success_count += 1
                else:
                    self.log_presenter.add_log(f"删除失败: {name}", "❌")
                    error_count += 1
            except Exception as e:
                self.log_presenter.add_log(f"删除 {name} 时出错: {e}", "❌")
                error_count += 1

        # 刷新文件列表
        self._refresh_files()

        # 不需要手动通知文件变更，因为远程服务器的删除API会自动广播事件

        # 显示操作结果
        if error_count == 0:
            self.status_bar_label.setText(f"成功删除 {success_count} 个项目")
        else:
            self.status_bar_label.setText(
                f"删除完成: {success_count} 成功, {error_count} 失败"
            )
            QMessageBox.warning(
                self,
                "删除结果",
                f"成功删除 {success_count} 个项目，{error_count} 个项目删除失败。",
                QMessageBox.Ok,
            )

    def _on_transfer_completed(self):
        """处理传输完成"""
        # 刷新文件列表
        QTimer.singleShot(500, self._refresh_files)

    def _on_transfer_error(self, error_message: str):
        """处理传输错误"""
        # 错误已在TransferPresenter中处理
        pass

    def _open_settings(self):
        """打开设置窗口"""
        # 懒导入设置窗口
        from gui.settings_window import SettingsWindow

        dialog = SettingsWindow(self.controller, self)
        if dialog.exec():
            self.controller.running_config = load_config(force_reload=True)
            self.share_model.reload_shares()
            self.controller.restart_file_watcher()

            # 通知共享变更
            client = self.connection_model.get_local_api_client()
            if client:
                client.notify_shares_changed()

            self.log_presenter.add_log("配置已更新。", "⚙️")
            QMessageBox.information(
                self, "设置已保存", "设置已成功保存。", QMessageBox.Ok
            )

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 邻里+",
            """<b>邻里+ (NetNeighbor Plus) v3.4.0</b>
            <p>一款基于局域网的、开源的、跨平台文件共享工具。</p>
            <p><b>核心功能:</b></p>
            <ul>
                <li>自动发现局域网内的其他设备</li>
                <li>支持文件和文件夹的上传与下载</li>
                <li>灵活的文件夹权限管理 (可读/可下载/可上传)</li>
                <li>实时文件变更监控与通知</li>
                <li>跨平台支持 (Windows, macOS, Linux)</li>
            </ul>
            <p>感谢您的使用！</p>
            """,
        )

    def _on_task_added(self, task_id: str, task_info: Dict[str, Any]):
        """处理任务添加"""
        # 处理位置更新请求
        if task_id == "update_position":
            self._update_floating_window_position()
            return

        # 更新传输状态按钮
        self._update_transfer_status_button()

    def _on_task_progress(self, task_id: str, progress: int):
        """处理任务进度更新"""
        # 更新传输状态按钮
        self._update_transfer_status_button()

    def _on_task_status(self, task_id: str, status: str):
        """处理任务状态更新"""
        # 更新传输状态按钮
        self._update_transfer_status_button()

    def _on_task_completed(self, task_id: str):
        """处理任务完成"""
        # 刷新文件列表
        QTimer.singleShot(500, self._refresh_files)
        # 更新传输状态按钮
        self._update_transfer_status_button()

    def _on_task_error(self, task_id: str, error_message: str):
        """处理任务错误"""
        # 错误已在TransferManager中处理
        # 更新传输状态按钮
        self._update_transfer_status_button()

    def _on_all_tasks_completed(self):
        """处理所有任务完成"""
        # 如果没有活动任务，隐藏传输状态按钮
        task_count = self.floating_transfer_view.get_task_count()
        if task_count == 0:
            # 隐藏传输状态按钮
            self.transfer_status_button.setVisible(False)

    def _update_transfer_status_button(self):
        """更新传输状态按钮"""
        task_count = self.floating_transfer_view.get_task_count()
        if task_count > 0:
            self.transfer_status_button.setText(f"传输: {task_count}")
            self.transfer_status_button.setVisible(True)

            # 根据是否有活动任务设置不同样式
            if self.transfer_model.is_transfer_active():
                self.transfer_status_button.setStyleSheet(
                    """
                    QPushButton {
                        border: none;
                        padding: 2px 8px;
                        background-color: #4CAF50;
                        border-radius: 3px;
                        color: white;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                    }
                """
                )
            else:
                self.transfer_status_button.setStyleSheet(
                    """
                    QPushButton {
                        border: none;
                        padding: 2px 8px;
                        background-color: #f0f0f0;
                        border-radius: 3px;
                        color: #333;
                    }
                    QPushButton:hover {
                        background-color: #e0e0e0;
                    }
                """
                )
        else:
            self.transfer_status_button.setVisible(False)

    def _show_transfer_dialog(self, title: str, tasks: List[Dict[str, Any]]):
        """显示传输对话框"""
        # 添加任务
        self.transfer_manager.add_tasks(title, tasks, silent=False)

        # 确保传输状态按钮可见
        self._update_transfer_status_button()

    def _toggle_transfer_list(self):
        """切换传输列表视图的显示状态"""
        if not self.floating_transfer_view.isVisible():
            # 先设置位置，再显示窗口
            self._update_floating_window_position()
            self.floating_transfer_view.setVisible(True)
        else:
            self.floating_transfer_view.setVisible(False)

    def _update_floating_window_position(self):
        """更新悬浮窗口位置到应用程序右下角"""
        if self.floating_transfer_view and self.floating_transfer_view.isVisible():
            # 获取主窗口的位置和大小
            main_pos = self.mapToGlobal(QPoint(0, 0))
            main_size = self.size()

            # 获取悬浮窗口的大小
            float_size = self.floating_transfer_view.sizeHint()

            # 计算悬浮窗口的位置（主窗口右下角）
            float_x = main_pos.x() + main_size.width() - float_size.width() - 20
            float_y = main_pos.y() + main_size.height() - float_size.height() - 20

            # 确保位置在屏幕内
            screen_rect = self.screen().availableGeometry()
            if float_x < 0:
                float_x = 10
            if float_y < 0:
                float_y = 10
            if float_x + float_size.width() > screen_rect.width():
                float_x = screen_rect.width() - float_size.width() - 10
            if float_y + float_size.height() > screen_rect.height():
                float_y = screen_rect.height() - float_size.height() - 10

            # 设置悬浮窗口位置
            self.floating_transfer_view.move(float_x, float_y)

            # 确保窗口在前端显示
            self.floating_transfer_view.raise_()

    def resizeEvent(self, event):
        """处理窗口大小变化事件"""
        super().resizeEvent(event)
        # 更新悬浮窗口位置
        self._update_floating_window_position()

    def moveEvent(self, event):
        """处理窗口移动事件"""
        super().moveEvent(event)
        # 更新悬浮窗口位置
        self._update_floating_window_position()

    def closeEvent(self, event: QCloseEvent):
        """处理窗口关闭事件"""
        # 检查是否有传输任务正在进行
        if self.transfer_model.is_transfer_active():
            reply = QMessageBox.question(
                self,
                "退出确认",
                "有文件正在传输，确定要强制退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        self.log_presenter.add_log("应用正在关闭...", "👋")

        # 停止所有连接
        self.connection_presenter.stop_all_connections()

        # 停止后台服务
        self.controller.stop_all_services()

        self.log_presenter.add_log("所有服务和线程已停止。应用退出。", "👋")
        event.accept()

    def _on_new_folder(self, dir_name: str, share_name: str, path: str):
        """处理新建文件夹"""
        client = self.connection_model.get_active_peer_client()
        if not client:
            return

        try:
            result = client.create_directory(share_name, path, dir_name)
            if result:
                if self.log_presenter:
                    self.log_presenter.add_log(f"已在远程创建文件夹: {dir_name}", "📁")
                # 成功后立即刷新文件列表
                self._refresh_files()
            else:
                QMessageBox.critical(self, "错误", f"创建文件夹 '{dir_name}' 失败。")

        except Exception as e:
            if self.log_presenter:
                self.log_presenter.add_log(f"创建文件夹时出错: {e}", "❌")
            QMessageBox.critical(self, "错误", f"创建文件夹失败: {str(e)}")
