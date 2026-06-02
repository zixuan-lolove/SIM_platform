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
    """三次 B 样条参考线平滑器

    参数:
        ctrl_step: 控制点采样步长，每隔 N 个原始点取 1 个作为 B 样条控制点。
                   值越大越平滑，默认 4。
        resample_step: 重采样步长 (m)，默认 0.2。
    """

    def __init__(self, ctrl_step: int = 4, resample_step: float = 0.2):
        self._ctrl_step = ctrl_step
        self._resample_step = resample_step

    def smooth(self, input_traj: TaskTraj) -> TaskTraj:
        """Clamped B 样条平滑: 锁首尾端点, 中间控制点做 B 样条逼近"""
        pts = input_traj.points
        if len(pts) < 3:
            return input_traj

        # 直接使用 TrajPoint 自带的 ENU x,y (避免 lat/lon↔XY 重转换引入误差)
        raw_xy = [(p.x, p.y) for p in pts]

        start_xy = raw_xy[0]
        end_xy = raw_xy[-1]

        # ── 下采样控制点 ──
        ctrl_xy = raw_xy[::self._ctrl_step]
        ctrl_xy = list(ctrl_xy)
        if ctrl_xy[-1] != end_xy:
            ctrl_xy.append(end_xy)
        if len(ctrl_xy) < 3:
            ctrl_xy = [start_xy, raw_xy[len(raw_xy)//2], end_xy]

        # ── Clamped 端点: 首尾控制点各重复 k=4 次 (三次 B 样条) ──
        K = 4  # cubic B-spline 阶数
        clamped_ctrl = [start_xy] * (K - 1) + ctrl_xy + [end_xy] * (K - 1)

        # B 样条平滑
        smooth_num = max(200, len(clamped_ctrl) * 6)
        smooth_xy = self._smooth_raw(clamped_ctrl, smooth_num)

        # 固定步长重采样
        resampled = self._resample_fixed_step(smooth_xy, self._resample_step)

        # ── 端点硬修正 ──
        if len(resampled) >= 2:
            resampled[0] = start_xy
            resampled[-1] = end_xy

        # 构建输出 (XY 直接从 smoothed 取值, lat/lon 从原始点最近点继承)
        output = TaskTraj(task_id=input_traj.task_id)
        for _, (x, y) in enumerate(resampled):
            tp = TrajPoint()
            tp.x = x
            tp.y = y
            # lat/lon 从最近原始点继承 (近似)
            src = _find_nearest_point(x, y, pts)
            tp.lat = src.lat
            tp.lon = src.lon
            tp = TrajPoint()
            tp.x = x
            tp.y = y

            src = _find_nearest_point(x, y, pts)
            tp.lat = src.lat
            tp.lon = src.lon
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

        # 从平滑后的 XY 几何反算 theta 和 heading
        n_pts = len(output.points)
        for i in range(n_pts):
            if n_pts >= 2:
                if i == 0:
                    dx = output.points[1].x - output.points[0].x
                    dy = output.points[1].y - output.points[0].y
                elif i == n_pts - 1:
                    dx = output.points[-1].x - output.points[-2].x
                    dy = output.points[-1].y - output.points[-2].y
                else:
                    dx = output.points[i + 1].x - output.points[i - 1].x
                    dy = output.points[i + 1].y - output.points[i - 1].y
                if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                    theta = math.atan2(dy, dx)
                    output.points[i].theta = theta
                    hdg_deg = 90.0 - math.degrees(theta)
                    while hdg_deg < 0:
                        hdg_deg += 360.0
                    while hdg_deg >= 360.0:
                        hdg_deg -= 360.0
                    output.points[i].heading = hdg_deg

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
