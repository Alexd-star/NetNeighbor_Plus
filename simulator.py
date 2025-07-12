import time
import socket
from zeroconf import ServiceInfo, Zeroconf
import threading

# --- 配置 ---
NUM_DEVICES_TO_SIMULATE = 500  # 您可以按需修改，比如改成500来做极限测试
SERVICE_TYPE = "_netneighbor._tcp.local."
BASE_PORT = 9000


# -------------

def register_service(zeroconf, service_name, port):
    """注册一个模拟的设备服务"""
    try:
        # 使用一个固定的假IP，因为我们只关心服务发现，不关心连接
        fake_ip = "192.168.1.100"
        full_service_name = f"{service_name}.{SERVICE_TYPE}"

        properties = {
            'os': 'SimulatedOS',
            'user': 'simulator',
            'tcp_port': str(port + 1),
            'dev_type': 'Simulator'
        }

        service_info = ServiceInfo(
            SERVICE_TYPE,
            full_service_name,
            addresses=[socket.inet_aton(fake_ip)],
            port=port,
            properties=properties
        )
        zeroconf.register_service(service_info)
        print(f"  -> 已注册模拟设备: {service_name} on port {port}")
    except Exception as e:
        print(f"注册服务 {service_name} 时出错: {e}")


def main():
    print("--- 邻里+ (NetNeighbor Plus) 性能压力测试模拟器 ---")
    print(f"准备在局域网中模拟 {NUM_DEVICES_TO_SIMULATE} 台设备上线...")

    zeroconf = Zeroconf()
    threads = []

    print("\n第1阶段：在后台快速注册所有服务...")
    start_time = time.time()

    for i in range(NUM_DEVICES_TO_SIMULATE):
        service_name = f"Simulated-PC-{i + 1}"
        port = BASE_PORT + i
        # 使用线程来加速注册过程
        thread = threading.Thread(target=register_service, args=(zeroconf, service_name, port))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()  # 等待所有注册线程完成

    end_time = time.time()
    print(f"\n第1阶段完成！所有服务已在 {end_time - start_time:.2f} 秒内注册完毕。")
    print("\n现在，请观察您的 NetNeighbor+ 主程序界面反应。")
    print("模拟器将保持运行状态以维持这些服务在线。")
    print("按 Ctrl+C 退出模拟器并注销所有服务。")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭模拟器并注销所有服务，请稍候...")
        zeroconf.unregister_all_services()
        zeroconf.close()
        print("所有模拟设备已下线。模拟器已关闭。")


if __name__ == "__main__":
    main()