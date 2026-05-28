"""仿真消息总线 — 进程内轻量级发布/订阅，替代 DDS (F-11)

所有模块通过此总线以同步回调方式交换数据，保持与真实系统一致的 Topic 语义。
"""

import logging
import threading
from typing import Callable, Any
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ==================== Topic 名称常量 ====================

# 下行 (Cloud → Gateway)
CLOUD_DISPATCH_TASK = "CloudDispatchTask"

# 下行 (Gateway → Planning)
TASK_TO_PLANNING = "TaskToPlanning"
MOVE_AUTHORITY = "MoveAuthority"

# 内层 (Planning → Control → Kinematics)
PLANNING_RESULT = "PlanningResult"
CONTROL_CMD = "ControlCmd"

# 上行 (Kinematics → Planning, Control, Gateway)
LOCALIZATION = "Localization"
CHASSIS = "Chassis"

# 横向 (Perception → Planning)
OBSTACLES = "Obstacles"

# 上行 (Gateway → Cloud)
CLOUD_DEVICE_MSG = "CloudDeviceMsg"

# 所有 Topic 列表
ALL_TOPICS = [
    CLOUD_DISPATCH_TASK,
    TASK_TO_PLANNING,
    MOVE_AUTHORITY,
    PLANNING_RESULT,
    CONTROL_CMD,
    LOCALIZATION,
    CHASSIS,
    OBSTACLES,
    CLOUD_DEVICE_MSG,
]


@dataclass
class MessageLogEntry:
    """单条消息日志"""
    topic: str
    timestamp: float
    msg_type: str  # 消息对象的类名


class SimMessageBus:
    """进程内同步消息总线

    所有 publish() 调用在发布者线程内同步调用所有订阅者回调。
    线程安全：publish/subscribe/unsubscribe 由内部锁保护，
    支持 Qt 主线程与 MQTT 网络线程并发访问。

    用法:
        bus = SimMessageBus()
        bus.subscribe(LOCALIZATION, lambda topic, msg: print(f"Got: {msg}"))
        bus.publish(LOCALIZATION, Localization(x=1.0, y=2.0))
    """

    def __init__(self, max_log_entries: int = 10000):
        self._subscribers: dict[str, list[Callable[[str, Any], None]]] = defaultdict(list)
        self._message_counts: dict[str, int] = defaultdict(int)
        self._message_log: list[MessageLogEntry] = []
        self._max_log_entries = max_log_entries
        self._lock = threading.Lock()

    def publish(self, topic: str, msg: Any) -> None:
        """发布消息到指定 Topic，同步调用所有订阅者回调

        Args:
            topic: Topic 名称（使用模块级常量，如 LOCALIZATION）
            msg: 消息体（dataclass 实例）
        """
        with self._lock:
            self._message_counts[topic] += 1
            self._log_message(topic, msg)
            callbacks = list(self._subscribers.get(topic, []))

        for callback in callbacks:
            try:
                callback(topic, msg)
            except Exception:
                logger.exception("SimMessageBus: subscriber callback failed for topic=%s", topic)

    def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        """订阅指定 Topic

        Args:
            topic: Topic 名称
            callback: 回调函数，签名为 callback(topic: str, msg: Any) -> None
        """
        with self._lock:
            if callback not in self._subscribers[topic]:
                self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        """取消订阅"""
        with self._lock:
            if topic in self._subscribers and callback in self._subscribers[topic]:
                self._subscribers[topic].remove(callback)

    def clear(self) -> None:
        """清除所有订阅和统计"""
        with self._lock:
            self._subscribers.clear()
            self._message_counts.clear()
            self._message_log.clear()

    def get_stats(self) -> dict[str, int]:
        """获取各 Topic 的消息计数，用于状态监控"""
        with self._lock:
            return dict(self._message_counts)

    def get_recent_log(self, n: int = 100) -> list[MessageLogEntry]:
        """获取最近 n 条消息日志"""
        with self._lock:
            return self._message_log[-n:]

    def get_topic_subscribers(self, topic: str) -> int:
        """获取指定 Topic 的订阅者数量"""
        with self._lock:
            return len(self._subscribers.get(topic, []))

    def _log_message(self, topic: str, msg: Any) -> None:
        """记录消息到内部日志（用于调试 F-11-05）"""
        timestamp = getattr(msg, "timestamp", 0.0)
        entry = MessageLogEntry(
            topic=topic,
            timestamp=timestamp,
            msg_type=type(msg).__name__,
        )
        self._message_log.append(entry)
        if len(self._message_log) > self._max_log_entries:
            self._message_log = self._message_log[-self._max_log_entries:]
