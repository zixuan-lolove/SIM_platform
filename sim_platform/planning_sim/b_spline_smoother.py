"""B 样条平滑器 — Python 等价实现 C++ BSplineSmoother (F-09-01)

管线: 经纬度转 XY → 三次 B 样条平滑 (200 点) → 0.2m 步长重采样 → XY 转回经纬度
"""

import math
from ..models.sim_messages import TaskTraj, TrajPoint
from .coordinate_converter import LocalCoordinateConverter


def _find_nearest_point(x: float, y: float, pts: list) -> "TrajPoint":
    """在候选点列表中找到离 (x, y) 最近的点"""
    best = pts[0]
    best_dist = float("inf")
    for p in pts:
        d = (p.x - x) ** 2 + (p.y - y) ** 2
        if d < best_dist:
            best_dist = d
            best = p
    return best


class BSplineSmoother:
    """三次 B 样条参考线平滑器"""

    def smooth(self, input_traj: TaskTraj) -> TaskTraj:
        """主平滑入口"""
        pts = input_traj.points
        if len(pts) < 3:
            return input_traj

        # 以第一个点为参考点，转 XY
        ref_lat = pts[0].lat
        ref_lon = pts[0].lon
        converter = LocalCoordinateConverter()
        converter.set_reference(ref_lat, ref_lon)
        raw_xy = [converter.latlon_to_xy(p.lat, p.lon) for p in pts]

        # B 样条平滑 (200 点)
        smooth_xy = self._smooth_raw(raw_xy, 200)

        # 0.2m 固定步长重采样
        resampled = self._resample_fixed_step(smooth_xy, 0.2)

        # 构建输出 — 为每个重采样点从原始点中查找最近点来继承属性
        output = TaskTraj(task_id=input_traj.task_id)
        for _, (x, y) in enumerate(resampled):
            lat, lon = converter.xy_to_latlon(x, y)
            tp = TrajPoint()
            tp.x = x
            tp.y = y
            tp.lat = lat
            tp.lon = lon

            # 在原始点中找到离当前重采样点最近的点，继承其属性
            src = _find_nearest_point(x, y, pts)
            tp.heading = src.heading
            tp.theta = src.theta
            tp.altitude = src.altitude
            tp.v = src.v
            tp.planned_v = src.planned_v
            tp.is_reverse = src.is_reverse
            tp.is_park = src.is_park
            tp.is_preview = src.is_preview
            tp.has_left_wall = src.has_left_wall
            tp.has_right_wall = src.has_right_wall
            tp.is_lift_forward = src.is_lift_forward
            tp.is_re_park = src.is_re_park
            tp.slope = src.slope
            tp.curvature = src.curvature
            output.points.append(tp)

        # 重建累计里程
        s = 0.0
        for i, p in enumerate(output.points):
            if i > 0:
                prev = output.points[i - 1]
                s += math.hypot(p.x - prev.x, p.y - prev.y)
            p.s = s

        return output

    # ========== B 样条核心 ==========

    @staticmethod
    def _bspline_basis(t: float, i: int) -> float:
        """三次 B 样条基函数"""
        if i == 0:
            return (-t**3 + 3 * t**2 - 3 * t + 1) / 6.0
        elif i == 1:
            return (3 * t**3 - 6 * t**2 + 4) / 6.0
        elif i == 2:
            return (-3 * t**3 + 3 * t**2 + 3 * t + 1) / 6.0
        elif i == 3:
            return t**3 / 6.0
        return 0.0

    @staticmethod
    def _calc_smooth_point(t: float, pts: list[tuple[float, float]]) -> tuple[float, float]:
        """计算参数 t 处的 B 样条值 (t ∈ [0, 1])"""
        n = len(pts) - 1
        if n <= 0:
            return (0.0, 0.0)

        k = int(t * n)
        if k >= n:
            k = n - 1
        lt = t * n - k

        x, y = 0.0, 0.0
        for i in range(4):
            idx = k + i - 1
            if idx < 0:
                idx = 0
            if idx > n:
                idx = n
            b = BSplineSmoother._bspline_basis(lt, i)
            x += pts[idx][0] * b
            y += pts[idx][1] * b
        return (x, y)

    def _smooth_raw(
        self, raw_xy: list[tuple[float, float]], num: int = 200
    ) -> list[tuple[float, float]]:
        """生成 num 个均匀分布的 B 样条点"""
        step = 1.0 / (num - 1)
        return [self._calc_smooth_point(i * step, raw_xy) for i in range(num)]

    # ========== 重采样 ==========

    @staticmethod
    def _resample_fixed_step(
        smooth_xy: list[tuple[float, float]], step: float = 0.2
    ) -> list[tuple[float, float]]:
        """按固定步长 (0.2m) 重采样"""
        if not smooth_xy:
            return []

        resampled = [smooth_xy[0]]
        dist_sum = 0.0

        for i in range(1, len(smooth_xy)):
            prev = smooth_xy[i - 1]
            curr = smooth_xy[i]
            dx = curr[0] - prev[0]
            dy = curr[1] - prev[1]
            seg_dist = math.sqrt(dx * dx + dy * dy)

            if seg_dist < 1e-6:
                continue

            dist_sum += seg_dist
            while dist_sum >= step - 1e-6:
                over = dist_sum - step
                ratio = (seg_dist - over) / seg_dist
                x = prev[0] + ratio * (curr[0] - prev[0])
                y = prev[1] + ratio * (curr[1] - prev[1])
                resampled.append((x, y))
                dist_sum = over

        # 保留最后一个点
        last = smooth_xy[-1]
        if math.hypot(resampled[-1][0] - last[0], resampled[-1][1] - last[1]) > 1e-3:
            resampled.append(last)

        return resampled

    # ========== 坐标转换 (委托给 LocalCoordinateConverter) ==========
