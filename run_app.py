"""
应用程序启动入口，负责初始化和启动NetNeighbor Plus
"""

import sys
import traceback
import argparse

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox


def show_exception_box(exception_type, exception_value, exception_traceback):
    """显示异常对话框"""
    traceback_format = traceback.format_exception(
        exception_type, exception_value, exception_traceback
    )
    traceback_string = "".join(traceback_format)

    error_box = QMessageBox()
    error_box.setIcon(QMessageBox.Icon.Critical)
    error_box.setWindowTitle("应用程序错误")
    error_box.setText("程序遇到了一个错误，无法继续执行。")
    error_box.setInformativeText(str(exception_value))
    error_box.setDetailedText(traceback_string)
    error_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    error_box.exec()


if __name__ == "__main__":
    sys._excepthook = sys.excepthook

    def exception_hook(exception_type, exception_value, exception_traceback):
        sys._excepthook(exception_type, exception_value, exception_traceback)
        show_exception_box(exception_type, exception_value, exception_traceback)
        sys.exit(1)

    sys.excepthook = exception_hook

    try:
        parser = argparse.ArgumentParser(description="NetNeighbor Plus 文件共享应用")
        parser.add_argument("--port", type=int, help="服务器端口号，用于单机多实例测试")
        parser.add_argument(
            "port_pos", type=int, nargs="?", help="服务器端口号（位置参数）"
        )

        args = parser.parse_args()

        port_override = args.port_pos if args.port_pos is not None else args.port
        if port_override:
            print(f"检测到端口覆盖参数，将尝试在端口 {port_override} 上启动服务。")

        app = QApplication(sys.argv)

        # 懒导入关键模块，减少启动时间
        from gui.app_controller import AppController
        from gui.main_window_mvc import MainWindowMVC

        controller = AppController(port_override=port_override)

        window = MainWindowMVC(controller)

        def delayed_startup():
            try:
                controller.start_all_services()
                window.post_init_setup()
            except Exception as e:
                print(f"启动服务时出错: {e}")
                traceback.print_exc()

        window.show()

        # 样式表加载已移至MainWindowMVC中，避免重复加载

        # 减少启动延迟，加快应用响应
        QTimer.singleShot(50, delayed_startup)

        exit_code = app.exec()

        controller.stop_all_services()

        sys.exit(exit_code)

    except Exception as e:
        print(f"应用程序启动失败: {e}")
        traceback.print_exc()

        if "app" in locals():
            show_exception_box(type(e), e, e.__traceback__)

        sys.exit(1)
