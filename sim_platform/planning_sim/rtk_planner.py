"""RTK 轨迹规划器 — Python 等价实现 C++ RTKPlanner (F-09-02)

将参考线截取规划长度段 → 转为局部规划轨迹 → 处理障碍物 → 速度规划
"""

import math
from typing import Optional

from ..models.sim_messages import (
    TrajPoint, PlanningTrajectoryPoint, Obstacle,
)
from ..gateway_sim.reference_line_mgr import ReferenceLine


class RTKPlanner:
    """RTK 基准轨迹规划器

    将参考线转为局部规划轨迹，处理障碍物产生停车点。
    """

    def __init__(
        self,
        plan_length: float = 80.0,
        ref_decel: float = 1.0,
        vehicle_width: float = 3.7,
    ):
        self.plan_length = plan_length
        self.ref_decel = ref_decel
        self.vehicle_width = vehicle_width

    def plan(
        self,
        ref_line: ReferenceLine,
        key_index: int,
        stop_index: int,
        obstacles: Optional[list[Obstacle]] = None,
    ) -> tuple[list[PlanningTrajectoryPoint], int]:
        """执行一步 RTK 规划

        Args:
            ref_line: 当前参考线
            key_index: 车辆在参考线上的最近点索引
            stop_index: 目标停车点索引
            obstacles: 障碍物列表

        Returns:
            (规划轨迹点列表, 更新后的 stop_index)
        """
        pts = ref_line.points
        if not pts:
            return [], stop_index

        cur_s = pts[key_index].s if key_index < len(pts) else 0.0
        run_road: list[TrajPoint] = []
        for i in range(key_index, len(pts)):
            if pts[i].s - cur_s < self.plan_length:
                run_road.append(pts[i])
            else:
                break

        if not run_road:
            return [], stop_index

        # 转为 PlanningTrajectoryPoint
        start_s = run_road[0].s
        trajectory = []
        for rp in run_road:
            pt = PlanningTrajectoryPoint(
                x=rp.x,
                y=rp.y,
                heading=rp.theta,
                velocity=rp.v,
                curvature=rp.curvature,
                s=rp.s - start_s,
                lat=rp.lat,
                lon=rp.lon,
                altitude=rp.altitude,
                planned_v=rp.planned_v,
            )
            trajectory.append(pt)

        # 障碍物处理
        if obstacles:
            new_stop = self._deal_obstacles(trajectory, obstacles)
            if new_stop < stop_index:
                stop_index = new_stop

        # 速度规划
        from .velocity_planner import VelocityPlanner
        VelocityPlanner.plan_velocity(
            cur_index=0,
            target_index=min(stop_index, len(trajectory) - 1),
            trajectory=trajectory,
            ref_decel=self.ref_decel,
        )

        return trajectory, stop_index

    def _deal_obstacles(
        self,
        trajectory: list[PlanningTrajectoryPoint],
        obstacles: list[Obstacle],
    ) -> int:
        """处理障碍物，返回碰撞触发的最小 stop_index"""
        min_collision_index = len(trajectory) - 1
        half_width = self.vehicle_width / 2.0 + 0.5

        for obs in obstacles:
            if not obs.corners:
                continue
            # 计算障碍物到轨迹各点的最短距离
            for i, tp in enumerate(trajectory):
                dist = self._point_to_polygon_distance(
                    tp.x, tp.y, obs.corners
                )
                if dist < half_width:
                    if i < min_collision_index:
                        min_collision_index = i
                    break

        return max(0, min_collision_index)

    @staticmethod
    def _point_to_polygon_distance(
        px: float, py: float, corners: list[tuple[float, float]]
    ) -> float:
        """计算点到凸多边形的最短距离 (SAT 简化版)

        如果点在多边形内，返回 0
        """
        if not corners:
            return float("inf")
        n = len(corners)
        inside = True
        min_dist = float("inf")

        for i in range(n):
            x1, y1 = corners[i]
            x2, y2 = corners[(i + 1) % n]

            # 边法向量方向检测 (点在多边形内)
            edge_x = x2 - x1
            edge_y = y2 - y1
            normal_x = -edge_y
            normal_y = edge_x

            # 点到边所在直线的投影
            vx = px - x1
            vy = py - y1
            proj = vx * normal_x + vy * normal_y
            if proj > 0:
                inside = False

            # 点到线段的最短距离
            seg_dist = RTKPlanner._point_to_segment_distance(px, py, x1, y1, x2, y2)
            if seg_dist < min_dist:
                min_dist = seg_dist

        return 0.0 if inside else min_dist

    @staticmethod
    def _point_to_segment_distance(
        px: float, py: float,
        x1: float, y1: float, x2: float, y2: float,
    ) -> float:
        """点到线段的最短距离"""
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
