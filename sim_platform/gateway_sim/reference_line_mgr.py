"""参考线管理器 — 等价于 C++ Business 类 (F-08-03)

将 TaskTraj 按 is_reverse 标志拆分为多段 ReferenceLine，
管理多段参考线的索引、切换逻辑、路权起终点。
"""

from dataclasses import dataclass, field

from ..models.sim_messages import TaskTraj, TrajPoint


@dataclass
class ReferenceLine:
    """单段参考线"""
    points: list[TrajPoint] = field(default_factory=list)
    direction: int = 1          # 0=倒车(reverse), 1=前进(forward)
    start_index: int = 0        # 在原始 TaskTraj 中的起始索引
    end_index: int = 0          # 在原始 TaskTraj 中的结束索引

    def __len__(self) -> int:
        return len(self.points)

    def __bool__(self) -> bool:
        return len(self.points) > 0

    @property
    def length(self) -> float:
        if not self.points:
            return 0.0
        return self.points[-1].s - self.points[0].s

    def find_closest_index(self, x: float, y: float) -> int:
        """在当前参考线上查找离 (x, y) 最近的点的局部索引"""
        if not self.points:
            return 0
        best = 0
        best_dist = float("inf")
        for i, p in enumerate(self.points):
            d = (p.x - x) ** 2 + (p.y - y) ** 2
            if d < best_dist:
                best_dist = d
                best = i
        return best


class ReferenceLineManager:
    """多段参考线管理器

    职责:
    - 将 TaskTraj 按 is_reverse 变化拆分为多段 ReferenceLine
    - 维护当前参考线索引
    - 管理 right_of_way_index 和 stop_index (路权信息)
    """

    def __init__(self):
        self._ref_lines: list[ReferenceLine] = []
        self._current_idx: int = 0
        self._right_of_way_index: int = 0
        self._stop_index: int = 10 ** 9  # Sentinel: 匹配 C++ uninitialized uint16_t (大值，min-tracking 初始态)
        self._total_points: int = 0

    # ========== 属性 ==========

    @property
    def current(self) -> ReferenceLine:
        """当前活跃参考线"""
        if 0 <= self._current_idx < len(self._ref_lines):
            return self._ref_lines[self._current_idx]
        return ReferenceLine()

    @property
    def current_index(self) -> int:
        return self._current_idx

    @property
    def ref_lines(self) -> list[ReferenceLine]:
        return self._ref_lines

    @property
    def right_of_way_index(self) -> int:
        return self._right_of_way_index

    @right_of_way_index.setter
    def right_of_way_index(self, val: int):
        self._right_of_way_index = val

    @property
    def stop_index(self) -> int:
        return self._stop_index

    @stop_index.setter
    def stop_index(self, val: int):
        self._stop_index = val

    @property
    def total_points(self) -> int:
        return self._total_points

    def __len__(self) -> int:
        return len(self._ref_lines)

    def __bool__(self) -> bool:
        return len(self._ref_lines) > 0

    # ========== 核心逻辑 ==========

    def update_from_task(self, task_traj: TaskTraj) -> None:
        """从 TaskTraj 构建参考线列表

        按 is_reverse 标志拆分: 连续相同 is_reverse 值的点组成一段参考线。
        is_reverse=True→前进, is_reverse=False→倒车
        """
        self._ref_lines.clear()
        self._stop_index = 10 ** 9  # 重置为 sentinel，匹配 C++ 新任务时 stop_index 未初始化
        self._current_idx = 0
        self._total_points = len(task_traj.points)

        pts = task_traj.points
        if len(pts) < 2:
            return

        # 按 is_reverse 拆分
        segment_start = 0
        current_is_reverse = pts[0].is_reverse

        for i in range(1, len(pts)):
            if pts[i].is_reverse != current_is_reverse:
                self._ref_lines.append(ReferenceLine(
                    points=pts[segment_start:i],
                    direction=1 if current_is_reverse else 0,
                    start_index=segment_start,
                    end_index=i - 1,
                ))
                segment_start = i
                current_is_reverse = pts[i].is_reverse

        # 最后一段
        self._ref_lines.append(ReferenceLine(
            points=pts[segment_start:],
            direction=1 if current_is_reverse else 0,
            start_index=segment_start,
            end_index=len(pts) - 1,
        ))

        # right_of_way_index = 倒数第二段的 is_park 点附近
        if len(self._ref_lines) >= 2:
            # 查找最后一个 is_park 点作为路权终点
            for i in range(len(pts) - 1, -1, -1):
                if pts[i].is_park:
                    self._right_of_way_index = i
                    break
        elif len(self._ref_lines) == 1:
            self._right_of_way_index = len(self._ref_lines[0].points) - 1

    def advance_to_next(self) -> bool:
        """切换到下一段参考线，返回 False 表示已是最后一段"""
        if self._current_idx + 1 < len(self._ref_lines):
            self._current_idx += 1
            return True
        return False

    def find_closest_index(self, x: float, y: float) -> int:
        """在全局点序列中查找离 (x, y) 最近的点的索引"""
        if self._total_points == 0:
            return 0
        all_points = []
        for rl in self._ref_lines:
            all_points.extend(rl.points)
        best = 0
        best_dist = float("inf")
        for i, p in enumerate(all_points):
            d = (p.x - x) ** 2 + (p.y - y) ** 2
            if d < best_dist:
                best_dist = d
                best = i
        return best

    def find_closest_by_latlon(self, lat: float, lon: float) -> int:
        """在全局点序列中查找离 (lat, lon) 最近的点索引

        对应 C++ Tool::FindNearestPointIndex(end_pos, reference_line)。
        无 MA 时 endpoint=(0,0) → autor_index ≈ 0，min-tracking 后 stop_index ≈ 0。
        """
        if self._total_points == 0:
            return 0
        all_points = self.get_all_points()
        best = 0
        best_dist = float("inf")
        for i, p in enumerate(all_points):
            dlat = p.lat - lat
            dlon = p.lon - lon
            d = dlat * dlat + dlon * dlon
            if d < best_dist:
                best_dist = d
                best = i
        return best

    def get_all_points(self) -> list[TrajPoint]:
        """获取所有参考线的全部点（扁平化）"""
        all_points = []
        for rl in self._ref_lines:
            all_points.extend(rl.points)
        return all_points

    def get_current_segment_points(self) -> list[TrajPoint]:
        """获取当前活跃段的全部点"""
        return self.current.points

    def update_current(self, ref_line: ReferenceLine) -> None:
        """用单个 ReferenceLine 替换当前参考线列表

        用于从 GatewaySim 的 ref_mgr 同步数据到引擎共享的 ref_mgr，
        确保 UI 始终能读取到参考线数据（即使 PlanningSim 因坐标框架不一致拒绝了任务）。
        """
        self._ref_lines.clear()
        self._ref_lines.append(ref_line)
        self._current_idx = 0
        self._total_points = len(ref_line.points)

    def clear(self):
        self._ref_lines.clear()
        self._current_idx = 0
        self._right_of_way_index = 0
        self._stop_index = 0
        self._total_points = 0
