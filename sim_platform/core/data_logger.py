"""数据记录器 — 记录仿真过程中各信号的时间序列

每个信号独立存储 (time, value) 对，支持多信号不同频率记录。
使用 deque(maxlen) 实现 O(1) 追加和自动裁剪。
"""

from collections import deque
from typing import Optional


class DataLogger:
    """时间序列数据记录器，按信号名存储 float 序列

    每个信号维护独立的 (times, values) deque 对，确保 get_signal()
    返回的 time 和 value 数组长度始终一致。
    """

    def __init__(self, max_points: int = 10000):
        self._max_points = max_points
        self._time: deque[float] = deque(maxlen=max_points)          # 全局时间线（兼容旧接口）
        self._signals: dict[str, tuple[deque[float], deque[float]]] = {}  # name → (times, values)

    def record(self, t: float, **signals: float) -> None:
        """记录一组信号值

        每个信号独立存储时间戳，支持同一仿真帧内多次调用（如 A1 引擎逐消息记录）。
        """
        self._time.append(t)
        for key, value in signals.items():
            if key not in self._signals:
                self._signals[key] = (
                    deque(maxlen=self._max_points),
                    deque(maxlen=self._max_points),
                )
            times, vals = self._signals[key]
            times.append(t)
            vals.append(value)

    def get_signal(self, name: str) -> tuple[list[float], list[float]]:
        """返回 (time_list, value_list)，两者长度始终一致"""
        pair = self._signals.get(name)
        if pair is not None:
            return list(pair[0]), list(pair[1])
        return [], []

    @property
    def signal_names(self) -> list[str]:
        return list(self._signals.keys())

    @property
    def time(self) -> list[float]:
        return list(self._time)

    def clear(self) -> None:
        self._time.clear()
        self._signals.clear()

    def __len__(self) -> int:
        return len(self._time)

    def __bool__(self) -> bool:
        return len(self._time) > 0
