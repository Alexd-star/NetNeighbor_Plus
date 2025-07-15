# -*- coding: utf-8 -*-
"""
版本信息文件，用于PyInstaller生成带版本信息的exe文件
"""

# 版本信息
VERSION = (1, 0, 0, 0)
VERSION_STRING = "1.0.0.0"

# 文件版本信息（Windows格式）
version_info = f"""
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION},
    prodvers={VERSION},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'NetNeighbor Plus Team'),
        StringStruct(u'FileDescription', u'NetNeighbor Plus - 局域网文件共享工具'),
        StringStruct(u'FileVersion', u'{VERSION_STRING}'),
        StringStruct(u'InternalName', u'NetNeighbor_Plus'),
        StringStruct(u'LegalCopyright', u'Copyright © 2024 NetNeighbor Plus Team'),
        StringStruct(u'OriginalFilename', u'NetNeighbor_Plus.exe'),
        StringStruct(u'ProductName', u'NetNeighbor Plus'),
        StringStruct(u'ProductVersion', u'{VERSION_STRING}')])
      ]), 
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


# 将版本信息写入文件
def create_version_file():
    """创建版本信息文件"""
    with open("version_info.txt", "w", encoding="utf-8") as f:
        f.write(version_info)
    print("版本信息文件已创建: version_info.txt")


if __name__ == "__main__":
    create_version_file()
