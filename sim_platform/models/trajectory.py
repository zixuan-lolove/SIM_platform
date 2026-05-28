"""轨迹数据模型 — 参考 C++ TrajectoryPoint / PlanningResult"""

import math
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..planning_sim.coordinate_converter import LocalCoordinateConverter


@dataclass
class TrajectoryPoint:
    """单个轨迹路径点"""
    x: float = 0.0           # ENU X 坐标 (m)
    y: float = 0.0           # ENU Y 坐标 (m)
    heading: float = 0.0     # 参考航向角 (rad)
    velocity: float = 0.0    # 参考速度 (m/s)
    curvature: float = 0.0   # 路径曲率 (1/m)
    s: float = 0.0           # 累计里程 (m)


class Trajectory:
    """轨迹 — 有序路径点序列"""

    def __init__(self, points: list[TrajectoryPoint] | None = None):
        self.points: list[TrajectoryPoint] = points or []
        self._build_s_index()

    def _build_s_index(self):
        """构建累计里程索引"""
        s = 0.0
        for i, p in enumerate(self.points):
            if i > 0:
                prev = self.points[i - 1]
                dx = p.x - prev.x
                dy = p.y - prev.y
                s += math.hypot(dx, dy)
            p.s = s

    # ========== 工厂方法 ==========

    @classmethod
    def from_csv(cls, path: str | Path) -> "Trajectory":
        """从 CSV 文件加载轨迹
        支持列名: x, y, heading, velocity, curvature
        或: lat, lon, heading, velocity  (会自动用第一个点做原点转 ENU)
        """
        points = []
        content = cls._read_text_file(str(path))
        lines = content.splitlines()
        reader = csv.DictReader(lines)
        rows = list(reader)
        if not rows:
            return cls()

        fieldnames = {k.strip().lower() for k in rows[0].keys()}

        # 检测是经纬度还是 ENU
        is_latlon = "lat" in fieldnames and "lon" in fieldnames
        converter = LocalCoordinateConverter()

        for row in rows:
            row = {k.strip().lower(): v for k, v in row.items()}
            if is_latlon:
                lat = float(row["lat"])
                lon = float(row["lon"])
                if not points:
                    converter.set_reference(lat, lon)
                x, y = converter.latlon_to_xy(lat, lon)
            else:
                x = float(row.get("x", 0))
                y = float(row.get("y", 0))

            heading = math.radians(float(row.get("heading", row.get("theta", 0))))
            velocity = float(row.get("velocity", row.get("v", 0)))
            curvature = float(row.get("curvature", 0))
            points.append(TrajectoryPoint(x=x, y=y, heading=heading,
                                          velocity=velocity, curvature=curvature))
        return cls(points)

    @classmethod
    def from_json(cls, path: str | Path) -> "Trajectory":
        """从 JSON 文件加载轨迹"""
        content = cls._read_text_file(str(path))
        data = json.loads(content)
        pts = data if isinstance(data, list) else data.get("points", data.get("trajectory", []))
        points = []
        for item in pts:
            points.append(TrajectoryPoint(
                x=float(item.get("x", 0)),
                y=float(item.get("y", 0)),
                heading=float(item.get("heading", item.get("theta", 0))),
                velocity=float(item.get("velocity", item.get("v", 0))),
                curvature=float(item.get("curvature", 0)),
            ))
        return cls(points)

    @classmethod
    def generate_straight(cls, length: float = 100.0, velocity: float = 5.0,
                          heading: float = 0.0, step: float = 1.0,
                          origin_x: float = 0.0, origin_y: float = 0.0,
                          origin_heading: float = 0.0) -> "Trajectory":
        """生成直线轨迹，可选从指定原点变换"""
        points = []
        n = int(length / step) + 1
        cos_h = math.cos(origin_heading)
        sin_h = math.sin(origin_heading)
        for i in range(n):
            s = i * step
            lx = s * math.cos(heading)
            ly = s * math.sin(heading)
            # 变换到全局坐标
            gx = origin_x + lx * cos_h - ly * sin_h
            gy = origin_y + lx * sin_h + ly * cos_h
            gh = cls._normalize_angle(heading + origin_heading)
            points.append(TrajectoryPoint(
                x=gx, y=gy, heading=gh,
                velocity=velocity, curvature=0.0,
            ))
        return cls(points)

    @classmethod
    def generate_circle(cls, radius: float = 25.0, velocity: float = 5.0,
                        step: float = 0.5,
                        origin_x: float = 0.0, origin_y: float = 0.0,
                        origin_heading: float = 0.0) -> "Trajectory":
        """生成圆形轨迹（逆时针），可选从指定原点变换

        圆心在车辆左侧（CCW），起点为车辆当前位置，切线沿车辆航向。
        """
        points = []
        circumference = 2 * math.pi * radius
        n = int(circumference / step) + 1
        cos_h = math.cos(origin_heading)
        sin_h = math.sin(origin_heading)
        for i in range(n):
            angle = 2 * math.pi * i / (n - 1) if n > 1 else 0
            # 局部坐标：圆心在 (0, -R)，起点 (0, 0)，切线沿 +x（航向 0）
            lx = radius * math.sin(angle)
            ly = -radius + radius * math.cos(angle)
            lh = angle  # 起点处 angle=0, 切线沿 +x
            gx = origin_x + lx * cos_h - ly * sin_h
            gy = origin_y + lx * sin_h + ly * cos_h
            gh = cls._normalize_angle(lh + origin_heading)
            points.append(TrajectoryPoint(
                x=gx, y=gy, heading=gh,
                velocity=velocity, curvature=1.0 / radius,
            ))
        return cls(points)

    @classmethod
    def generate_lane_change(cls, length: float = 80.0, lateral_offset: float = 3.5,
                             velocity: float = 8.0, step: float = 0.5,
                             origin_x: float = 0.0, origin_y: float = 0.0,
                             origin_heading: float = 0.0) -> "Trajectory":
        """生成变道轨迹（正弦曲线），可选从指定原点变换"""
        points = []
        n = int(length / step) + 1
        cos_h = math.cos(origin_heading)
        sin_h = math.sin(origin_heading)
        for i in range(n):
            s = i * step
            ratio = s / length
            lx = s
            ly = lateral_offset * (ratio - math.sin(2 * math.pi * ratio) / (2 * math.pi))
            # 航向角由变道曲线导数决定
            dy_dx = (lateral_offset / length) * (1 - math.cos(2 * math.pi * ratio))
            lh = math.atan(dy_dx)
            # 曲率由二阶导数决定
            d2y_dx2 = (lateral_offset / (length * length)) * 2 * math.pi * math.sin(2 * math.pi * ratio)
            curvature = d2y_dx2 / ((1 + dy_dx ** 2) ** 1.5) if (1 + dy_dx ** 2) > 0 else 0
            # 变换到全局坐标
            gx = origin_x + lx * cos_h - ly * sin_h
            gy = origin_y + lx * sin_h + ly * cos_h
            gh = cls._normalize_angle(lh + origin_heading)
            points.append(TrajectoryPoint(
                x=gx, y=gy, heading=gh,
                velocity=velocity, curvature=curvature,
            ))
        return cls(points)

    # ========== 查询方法 ==========

    def find_closest_index(self, x: float, y: float) -> int:
        """查找距离 (x,y) 最近的轨迹点索引"""
        if not self.points:
            return 0
        best_idx = 0
        best_dist = float("inf")
        for i, p in enumerate(self.points):
            d = (p.x - x) ** 2 + (p.y - y) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    def get_lookahead_point(self, x: float, y: float, lookahead: float) -> Optional[TrajectoryPoint]:
        """从最近点向前搜索预瞄距离处的轨迹点"""
        if not self.points:
            return None
        start_idx = self.find_closest_index(x, y)
        # 从最近点向前搜索第一个距离 >= lookahead 的点
        for i in range(start_idx, len(self.points)):
            p = self.points[i]
            d = math.sqrt((p.x - x) ** 2 + (p.y - y) ** 2)
            if d >= lookahead:
                return p
        return self.points[-1]

    def get_point_at(self, index: int) -> Optional[TrajectoryPoint]:
        if 0 <= index < len(self.points):
            return self.points[index]
        return None

    def get_velocity_at(self, x: float, y: float) -> float:
        """获取最近轨迹点的参考速度"""
        idx = self.find_closest_index(x, y)
        p = self.get_point_at(idx)
        return p.velocity if p else 0.0

    @property
    def length(self) -> float:
        if not self.points:
            return 0.0
        return self.points[-1].s

    def __len__(self) -> int:
        return len(self.points)

    def __bool__(self) -> bool:
        return len(self.points) > 0

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """归一化到 [-π, π]"""
        return math.atan2(math.sin(angle), math.cos(angle))

    @staticmethod
    def _read_text_file(path: str) -> str:
        """读取文本文件，自动尝试 utf-8 / gbk 编码"""
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def to_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["x", "y", "heading", "velocity", "curvature", "s"])
            for p in self.points:
                writer.writerow([p.x, p.y, p.heading, p.velocity, p.curvature, p.s])
