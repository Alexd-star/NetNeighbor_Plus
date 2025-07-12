#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

    app = QApplication(sys.argv)

    # 加载QSS样式表美化UI
    try:
        with open("gui/style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("警告：未找到 gui/style.qss 样式文件，将使用默认样式。")
    
    # 创建应用总控制器
    controller = AppController(port_override=port_override)
    
    # 启动所有后台服务
    controller.start_all_services()
    
    # 创建并显示主窗口
    window = MainWindow(controller)
    window.show()
    window.post_init_setup()
    
    # 启动事件循环
    exit_code = app.exec()
    
    # 关闭所有服务
    controller.stop_all_services()
    
    sys.exit(exit_code)