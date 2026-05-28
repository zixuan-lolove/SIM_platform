""".log 数据帧模型（为后续数据回放预留）"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LogFrame:
    """单帧日志数据"""
    timestamp: float = 0.0          # 时间戳 (s)

    # 车辆状态
    x: float = 0.0                  # X 坐标 (m)
    y: float = 0.0                  # Y 坐标 (m)
    theta: float = 0.0              # 航向角 (rad)
    velocity: float = 0.0           # 纵向速度 (m/s)
    steer_angle: float = 0.0        # 前轮转角 (rad)
    gear: int = 3                   # 档位 0=P,1=R,2=N,3=D
    brake_pressure: float = 0.0     # 制动压力 (MPa)

    # 扩展字段
    acceleration_x: float = 0.0     # 纵向加速度 (m/s²)
    acceleration_y: float = 0.0     # 横向加速度 (m/s²)
    yaw_rate: float = 0.0           # 横摆角速度 (rad/s)
    curvature: Optional[float] = None  # 路径曲率 (1/m)

    # 规划/决策数据
    ref_line_id: Optional[int] = None
    task_state: Optional[int] = None
    fault_code: Optional[int] = None
