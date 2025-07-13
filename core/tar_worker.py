# 文件: core/tar_worker.py
import os
import sys
import tarfile
import time


def log_error(message):
    """一个简单的函数，用于向stderr打印带时间戳的、UTF-8编码的日志。"""
    timestamp = time.strftime("%H:%M:%S")
    sys.stderr.buffer.write(f"[{timestamp}] [TAR_WORKER] {message}\n".encode("utf-8"))
    sys.stderr.buffer.flush()


def main():
    log_error("TAR打包工作进程启动。")
    if len(sys.argv) < 2:
        log_error("错误: 未提供文件夹路径。")
        sys.exit(1)

    folder_path = sys.argv[1]

    if not os.path.isdir(folder_path):
        log_error(f"错误: 路径 '{folder_path}' 不是一个有效的文件夹。")
        sys.exit(1)

    try:
        log_error("开始向stdout生成TAR数据流 (使用GNU格式)...")
        # 'w|'表示以无压缩的流模式写入
        with tarfile.open(
            fileobj=sys.stdout.buffer, mode="w|", format=tarfile.GNU_FORMAT
        ) as tar:
            # arcname 指定了文件在压缩包内的相对路径，这里是文件夹本身
            tar.add(folder_path, arcname=os.path.basename(folder_path))

        log_error("TAR数据流生成完毕。工作进程正常退出。")

    except Exception as e:
        log_error(f"打包过程中发生致命错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
