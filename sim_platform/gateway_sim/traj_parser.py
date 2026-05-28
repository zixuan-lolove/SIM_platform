"""轨迹文件解析器 — Python 等价实现 C++ TrajParser (F-08-02/10/11)

解析 17 列 CSV 轨迹文件，提取完整的 TaskTraj 数据。
"""

import os
import math
from pathlib import Path
from typing import Optional

from ..models.sim_messages import TaskTraj, TrajPoint


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


class TrajParser:
    """17 列 CSV 轨迹解析器

    CSV 格式 (每行):
        $, road_id, heading, lat, lon, y, x, altitude, spd,
        left_dis, right_dis, attribute_1, slope, curvature, attribute_2,
        overtake_left_dis, overtake_right_dis, $

    列索引对应关系:
        0: $ (起始标记)
        1: road_id
        2: heading (deg)
        3: lat (纬度)
        4: lon (经度)
        5: y (ENU Y)
        6: x (ENU X)
        7: altitude (海拔)
        8: spd (参考速度 m/s)
        9: left_dis (左侧距离)
        10: right_dis (右侧距离)
        11: attribute_1 (7-bit 标志)
        12: slope (坡度)
        13: curvature (曲率)
        14: attribute_2 (8-bit 保留标志)
        15: overtake_left_dis (左侧超车距离)
        16: overtake_right_dis (右侧超车距离)
        17: $ (结束标记)
    """

    def parse_file(self, file_path: str | Path) -> TaskTraj:
        """解析单个 .traj CSV 文件"""
        traj = TaskTraj(task_id=str(file_path))
        content = _read_text_file(str(file_path))
        for line in content.splitlines():
            line = line.strip()
            if not line or line[0] != "$":
                continue
            parts = line.split(",")
            if len(parts) < 18:
                continue
            pt = self._parse_line(parts)
            if pt is not None:
                traj.points.append(pt)
        # 构建累计里程
        self._build_s(traj)
        return traj

    def parse_folder(self, folder_path: str | Path) -> TaskTraj:
        """在文件夹中查找唯一的 .traj 文件并解析"""
        folder = Path(folder_path)
        traj_files = list(folder.glob("*.traj"))
        if len(traj_files) == 0:
            raise FileNotFoundError(f"未找到 .traj 文件: {folder_path}")
        if len(traj_files) > 1:
            raise RuntimeError(f"存在多个 .traj 文件: {folder_path}")
        return self.parse_file(traj_files[0])

    def _parse_line(self, parts: list[str]) -> Optional[TrajPoint]:
        """解析单行 17 列数据"""
        try:
            # parts[0] 和 parts[17] 是 $ 标记
            data = [float(v.strip()) for v in parts[1:17]]
        except (ValueError, IndexError):
            return None

        pt = TrajPoint()
        pt.road_id = int(data[0])
        pt.heading = data[1]
        pt.lat = data[2]
        pt.lon = data[3]
        pt.y = data[4]
        pt.x = data[5]
        pt.altitude = data[6]
        pt.v = data[7]
        pt.left_dis = data[8]
        pt.right_dis = data[9]

        # attribute_1: 7 个位标志 (bit 1-7)
        a1 = data[10]
        pt.is_re_park = self._get_bit(a1, 1)
        pt.is_lift_forward = self._get_bit(a1, 2)
        pt.is_park = self._get_bit(a1, 3)
        pt.has_right_wall = self._get_bit(a1, 4)
        pt.has_left_wall = self._get_bit(a1, 5)
        pt.is_reverse = self._get_bit(a1, 6)
        pt.is_preview = self._get_bit(a1, 7)

        pt.slope = data[11]
        pt.curvature = data[12]

        # attribute_2: 8 个保留位 (暂存 curvature 来源标记)
        # data[13] 在 proto 中是 attribute_2 的 raw double 值
        pt.overtake_left_dis = data[14] if len(data) > 14 else 0.0
        pt.overtake_right_dis = data[15] if len(data) > 15 else 0.0

        # 地理航向 (0=北, CW) → 数学角度 (0=东, CCW): θ_math = π/2 - heading_rad
        pt.theta = math.pi / 2 - math.radians(pt.heading)
        pt.planned_v = pt.v
        pt.s = 0.0  # 由 _build_s 填充

        return pt

    @staticmethod
    def _get_bit(value: float, bit: int) -> bool:
        """提取 double 值中第 bit 位 (1-indexed)"""
        v = int(value) & 0xFF
        return ((v >> (bit - 1)) & 1) == 1

    @staticmethod
    def _build_s(traj: TaskTraj) -> None:
        """构建累计里程索引"""
        s = 0.0
        for i, pt in enumerate(traj.points):
            if i > 0:
                prev = traj.points[i - 1]
                dx = pt.x - prev.x
                dy = pt.y - prev.y
                s += math.hypot(dx, dy)
            pt.s = s
