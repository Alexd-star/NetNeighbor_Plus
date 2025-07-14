"""
事件总线系统，提供高性能的发布/订阅模式事件处理
"""

import time
import threading
from typing import Callable, Dict, List, Any
from collections import defaultdict


class EventBus:
    """一个高性能的发布/订阅模式事件总线，支持事件聚合和限流。"""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_aggregator = EventAggregator()
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable):
        """订阅一个事件类型。"""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, *args, **kwargs):
        """发布一个事件，使用事件聚合器来优化性能。"""
        # 对于peer_update事件，使用聚合器
        if event_type == "peer_update" and args:
            self._event_aggregator.add_event(event_type, args[0])
        else:
            # 其他事件直接发布
            self._publish_immediate(event_type, *args, **kwargs)

    def _publish_immediate(self, event_type: str, *args, **kwargs):
        """立即发布事件"""
        with self._lock:
            if event_type in self._subscribers:
                for callback in self._subscribers[event_type]:
                    try:
                        callback(*args, **kwargs)
                    except Exception as e:
                        print(f"Error in event bus callback for '{event_type}': {e}")


class EventAggregator:
    """事件聚合器，用于合并和批量处理相似事件"""

    def __init__(self, flush_interval: float = 0.01):  # 减少聚合间隔提高响应速度
        self._pending_events: Dict[str, List[Any]] = defaultdict(list)
        self._last_flush_time: Dict[str, float] = {}
        self._flush_interval = flush_interval
        self._lock = threading.Lock()

    def add_event(self, event_type: str, event_data: Any):
        """添加事件到聚合器"""
        current_time = time.time()

        with self._lock:
            self._pending_events[event_type].append(event_data)

            # 检查是否需要刷新
            last_flush = self._last_flush_time.get(event_type, 0)
            if current_time - last_flush >= self._flush_interval:
                self._flush_events(event_type)
                self._last_flush_time[event_type] = current_time

    def _flush_events(self, event_type: str):
        """刷新指定类型的事件"""
        if not self._pending_events[event_type]:
            return

        # 对于peer_update事件，只保留最新的状态
        if event_type == "peer_update":
            # 按设备名称分组，只保留每个设备的最新状态
            latest_events = {}
            for event_data in self._pending_events[event_type]:
                device_name = event_data.get("name")
                if device_name:
                    latest_events[device_name] = event_data

            # 发布聚合后的事件
            for event_data in latest_events.values():
                bus._publish_immediate(event_type, event_data)

        # 清空待处理事件
        self._pending_events[event_type].clear()


bus = EventBus()
