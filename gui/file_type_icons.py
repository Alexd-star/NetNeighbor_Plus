"""
文件类型图标管理器，为不同文件类型提供相应的图标
"""

import os
import platform
from typing import Dict, Optional
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QStyle, QApplication, QFileIconProvider
from PySide6.QtCore import QFileInfo


class FileTypeIconManager:
    """文件类型图标管理器，使用Windows系统真实文件图标"""

    def __init__(self):
        self._icon_cache: Dict[str, QIcon] = {}
        self._icon_provider = None
        self._is_windows = platform.system() == "Windows"
        self._initialize_icon_provider()

        # 常见文件类型的示例文件名（用于获取系统图标）
        self._sample_files = {
            # 文档类型
            ".txt": "sample.txt",
            ".doc": "sample.doc",
            ".docx": "sample.docx",
            ".pdf": "sample.pdf",
            ".rtf": "sample.rtf",
            ".odt": "sample.odt",
            # 表格类型
            ".xls": "sample.xls",
            ".xlsx": "sample.xlsx",
            ".csv": "sample.csv",
            ".ods": "sample.ods",
            # 演示文稿
            ".ppt": "sample.ppt",
            ".pptx": "sample.pptx",
            ".odp": "sample.odp",
            # 图片类型
            ".jpg": "sample.jpg",
            ".jpeg": "sample.jpeg",
            ".png": "sample.png",
            ".gif": "sample.gif",
            ".bmp": "sample.bmp",
            ".tiff": "sample.tiff",
            ".tif": "sample.tif",
            ".svg": "sample.svg",
            ".ico": "sample.ico",
            ".webp": "sample.webp",
            # 音频类型
            ".mp3": "sample.mp3",
            ".wav": "sample.wav",
            ".flac": "sample.flac",
            ".aac": "sample.aac",
            ".ogg": "sample.ogg",
            ".wma": "sample.wma",
            ".m4a": "sample.m4a",
            # 视频类型
            ".mp4": "sample.mp4",
            ".avi": "sample.avi",
            ".mkv": "sample.mkv",
            ".mov": "sample.mov",
            ".wmv": "sample.wmv",
            ".flv": "sample.flv",
            ".webm": "sample.webm",
            ".m4v": "sample.m4v",
            ".3gp": "sample.3gp",
            # 压缩文件
            ".zip": "sample.zip",
            ".rar": "sample.rar",
            ".7z": "sample.7z",
            ".tar": "sample.tar",
            ".gz": "sample.gz",
            ".bz2": "sample.bz2",
            ".xz": "sample.xz",
            ".tar.gz": "sample.tar.gz",
            ".tar.bz2": "sample.tar.bz2",
            # 代码文件
            ".py": "sample.py",
            ".js": "sample.js",
            ".html": "sample.html",
            ".htm": "sample.htm",
            ".css": "sample.css",
            ".cpp": "sample.cpp",
            ".c": "sample.c",
            ".h": "sample.h",
            ".java": "sample.java",
            ".php": "sample.php",
            ".rb": "sample.rb",
            ".go": "sample.go",
            ".rs": "sample.rs",
            ".swift": "sample.swift",
            ".kt": "sample.kt",
            ".ts": "sample.ts",
            ".jsx": "sample.jsx",
            ".vue": "sample.vue",
            ".xml": "sample.xml",
            ".json": "sample.json",
            ".yaml": "sample.yaml",
            ".yml": "sample.yml",
            ".toml": "sample.toml",
            ".ini": "sample.ini",
            ".cfg": "sample.cfg",
            ".conf": "sample.conf",
            # 可执行文件
            ".exe": "sample.exe",
            ".msi": "sample.msi",
            ".app": "sample.app",
            ".deb": "sample.deb",
            ".rpm": "sample.rpm",
            ".dmg": "sample.dmg",
            ".pkg": "sample.pkg",
            # 字体文件
            ".ttf": "sample.ttf",
            ".otf": "sample.otf",
            ".woff": "sample.woff",
            ".woff2": "sample.woff2",
            ".eot": "sample.eot",
            # 数据库文件
            ".db": "sample.db",
            ".sqlite": "sample.sqlite",
            ".sqlite3": "sample.sqlite3",
            ".mdb": "sample.mdb",
            ".accdb": "sample.accdb",
            # 配置文件
            ".config": "sample.config",
            ".properties": "sample.properties",
            ".settings": "sample.settings",
            # 日志文件
            ".log": "sample.log",
            ".logs": "sample.logs",
            # 备份文件
            ".bak": "sample.bak",
            ".backup": "sample.backup",
            ".old": "sample.old",
        }

        self._initialize_icons()

    def _initialize_icon_provider(self):
        """初始化图标提供器"""
        try:
            app = QApplication.instance()
            if app is not None:
                self._icon_provider = QFileIconProvider()
        except Exception as e:
            print(f"初始化图标提供器失败: {e}")
            self._icon_provider = None

    def _initialize_icons(self):
        """初始化图标缓存"""
        app = QApplication.instance()
        if app is None or self._icon_provider is None:
            # 如果没有QApplication实例或图标提供器，延迟初始化
            return

        # 缓存文件夹图标
        try:
            folder_info = QFileInfo(".")
            folder_info.setFile(".")
            self._icon_cache["folder"] = self._icon_provider.icon(folder_info)
        except Exception:
            # 回退到系统标准图标
            style = app.style()
            self._icon_cache["folder"] = style.standardIcon(
                QStyle.StandardPixmap.SP_DirIcon
            )

        # 缓存默认文件图标
        try:
            default_info = QFileInfo("sample.txt")
            self._icon_cache["default"] = self._icon_provider.icon(default_info)
        except Exception:
            # 回退到系统标准图标
            style = app.style()
            self._icon_cache["default"] = style.standardIcon(
                QStyle.StandardPixmap.SP_FileIcon
            )

        # 如果是Windows系统，预缓存一些常见的文件类型图标
        if self._is_windows and self._icon_provider:
            self._preload_common_icons()

    def _preload_common_icons(self):
        """预加载常见文件类型的图标"""
        # 预加载最常见的文件类型
        common_extensions = [
            ".txt",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".jpg",
            ".png",
            ".mp3",
            ".mp4",
            ".zip",
            ".exe",
            ".html",
            ".py",
        ]

        for ext in common_extensions:
            try:
                icon = self._get_system_icon_for_extension(ext)
                if icon and not icon.isNull():
                    self._icon_cache[ext] = icon
            except Exception:
                continue

    def get_file_icon(self, filename: str, is_dir: bool = False) -> QIcon:
        """
        根据文件名获取对应的图标

        Args:
            filename: 文件名
            is_dir: 是否为目录

        Returns:
            QIcon: 对应的图标
        """
        # 如果图标提供器未初始化，尝试重新初始化
        if self._icon_provider is None:
            self._initialize_icon_provider()

        # 如果图标缓存为空，尝试重新初始化
        if not self._icon_cache:
            self._initialize_icons()

        if is_dir:
            return self._icon_cache.get("folder", QIcon())

        # 获取文件扩展名
        _, ext = os.path.splitext(filename.lower())

        # 处理特殊的复合扩展名
        if filename.lower().endswith(".tar.gz"):
            ext = ".tar.gz"
        elif filename.lower().endswith(".tar.bz2"):
            ext = ".tar.bz2"

        # 首先检查缓存
        cache_key = ext or "default"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        # 尝试从系统获取图标
        icon = self._get_system_icon_for_extension(ext)
        if icon and not icon.isNull():
            self._icon_cache[cache_key] = icon
            return icon

        # 回退到默认图标
        return self._icon_cache.get("default", QIcon())

    def _get_system_icon_for_extension(self, ext: str) -> Optional[QIcon]:
        """
        从系统获取指定扩展名的图标

        Args:
            ext: 文件扩展名

        Returns:
            QIcon: 系统图标，如果获取失败则返回None
        """
        if not self._icon_provider or not ext:
            return None

        try:
            # 使用示例文件名获取系统图标
            sample_filename = self._sample_files.get(ext)
            if sample_filename:
                file_info = QFileInfo(sample_filename)
                icon = self._icon_provider.icon(file_info)
                if not icon.isNull():
                    return icon

            # 如果没有预定义的示例文件，创建一个
            sample_filename = f"sample{ext}"
            file_info = QFileInfo(sample_filename)
            icon = self._icon_provider.icon(file_info)
            if not icon.isNull():
                return icon

        except Exception as e:
            print(f"获取系统图标失败 {ext}: {e}")

        return None

    def get_icon_by_type(self, icon_type: str) -> Optional[QIcon]:
        """
        根据图标类型获取图标

        Args:
            icon_type: 图标类型

        Returns:
            QIcon: 对应的图标，如果不存在则返回None
        """
        return self._icon_cache.get(icon_type)

    def clear_cache(self):
        """清理图标缓存"""
        self._icon_cache.clear()

    def get_cache_info(self) -> Dict[str, int]:
        """获取缓存信息"""
        return {
            "cached_icons": len(self._icon_cache),
            "is_windows": self._is_windows,
            "has_provider": self._icon_provider is not None,
        }


# 全局实例
_file_type_icon_manager = None


def get_file_type_icon_manager() -> FileTypeIconManager:
    """获取文件类型图标管理器的全局实例"""
    global _file_type_icon_manager
    if _file_type_icon_manager is None:
        _file_type_icon_manager = FileTypeIconManager()
    return _file_type_icon_manager
