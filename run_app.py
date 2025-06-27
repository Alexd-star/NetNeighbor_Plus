# 文件: run_app.py
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from gui.main_window import MainWindow
from gui.app_controller import AppController

if __name__ == "__main__":
    # 允许通过命令行覆盖端口，用于单机多实例测试
    port_override = None
    if len(sys.argv) > 1:
        try:
            port_override = int(sys.argv[1])
            print(f"检测到端口覆盖参数，将尝试在端口 {port_override} 上启动服务。")
        except ValueError:
            print("警告：端口参数无效，将使用配置文件中的默认端口。")

    # 1. 创建Qt应用实例
    app = QApplication(sys.argv)

    # 加载QSS样式表美化UI
    try:
        with open("gui/style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("警告：未找到 gui/style.qss 样式文件，将使用默认样式。")

    # 2. 创建唯一的应用总控制器
    controller = AppController(port_override=port_override)

    # 3. 创建主窗口，并将总控制器传递给它
    window = MainWindow(controller)

    # 4. 将后台服务的启动和UI的后续初始化连接起来
    #    确保服务完全启动后，UI才开始进行网络活动
    controller.server_started.connect(window.post_init_setup)

    # 5. 使用QTimer异步启动后台服务，防止阻塞UI
    QTimer.singleShot(100, controller.start_all_services)

    # 6. 显示主窗口
    window.show()

    # 7. 运行Qt事件循环，并在结束后退出
    sys.exit(app.exec())