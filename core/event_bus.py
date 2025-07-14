from typing import Callable, Dict, List


class EventBus:
    """一个简单的发布/订阅模式事件总线。"""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """订阅一个事件类型。"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, *args, **kwargs):
        """发布一个事件，并触发所有已订阅的回调。"""
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    print(f"Error in event bus callback for '{event_type}': {e}")


bus = EventBus()
