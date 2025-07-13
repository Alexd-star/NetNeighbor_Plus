# 文件: core/event_bus.py
# 描述: 一个极简的、用于模块间解耦的事件总线。

from typing import Callable, Dict, List


class EventBus:
    """
    一个简单的发布/订阅模式事件总线。
    """

    def __init__(self):
        # 使用字典来存储每个事件类型对应的所有回调函数
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """订阅一个事件类型。"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, *args, **kwargs):
        """发布一个事件，并触发所有已订阅的回调。"""
        if event_type in self._subscribers:
            # 遍历并调用所有订阅了该事件的回调函数
            for callback in self._subscribers[event_type]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    # 打印错误，但确保一个回调的失败不会影响其他回调
                    print(f"Error in event bus callback for '{event_type}': {e}")


# 创建一个全局唯一的事件总线实例，供整个应用使用
bus = EventBus()
