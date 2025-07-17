# -*- mode: python ; coding: utf-8 -*-
"""
NetNeighbor Plus PyInstaller 配置文件
优化的打包配置，兼顾兼容性、大小和稳定性
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 获取项目根目录
project_root = os.path.dirname(os.path.abspath(SPEC))

# 分析主程序
a = Analysis(
    ['run_app.py'],
    pathex=[project_root],
    binaries=[],
    datas=[
        # 包含样式文件
        ('gui/style.qss', 'gui'),
        # 包含配置模板（如果有的话）
        # ('config_template.toml', '.'),
    ],
    hiddenimports=[
        # PySide6 GUI框架
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtWidgets',
        'PySide6.QtGui',
        'PySide6.QtNetwork',

        # Web框架和服务器
        'fastapi',
        'fastapi.applications',
        'fastapi.responses',
        'fastapi.routing',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.dependencies',
        'fastapi.exceptions',
        'fastapi.encoders',
        'starlette',              # FastAPI 基于 starlette
        'starlette.applications',
        'starlette.responses',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.base',
        'starlette.middleware.cors',
        'starlette.exceptions',
        'starlette.requests',
        'starlette.datastructures',
        'uvicorn',
        'uvicorn.config',
        'uvicorn.main',
        'uvicorn.server',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.websockets_impl',

        # HTTP客户端
        'httpx',
        'httpx._client',
        'httpx._transports',
        'httpx._transports.default',
        'httpx._auth',
        'httpx._config',

        # 设备发现 - zeroconf 完整模块列表
        'zeroconf',
        'zeroconf._cache',
        'zeroconf._core',
        'zeroconf._dns',
        'zeroconf._engine',
        'zeroconf._exceptions',
        'zeroconf._handlers',
        'zeroconf._handlers.answers',
        'zeroconf._handlers.multicast_outgoing_queue',
        'zeroconf._handlers.query_handler',
        'zeroconf._handlers.record_manager',
        'zeroconf._history',
        'zeroconf._listener',
        'zeroconf._logger',
        'zeroconf._protocol',
        'zeroconf._protocol.incoming',
        'zeroconf._protocol.outgoing',
        'zeroconf._record_update',
        'zeroconf._services',
        'zeroconf._services.browser',
        'zeroconf._services.info',
        'zeroconf._services.registry',
        'zeroconf._services.types',
        'zeroconf._transport',
        'zeroconf._updates',
        'zeroconf._utils',
        'zeroconf._utils.asyncio',
        'zeroconf._utils.ipaddress',
        'zeroconf._utils.name',
        'zeroconf._utils.net',
        'zeroconf._utils.time',
        'zeroconf.asyncio',
        'zeroconf.const',

        # WebSocket通信 - 添加更多必需模块
        'websockets',
        'websockets.asyncio',
        'websockets.asyncio.client',
        'websockets.asyncio.server',
        'websockets.asyncio.connection',
        'websockets.server',
        'websockets.client',
        'websockets.protocol',
        'websockets.exceptions',
        'websockets.extensions',
        'websockets.extensions.base',

        # 文件监控
        'watchdog',
        'watchdog.events',
        'watchdog.observers',

        # 并发处理
        'concurrent',
        'concurrent.futures',

        # 其他必需依赖
        'toml',           # 配置文件解析
        'tarfile',        # 文件打包
        'multipart',      # 文件上传处理 (python-multipart)
        'multipart.multipart',
        'multipart.decoders',
        'zipstream',      # 流式ZIP压缩 (zipstream-ng)
        'zipstream.ng',

        # 项目模块
        'core',
        'core.config_loader',
        'core.discovery',
        'core.web_api',
        'core.tcp_server',
        'core.event_bus',
        'core.file_watcher',
        'core.path_utils',
        'core.tar_worker',
        'core.error_handler',
        'gui',
        'gui.app_controller',
        'gui.main_window_mvc',
        'gui.api_client',
        'gui.websocket_client',
        'gui.worker_thread',
        'gui.settings_window',
        'gui.conflict_resolver',
        'gui.models',
        'gui.views',
        'gui.presenters',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的模块以减小体积
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'PIL',
        'cv2',
        'tensorflow',
        'torch',
        'jupyter',
        'IPython',
        'notebook',
        'pytest',
        'unittest',
        'doctest',
        'pdb',
        'profile',
        'pstats',
        'cProfile',
        'sqlite3',  # 如果不使用数据库
        'xml.etree.ElementTree',  # 如果不使用XML
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 暂时禁用自动数据文件收集，避免格式问题
# pyside6_datas = collect_data_files('PySide6')
# a.datas += pyside6_datas

# uvicorn_datas = collect_data_files('uvicorn')
# a.datas += uvicorn_datas

# 过滤掉不必要的文件以减小体积
def filter_binaries(binaries):
    """过滤二进制文件，移除不必要的库"""
    filtered = []
    exclude_patterns = [
        'api-ms-win-',  # Windows API集
        'ucrtbase',     # 通用C运行时（通常系统已有）
        'msvcp',        # Visual C++运行时（通常系统已有）
        'vcruntime',    # Visual C++运行时（通常系统已有）
    ]
    
    for binary in binaries:
        name = binary[0].lower()
        if not any(pattern in name for pattern in exclude_patterns):
            filtered.append(binary)
    
    return filtered

# 暂时禁用二进制文件过滤，避免格式问题
# a.binaries = filter_binaries(a.binaries)

# 创建PYZ文件（Python字节码归档）
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# 创建可执行文件
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='邻里+',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # 启用UPX压缩以减小文件大小
    upx_exclude=[
        # 排除某些文件不进行UPX压缩（如果有兼容性问题）
        'vcruntime*.dll',  # 避免压缩系统运行时库
        'msvcp*.dll',      # 避免压缩系统运行时库
        'python*.dll',     # 避免压缩Python核心库
    ],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resource/icon.ico',  # 应用图标
    version_file='version_info.txt',  # 版本信息文件
    # 添加Windows特定选项
    uac_admin=False,    # 不请求管理员权限
    uac_uiaccess=False, # 不请求UI访问权限
)

# 如果需要创建目录分发版本（可选）
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='NetNeighbor_Plus'
# )
