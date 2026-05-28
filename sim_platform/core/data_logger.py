"""数据记录器 — 记录仿真过程中各信号的时间序列"""

from collections import deque
from typing import Optional


class DataLogger:
    """时间序列数据记录器，按信号名存储 float 序列

    使用 deque(maxlen) 实现 O(1) 追加和自动裁剪。
    """

    def __init__(self, max_points: int = 10000):
        self._max_points = max_points
        self._time: deque[float] = deque(maxlen=max_points)
        self._signals: dict[str, deque[float]] = {}

    def record(self, t: float, **signals: float):
        self._time.append(t)
        for key, value in signals.items():
            if key not in self._signals:
                self._signals[key] = deque(maxlen=self._max_points)
            self._signals[key].append(value)

    def get_signal(self, name: str) -> tuple[list[float], list[float]]:
        """返回 (time_list, value_list)"""
        if name in self._signals:
            return list(self._time), list(self._signals[name])
        return [], []

    @property
    def signal_names(self) -> list[str]:
        return list(self._signals.keys())

    @property
    def time(self) -> list[float]:
        return list(self._time)

    def clear(self):
        self._time.clear()
        self._signals.clear()

    def __len__(self) -> int:
        return len(self._time)

    def __bool__(self) -> bool:
        return len(self._time) > 0
