# Windows系统文件图标功能

## 概述

邻里+ 现在支持使用Windows系统的真实文件图标，使文件浏览界面与Windows资源管理器保持一致的视觉效果。

## ✨ 主要特性

### 🎯 Windows系统图标集成
- **真实系统图标**：直接使用Windows系统注册的文件类型图标
- **完美兼容**：显示效果与Windows资源管理器完全一致
- **自动识别**：支持所有Windows注册的文件类型
- **应用程序关联**：显示与文件关联的应用程序图标

### 🚀 性能优化
- **智能缓存**：图标缓存机制，避免重复获取
- **延迟加载**：按需加载图标，提高启动速度
- **预加载**：预缓存常见文件类型图标
- **内存优化**：高效的图标管理

### 🔧 技术特性
- **跨平台兼容**：在非Windows系统上自动回退到标准图标
- **错误处理**：优雅处理图标获取失败的情况
- **动态更新**：支持系统图标变更的实时更新

## 📁 支持的文件类型

### 📄 办公文档
- **Word文档**：`.doc`, `.docx` - 显示Microsoft Word图标
- **Excel表格**：`.xls`, `.xlsx` - 显示Microsoft Excel图标
- **PowerPoint**：`.ppt`, `.pptx` - 显示Microsoft PowerPoint图标
- **PDF文档**：`.pdf` - 显示PDF阅读器图标
- **文本文件**：`.txt` - 显示记事本图标

### 🖼️ 多媒体文件
- **图片文件**：`.jpg`, `.png`, `.gif`, `.bmp` - 显示图片查看器图标
- **音频文件**：`.mp3`, `.wav`, `.flac` - 显示音频播放器图标
- **视频文件**：`.mp4`, `.avi`, `.mkv` - 显示视频播放器图标

### 💻 开发文件
- **Python代码**：`.py` - 显示Python解释器图标
- **网页文件**：`.html`, `.htm` - 显示浏览器图标
- **样式表**：`.css` - 显示代码编辑器图标
- **JavaScript**：`.js` - 显示JavaScript引擎图标

### 📦 压缩文件
- **ZIP压缩包**：`.zip` - 显示压缩软件图标
- **RAR压缩包**：`.rar` - 显示WinRAR图标
- **7-Zip压缩包**：`.7z` - 显示7-Zip图标

### ⚙️ 系统文件
- **可执行文件**：`.exe` - 显示应用程序图标
- **安装包**：`.msi` - 显示Windows安装程序图标
- **配置文件**：`.ini`, `.cfg` - 显示配置文件图标

## 🔧 技术实现

### 核心组件

#### FileTypeIconManager 类
```python
class FileTypeIconManager:
    """Windows系统文件图标管理器"""
    
    def __init__(self):
        self._icon_cache = {}           # 图标缓存
        self._icon_provider = None      # Qt图标提供器
        self._is_windows = True         # Windows系统检测
```

#### 主要方法

1. **get_file_icon(filename, is_dir)**
   - 根据文件名获取对应的系统图标
   - 自动处理文件夹和文件的区别
   - 支持复合扩展名（如.tar.gz）

2. **_get_system_icon_for_extension(ext)**
   - 从Windows系统获取指定扩展名的图标
   - 使用QFileIconProvider获取真实系统图标
   - 自动处理获取失败的情况

3. **_preload_common_icons()**
   - 预加载常见文件类型的图标
   - 提高常用文件类型的显示速度

### 使用示例

```python
from gui.file_type_icons import get_file_type_icon_manager

# 获取图标管理器
icon_manager = get_file_type_icon_manager()

# 获取Word文档图标
word_icon = icon_manager.get_file_icon("document.docx")

# 获取文件夹图标
folder_icon = icon_manager.get_file_icon("my_folder", is_dir=True)

# 获取缓存信息
cache_info = icon_manager.get_cache_info()
print(f"已缓存图标数量: {cache_info['cached_icons']}")
```

## 🎨 视觉效果

### Windows资源管理器风格
- **一致性**：与Windows资源管理器完全一致的图标显示
- **专业性**：使用系统注册的官方应用程序图标
- **识别性**：用户熟悉的图标，提高操作效率

### 图标类型示例
- 📄 **Word文档** → Microsoft Word蓝色W图标
- 📊 **Excel表格** → Microsoft Excel绿色X图标
- 📽️ **PowerPoint** → Microsoft PowerPoint橙色P图标
- 🖼️ **图片文件** → Windows照片查看器图标
- 🎵 **音频文件** → Windows媒体播放器图标
- 🎬 **视频文件** → 视频播放器图标
- 📦 **ZIP文件** → WinRAR或7-Zip图标
- 💻 **Python文件** → Python解释器图标

## 🔄 兼容性

### Windows系统
- **完全支持**：使用真实的Windows系统图标
- **版本兼容**：支持Windows 7/8/10/11
- **应用关联**：自动识别文件关联的应用程序

### 非Windows系统
- **自动回退**：在Linux/macOS上自动使用Qt标准图标
- **功能保持**：基本的文件类型识别功能正常工作
- **性能稳定**：不影响应用程序的稳定性

## 📈 性能优势

- **启动速度**：延迟加载机制，不影响应用启动
- **内存使用**：智能缓存，避免重复加载
- **响应速度**：预加载常见图标，提高响应速度
- **系统资源**：高效的图标管理，最小化系统资源占用

## 🛠️ 维护和扩展

### 缓存管理
- 自动缓存已获取的图标
- 支持手动清理缓存
- 提供缓存状态查询

### 错误处理
- 优雅处理图标获取失败
- 自动回退到默认图标
- 详细的错误日志记录

这个功能大大提升了邻里+在Windows系统上的用户体验，使其看起来更加原生和专业。
