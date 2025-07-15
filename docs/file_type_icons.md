# 文件类型图标功能

## 概述

邻里+ 现在支持为不同类型的文件显示相应的图标，使文件浏览界面更加直观和美观。

## 支持的文件类型

### 📄 文档类型
- `.txt` - 文本文件
- `.doc`, `.docx` - Word文档
- `.pdf` - PDF文档
- `.rtf` - 富文本格式
- `.odt` - OpenDocument文本

### 📊 表格类型
- `.xls`, `.xlsx` - Excel表格
- `.csv` - 逗号分隔值文件
- `.ods` - OpenDocument表格

### 📽️ 演示文稿
- `.ppt`, `.pptx` - PowerPoint演示文稿
- `.odp` - OpenDocument演示文稿

### 🖼️ 图片类型
- `.jpg`, `.jpeg` - JPEG图片
- `.png` - PNG图片
- `.gif` - GIF动图
- `.bmp` - 位图
- `.tiff`, `.tif` - TIFF图片
- `.svg` - 矢量图
- `.ico` - 图标文件
- `.webp` - WebP图片

### 🎵 音频类型
- `.mp3` - MP3音频
- `.wav` - WAV音频
- `.flac` - FLAC无损音频
- `.aac` - AAC音频
- `.ogg` - OGG音频
- `.wma` - WMA音频
- `.m4a` - M4A音频

### 🎬 视频类型
- `.mp4` - MP4视频
- `.avi` - AVI视频
- `.mkv` - MKV视频
- `.mov` - QuickTime视频
- `.wmv` - WMV视频
- `.flv` - Flash视频
- `.webm` - WebM视频
- `.m4v` - M4V视频
- `.3gp` - 3GP视频

### 📦 压缩文件
- `.zip` - ZIP压缩包
- `.rar` - RAR压缩包
- `.7z` - 7-Zip压缩包
- `.tar` - TAR归档
- `.gz` - Gzip压缩
- `.bz2` - Bzip2压缩
- `.xz` - XZ压缩
- `.tar.gz`, `.tar.bz2` - 复合压缩格式

### 💻 代码文件
- `.py` - Python代码
- `.js` - JavaScript代码
- `.html`, `.htm` - HTML文件
- `.css` - CSS样式表
- `.cpp`, `.c`, `.h` - C/C++代码
- `.java` - Java代码
- `.php` - PHP代码
- `.rb` - Ruby代码
- `.go` - Go代码
- `.rs` - Rust代码
- `.swift` - Swift代码
- `.kt` - Kotlin代码
- `.ts` - TypeScript代码
- `.jsx` - React JSX
- `.vue` - Vue.js组件
- `.xml` - XML文件
- `.json` - JSON数据
- `.yaml`, `.yml` - YAML配置
- `.toml` - TOML配置
- `.ini`, `.cfg`, `.conf` - 配置文件

### ⚙️ 可执行文件
- `.exe` - Windows可执行文件
- `.msi` - Windows安装包
- `.app` - macOS应用程序
- `.deb` - Debian软件包
- `.rpm` - RPM软件包
- `.dmg` - macOS磁盘映像
- `.pkg` - 软件包

### 🔤 字体文件
- `.ttf` - TrueType字体
- `.otf` - OpenType字体
- `.woff`, `.woff2` - Web字体
- `.eot` - Embedded OpenType字体

### 🗄️ 数据库文件
- `.db` - 数据库文件
- `.sqlite`, `.sqlite3` - SQLite数据库
- `.mdb` - Microsoft Access数据库
- `.accdb` - Access 2007+数据库

### ⚙️ 配置文件
- `.config` - 配置文件
- `.properties` - 属性文件
- `.settings` - 设置文件

### 📋 日志文件
- `.log`, `.logs` - 日志文件

### 💾 备份文件
- `.bak` - 备份文件
- `.backup` - 备份文件
- `.old` - 旧版本文件

## 技术实现

### 文件类型图标管理器

`gui/file_type_icons.py` 模块提供了 `FileTypeIconManager` 类，负责：

1. **文件类型映射**：将文件扩展名映射到图标类型
2. **图标缓存**：缓存系统图标以提高性能
3. **延迟初始化**：在QApplication可用时才初始化图标
4. **回退机制**：为未知文件类型提供默认图标

### 使用方法

```python
from gui.file_type_icons import get_file_type_icon_manager

# 获取图标管理器实例
icon_manager = get_file_type_icon_manager()

# 获取文件图标
icon = icon_manager.get_file_icon("document.pdf", is_dir=False)

# 获取文件夹图标
folder_icon = icon_manager.get_file_icon("my_folder", is_dir=True)
```

## 特性

- **自动识别**：根据文件扩展名自动选择合适的图标
- **性能优化**：图标缓存机制，避免重复创建
- **兼容性好**：使用系统标准图标，确保跨平台兼容
- **可扩展**：易于添加新的文件类型支持
- **回退安全**：未知文件类型使用默认图标

## 效果

- 文档文件显示文档图标
- 图片文件显示图片图标
- 音频文件显示音频图标
- 视频文件显示视频图标
- 代码文件显示代码图标
- 压缩文件显示压缩包图标
- 其他文件类型显示相应的专用图标
- 未知文件类型显示默认文件图标

这个功能大大提升了文件浏览界面的用户体验，使用户能够快速识别不同类型的文件。
