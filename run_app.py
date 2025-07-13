#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import traceback
import argparse

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.app_controller import AppController
from gui.main_window_mvc import MainWindowMVC


# 异常处理函数
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
    # 设置全局异常处理
    sys._excepthook = sys.excepthook

    def exception_hook(exception_type, exception_value, exception_traceback):
        sys._excepthook(exception_type, exception_value, exception_traceback)
        show_exception_box(exception_type, exception_value, exception_traceback)
        sys.exit(1)

    sys.excepthook = exception_hook

    try:
        # 创建命令行参数解析器
        parser = argparse.ArgumentParser(description="NetNeighbor Plus 文件共享应用")
        parser.add_argument("--port", type=int, help="服务器端口号，用于单机多实例测试")
        parser.add_argument(
            "port_pos", type=int, nargs="?", help="服务器端口号（位置参数）"
        )

        # 解析命令行参数
        args = parser.parse_args()

        # 获取端口号（优先使用位置参数）
        port_override = args.port_pos if args.port_pos is not None else args.port
        if port_override:
            print(f"检测到端口覆盖参数，将尝试在端口 {port_override} 上启动服务。")

        # 创建应用
        app = QApplication(sys.argv)

        # 创建应用总控制器
        controller = AppController(port_override=port_override)

        # 创建并显示主窗口
        window = MainWindowMVC(controller)

        # 延迟加载样式表，避免启动时阻塞UI
        def load_style_sheet():
            try:
                with open("gui/style.qss", "r", encoding="utf-8") as f:
                    app.setStyleSheet(f.read())
            except FileNotFoundError:
                print("警告：未找到 gui/style.qss 样式文件，将使用默认样式。")

        # 使用QTimer延迟启动非关键服务
        def delayed_startup():
            try:
                # 启动所有后台服务
                controller.start_all_services()
                # 在UI显示后执行post_init_setup
                window.post_init_setup()
            except Exception as e:
                print(f"启动服务时出错: {e}")
                traceback.print_exc()

        # 先显示窗口，然后再加载样式和启动服务
        window.show()

        # 立即加载样式表
        load_style_sheet()

        # 延迟100毫秒启动后台服务
        QTimer.singleShot(100, delayed_startup)

        # 启动事件循环
        exit_code = app.exec()

        # 关闭所有服务
        controller.stop_all_services()

        sys.exit(exit_code)

    except Exception as e:
        print(f"应用程序启动失败: {e}")
        traceback.print_exc()

        # 如果QApplication已经创建，则显示错误对话框
        if "app" in locals():
            show_exception_box(type(e), e, e.__traceback__)

        sys.exit(1)
