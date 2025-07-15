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
    # 在Windows上，确保子进程也不会显示控制台窗口
    if sys.platform == "win32":
        # 设置默认的subprocess创建标志，影响所有子进程
        import subprocess

        subprocess._subprocess_main = getattr(subprocess, "_subprocess_main", None)

        # 保存原始的Popen类
        original_popen = subprocess.Popen

        # 创建一个新的Popen类，自动添加CREATE_NO_WINDOW标志
        class NoConsoleWindowPopen(original_popen):
            def __init__(self, *args, **kwargs):
                if "creationflags" not in kwargs:
                    kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                super().__init__(*args, **kwargs)

        # 替换原始的Popen类
        subprocess.Popen = NoConsoleWindowPopen

    if getattr(sys, "frozen", False):
        # 打包后的应用，重定向输出到文件（静默模式）
        try:
            import os
            import datetime

            # 创建日志目录
            log_dir = os.path.join(os.path.expanduser("~"), ".netneighbor")
            os.makedirs(log_dir, exist_ok=True)

            # 重定向到日志文件
            log_file = os.path.join(log_dir, "app.log")

            # 使用文件作为标准输出，但不显示控制台
            log_handle = open(log_file, "w", encoding="utf-8")
            sys.stdout = log_handle
            sys.stderr = log_handle

            # 写入启动信息
            print(f"邻里+ 启动时间: {datetime.datetime.now()}")
            print("=" * 60)
            print(f"系统平台: {sys.platform}")
            print(f"Python版本: {sys.version}")
            print("=" * 60)

        except Exception as e:
            # 如果文件日志也失败，就完全静默运行
            import os

            null_device = os.devnull
            sys.stdout = open(null_device, "w")
            sys.stderr = sys.stdout
    else:
        print("开发环境，使用标准输出")

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
