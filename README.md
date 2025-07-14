# 邻里+ (NetNeighbor Plus)

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-GUI-green.svg)](https://doc.qt.io/qtforpython/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-red.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-Open%20Source-brightgreen.svg)](#)

一款基于局域网的、开源的、跨平台文件共享工具。通过零配置的设备发现和高效的文件传输，让局域网内的设备间文件共享变得简单快捷。

## ✨ 核心特性

### 🔍 自动设备发现
- 基于 **mDNS/Zeroconf** 协议的零配置设备发现
- 自动识别局域网内运行 NetNeighbor Plus 的设备
- 实时显示设备上线/下线状态
- 支持设备类型识别（PC、移动设备等）

### 📁 灵活的文件共享
- **多权限级别**：可读、可下载、可上传
- **文件夹级别共享**：精确控制每个共享文件夹的权限
- **实时文件监控**：自动检测文件变更并通知连接的设备
- **安全路径验证**：防止路径遍历攻击

### 🚀 高效文件传输
- **双协议支持**：
  - HTTP API：适用于小文件和常规操作
  - TCP 高速传输：专为大文件和文件夹下载优化
- **流式传输**：支持大文件的流式上传下载
- **断点续传**：网络中断后可恢复传输
- **实时进度显示**：详细的传输进度和速度信息

### 🎨 现代化用户界面
- **MVC 架构**：清晰的代码结构，易于维护和扩展
- **响应式设计**：自适应不同屏幕尺寸
- **实时日志**：详细的操作日志和状态信息
- **拖拽支持**：直接拖拽文件到界面进行上传

## 🏗️ 技术架构

### 后端技术栈
- **FastAPI**：现代化的 Web API 框架
- **Uvicorn**：高性能 ASGI 服务器
- **WebSocket**：实时双向通信
- **AsyncIO**：异步 I/O 处理
- **Zeroconf**：设备发现服务

### 前端技术栈
- **PySide6 (Qt6)**：跨平台 GUI 框架
- **MVC 模式**：模型-视图-控制器架构
- **事件总线**：解耦的组件间通信
- **多线程**：非阻塞的用户界面

### 核心模块

#### 🔧 Core 模块
```
core/
├── config_loader.py    # 配置管理（TOML格式）
├── discovery.py        # 设备发现服务
├── event_bus.py        # 事件总线系统
├── file_watcher.py     # 文件系统监控
├── tcp_server.py       # TCP高速传输服务
└── web_api.py          # REST API服务
```

#### 🖥️ GUI 模块
```
gui/
├── models/             # 数据模型层
│   ├── device_model.py     # 设备数据管理
│   ├── file_model.py       # 文件数据管理
│   ├── share_model.py      # 共享配置管理
│   └── connection_model.py # 连接状态管理
├── views/              # 视图层
│   ├── device_list_view.py # 设备列表界面
│   ├── file_browser_view.py # 文件浏览器界面
│   └── transfer_list_view.py # 传输列表界面
├── presenters/         # 控制器层
│   ├── device_presenter.py # 设备列表控制器
│   ├── file_browser_presenter.py # 文件浏览控制器
│   └── connection_presenter.py # 连接管理控制器
└── app_controller.py   # 应用主控制器
```

## 🚀 快速开始

### 环境要求
- Python 3.9+
- 支持的操作系统：Windows、macOS、Linux

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行应用
```bash
python run_app.py
```

### 命令行参数
```bash
# 指定端口运行（用于多实例测试）
python run_app.py --port 8081
python run_app.py 8082  # 位置参数形式
```

## 📖 使用指南

### 1. 首次运行
- 应用会自动创建配置文件：
  - Windows: `%APPDATA%/NetNeighbor_Plus/config.toml`
  - Linux/macOS: `~/.config/NetNeighbor_Plus/config.toml`

### 2. 配置共享文件夹
1. 点击 "设置" 按钮
2. 添加要共享的文件夹
3. 设置权限：可读、可下载、可上传
4. 保存配置

### 3. 连接其他设备
1. 确保设备在同一局域网内
2. 在设备列表中选择要连接的设备
3. 浏览远程设备的共享文件夹
4. 进行文件上传/下载操作

### 4. 文件传输
- **上传**：拖拽文件到文件浏览器或使用上传按钮
- **下载**：选择文件后点击下载按钮
- **文件夹下载**：自动使用 TCP 高速传输模式

## 🔧 配置文件

配置文件使用 TOML 格式：

```toml
[service]
name = "我的电脑"
port = 8080

[[shares]]
name = "文档"
path = "/home/user/Documents"
permissions = ["read", "download"]

[[shares]]
name = "共享文件夹"
path = "/home/user/Shared"
permissions = ["read", "download", "upload"]
```

### 权限说明
- **read**: 允许浏览文件夹内容
- **download**: 允许下载文件
- **upload**: 允许上传文件到该文件夹

## 🌐 网络协议

### HTTP API 端点
- `GET /api/v1/shares` - 获取共享列表
- `GET /api/v1/peers` - 获取在线设备列表
- `GET /api/v1/files/{share_name}` - 浏览文件夹内容
- `POST /api/v1/upload/{share_name}` - 上传文件
- `GET /api/v1/download/{share_name}` - 下载文件
- `WebSocket /ws/events` - 实时事件通信

### TCP 高速传输
- 专用端口：HTTP端口 + 1（如8081）
- 用于大文件和文件夹的高速下载
- 支持流式传输和进度反馈

### 设备发现协议
- 服务类型：`_netneighbor._tcp.local.`
- 自动广播设备信息和能力
- 支持设备属性传递（操作系统、用户名等）

## 🧪 开发和测试

### 性能测试
项目包含设备发现性能测试工具：
```bash
python simulator.py
```
该工具可以模拟多个设备上线，测试应用的性能表现。

### 代码结构
- 遵循 PEP 8 编码规范
- 使用类型提示增强代码可读性
- 模块化设计，便于单元测试
- 事件驱动架构，降低组件耦合度

## 🔒 安全特性

### 路径安全
- 严格的路径验证，防止目录遍历攻击
- 共享文件夹边界检查
- 文件名安全性验证

### 网络安全
- 仅限局域网访问
- 无需外网连接
- 权限级别控制

### 数据完整性
- 文件传输校验
- 异常处理和恢复
- 传输状态监控

## 📊 性能特点

### 传输性能
- **小文件**: HTTP API，响应快速
- **大文件**: TCP 流式传输，高吞吐量
- **文件夹**: 自动 TAR 打包，减少网络开销

### 内存优化
- 流式处理，避免大文件占用内存
- 异步 I/O，提高并发性能
- 智能缓存机制

### 用户体验
- 非阻塞界面，操作流畅
- 实时进度反馈
- 智能错误恢复

## ❓ 常见问题

### Q: 为什么看不到其他设备？
A: 请确保：
- 所有设备在同一局域网内
- 防火墙允许应用通信
- 网络支持 mDNS 协议

### Q: 文件传输失败怎么办？
A: 检查：
- 目标文件夹权限设置
- 磁盘空间是否充足
- 网络连接是否稳定

### Q: 如何提高传输速度？
A: 建议：
- 使用有线网络连接
- 关闭不必要的网络应用
- 大文件会自动使用 TCP 高速模式

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境设置
1. Fork 本仓库
2. 创建功能分支
3. 提交更改
4. 创建 Pull Request

### 代码贡献规范
- 遵循现有代码风格
- 添加必要的类型提示
- 编写清晰的提交信息
- 更新相关文档

## 🔄 版本历史

### v3.3.0 (当前版本)
- ✨ 完整的 MVC 架构重构
- 🚀 TCP 高速传输支持
- 📱 响应式用户界面
- 🔍 优化的设备发现机制
- 📊 实时传输进度显示

### 主要里程碑
- **v3.0**: 引入 FastAPI 后端架构
- **v2.0**: 添加 WebSocket 实时通信
- **v1.0**: 基础文件共享功能

## 🛠️ 故障排除

### 常见错误及解决方案

#### 端口占用错误
```bash
# 使用不同端口启动
python run_app.py --port 8081
```

#### 设备发现问题
1. 检查防火墙设置
2. 确认网络支持组播
3. 重启网络服务

#### 传输中断
- 检查网络连接稳定性
- 确认目标设备在线
- 重新尝试连接

## 📄 许可证

本项目采用开源许可证，详情请查看 LICENSE 文件。

## 🙏 致谢

感谢以下开源项目的支持：
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Web 框架
- [PySide6](https://doc.qt.io/qtforpython/) - Python Qt 绑定
- [Zeroconf](https://github.com/python-zeroconf/python-zeroconf) - 设备发现服务
- [Watchdog](https://github.com/gorakhargosh/watchdog) - 文件系统监控

---

**邻里+ (NetNeighbor Plus) v3.3.0** - 让局域网文件共享更简单！
