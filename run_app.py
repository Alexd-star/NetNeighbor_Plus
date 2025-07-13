#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import argparse
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from gui.main_window_mvc import MainWindowMVC
from gui.app_controller import AppController

if __name__ == "__main__":
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="NetNeighbor Plus 文件共享应用")
    parser.add_argument("--port", type=int, help="服务器端口号，用于单机多实例测试")
    parser.add_argument("port_pos", type=int, nargs='?', help="服务器端口号（位置参数）")
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 获取端口号（优先使用位置参数）
    port_override = args.port_pos if args.port_pos is not None else args.port
    if port_override:
        print(f"检测到端口覆盖参数，将尝试在端口 {port_override} 上启动服务。")
        
    # 创建应用
    app = QApplication(sys.argv)

    # 加载QSS样式表美化UI
    try:
        with open("gui/style.qss", "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("警告：未找到 gui/style.qss 样式文件，将使用默认样式。")
    
    # 创建应用总控制器
    controller = AppController(port_override=port_override)
    
    # 启动所有后台服务
    controller.start_all_services()
    
    # 创建并显示主窗口
    window = MainWindowMVC(controller)
    window.show()
    window.post_init_setup()
    
    # 启动事件循环
    exit_code = app.exec()
    
    # 关闭所有服务
    controller.stop_all_services()
    
    sys.exit(exit_code)