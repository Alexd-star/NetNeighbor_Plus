"""
WebSocket客户端线程类，用于处理WebSocket连接
"""

import asyncio
import json

from PySide6.QtCore import QThread, Signal
import websockets


class WebSocketClientThread(QThread):
    """在后台线程中处理 WebSocket 连接, 并通过信号与主线程通信。"""

    message_received = Signal(str, str)  # 消息内容，来源

    def __init__(self, uri: str, source: str):
        super().__init__()
        self.uri = uri
        self.source = source
        self._is_running = True
        self.loop: asyncio.AbstractEventLoop = None
        self.task: asyncio.Task = None

    async def listen(self):
        """异步监听 WebSocket 消息的核心循环。"""
        while self._is_running:
            try:
                connect_kwargs = {"open_timeout": 5, "close_timeout": 5}
                async with websockets.connect(self.uri, **connect_kwargs) as ws:
                    print(f"WebSocket ({self.source}) 已连接到 {self.uri}")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_connected"}),
                        self.source,
                    )
                    while self._is_running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            self.message_received.emit(msg, self.source)
                        except asyncio.TimeoutError:
                            await asyncio.sleep(0.1)
                        except websockets.exceptions.ConnectionClosed:
                            if self._is_running:
                                print(f"WebSocket ({self.source}) 连接已关闭。")
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._is_running:
                    print(f"WebSocket ({self.source}) 连接错误: {e}。5秒后重连...")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_disconnected"}),
                        self.source,
                    )
                    for _ in range(50):
                        if not self._is_running:
                            break
                        await asyncio.sleep(0.1)

    def run(self):
        """QThread的入口点, 设置并运行asyncio事件循环。"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.task = self.loop.create_task(self.listen())
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        finally:
            if self.loop and self.loop.is_running():
                self.loop.stop()
            if self.loop and not self.loop.is_closed():
                self.loop.close()
            print(f"WebSocket ({self.source}) 线程已干净地终止。")

    def stop(self):
        """从外部请求停止线程。"""
        if not self.isRunning():
            return
        print(f"正在请求停止 WebSocket ({self.source}) 线程...")
        self._is_running = False
        if self.loop and self.task and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)
        if not self.wait(2000):
            print(f"警告: WebSocket ({self.source}) 线程超时，强制终止。")
            self.terminate()
