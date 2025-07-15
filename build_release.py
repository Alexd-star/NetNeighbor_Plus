#!/usr/bin/env python3
"""
邻里+ 正式版本打包脚本
生成无控制台窗口的正式发布版本
"""

import os
import sys
import subprocess
import shutil
import time


def main():
    print("邻里+ 正式版本打包工具")
    print("=" * 60)

    start_time = time.time()

    # 清理旧文件
    print("清理构建目录...")
    for dir_name in ["build", "dist"]:
        if os.path.exists(dir_name):
            print(f"删除 {dir_name}")
            shutil.rmtree(dir_name)

    # 检查必要文件
    required_files = ["run_app.py", "build_config.spec", "icon.ico"]
    for file_name in required_files:
        if not os.path.exists(file_name):
            print(f"错误: {file_name} 不存在")
            return False

    # 生成版本信息
    print("生成版本信息...")
    try:
        exec(open("version_info.py").read())
        print("✓ 版本信息已生成")
    except:
        print("⚠ 版本信息生成失败，跳过")

    print("开始打包正式版本...")
    print("特点: 无控制台窗口，静默运行，包含完整功能")
    print("修复: 已解决控制台窗口闪现问题")

    # 使用正式版本的 spec 文件
    # 注意：当使用.spec文件时，控制台设置在spec文件中配置，不能使用命令行选项
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "build_config.spec"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode == 0:
            print("✓ 打包成功")

            # 检查输出文件
            exe_path = "dist/邻里+.exe"
            if os.path.exists(exe_path):
                file_size = os.path.getsize(exe_path) / (1024 * 1024)
                print(f"✓ 正式版可执行文件: {exe_path}")
                print(f"✓ 文件大小: {file_size:.1f} MB")

                # 创建发布目录
                os.makedirs("release", exist_ok=True)

                # 复制主程序
                shutil.copy2(exe_path, "release/")
                print("✓ 主程序已复制到 release 目录")

                # 创建配置文件模板
                config_template = "release/config_template.toml"
                if not os.path.exists(config_template):
                    with open(config_template, "w", encoding="utf-8") as f:
                        f.write(
                            """# 邻里+ 配置文件模板
# 首次运行时会自动创建配置文件

[service]
name = "我的设备"
port = 8080

[[shares]]
name = "共享文件夹"
path = "C:\\Users\\Public\\Documents"
permissions = ["read", "write"]
"""
                        )
                    print("✓ 配置文件模板已创建")

                # 创建安装脚本
                create_installer_script()

                # 创建使用说明
                create_readme()

                end_time = time.time()
                print(f"✓ 总耗时: {end_time - start_time:.1f} 秒")

                print("\n" + "=" * 60)
                print("邻里+ 正式版本打包完成！")
                print("=" * 60)
                print("发布文件:")
                print("- 邻里+.exe (主程序)")
                print("- config_template.toml (配置模板)")
                print("- install.bat (安装脚本)")
                print("- README.txt (使用说明)")
                print()
                print("特点:")
                print("- 无控制台窗口，静默运行")
                print("- 已修复控制台窗口闪现问题")
                print("- 包含完整的设备发现和文件共享功能")
                print("- 自动处理端口冲突")
                print("- 支持多实例运行")
                print("- 包含UPX压缩，文件更小")
                print("- 支持VPN环境下的网络连接")
                print()
                print("使用方法:")
                print("1. 直接运行 邻里+.exe")
                print("2. 或运行 install.bat 进行系统安装")
                print("3. 首次运行会自动创建配置文件")

                return True
            else:
                print("✗ 可执行文件未生成")
                return False
        else:
            print("✗ 打包失败")
            print("错误输出:")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("✗ 打包超时")
        return False
    except Exception as e:
        print(f"✗ 打包出错: {e}")
        return False


def create_installer_script():
    """创建安装脚本"""
    installer_script = "release/install.bat"
    with open(installer_script, "w", encoding="utf-8") as f:
        f.write(
            """@echo off
chcp 65001 >nul
echo 邻里+ 安装脚本
echo ==================

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% == 0 (
    echo ✓ 检测到管理员权限
) else (
    echo ⚠ 建议以管理员身份运行以获得最佳兼容性
    echo.
)

:: 创建程序目录
set INSTALL_DIR=%ProgramFiles%\\邻里+
if not exist "%INSTALL_DIR%" (
    mkdir "%INSTALL_DIR%"
    echo ✓ 已创建安装目录: %INSTALL_DIR%
)

:: 复制文件
echo 正在安装文件...
copy "邻里+.exe" "%INSTALL_DIR%\\" >nul
if exist "config_template.toml" (
    copy "config_template.toml" "%INSTALL_DIR%\\" >nul
)
echo ✓ 文件安装完成

:: 创建桌面快捷方式
set /p CREATE_SHORTCUT="是否创建桌面快捷方式? (y/n): "
if /i "%CREATE_SHORTCUT%"=="y" (
    powershell "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%USERPROFILE%\\Desktop\\邻里+.lnk'); $Shortcut.TargetPath = '%INSTALL_DIR%\\邻里+.exe'; $Shortcut.Save()"
    echo ✓ 桌面快捷方式已创建
)

echo.
echo ==================
echo 安装完成！
echo ==================
echo 程序位置: %INSTALL_DIR%\\邻里+.exe
echo 配置目录: %USERPROFILE%\\.netneighbor
echo 应用日志: %USERPROFILE%\\.netneighbor\\app.log
echo.
echo 使用说明:
echo 1. 双击桌面快捷方式或直接运行程序
echo 2. 首次运行会自动创建配置文件
echo 3. 程序会在系统托盘中运行
echo 4. 支持局域网设备自动发现和文件共享
echo.
pause
"""
        )
    print("✓ 安装脚本已创建")


def create_readme():
    """创建使用说明"""
    readme_file = "release/README.txt"
    with open(readme_file, "w", encoding="utf-8") as f:
        f.write(
            """邻里+ (NetNeighbor Plus) - 使用说明
========================================

邻里+ 是一款局域网文件共享和设备发现工具，让您轻松与局域网内的其他设备共享文件。

快速开始
--------
1. 双击运行 邻里+.exe
2. 首次运行会自动创建配置文件
3. 程序会在系统托盘中运行
4. 自动发现局域网内的其他邻里+设备

主要功能
--------
- 自动设备发现：基于zeroconf协议自动发现局域网设备
- 文件共享：支持文件夹共享和文件传输
- 多实例支持：可同时运行多个实例（不同端口）
- 端口自动切换：自动处理端口冲突
- Web界面：提供友好的Web管理界面

系统要求
--------
- Windows 7/8/10/11 (x64)
- 至少 512MB RAM
- 约 200MB 磁盘空间

配置文件
--------
配置文件位置: %USERPROFILE%\\.netneighbor\\config.toml
首次运行会自动创建，您可以根据需要修改设备名称、端口和共享文件夹。

日志文件
--------
应用日志: %USERPROFILE%\\.netneighbor\\app.log
调试日志: %USERPROFILE%\\netneighbor_debug.log

故障排除
--------
1. 如果无法发现设备，请检查防火墙设置
2. 如果端口冲突，程序会自动切换到可用端口
3. 查看日志文件获取详细错误信息

技术支持
--------
如有问题，请查看日志文件或联系技术支持。

版本信息
--------
版本: 1.0.0
构建时间: 2025年7月
"""
        )
    print("✓ 使用说明已创建")


if __name__ == "__main__":
    success = main()
    if not success:
        print("\n❌ 正式版本打包失败")
        print("请检查错误信息")

    input("\n按回车键退出...")
