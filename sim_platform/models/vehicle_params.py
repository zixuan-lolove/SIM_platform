"""车辆参数数据模型"""

from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class VehicleParams:
    """电动宽体矿卡车辆物理参数"""

    # === 基本尺寸 ===
    wheelbase: float = 4.2           # 轴距 L (m)
    length: float = 9.5              # 车长 (m)
    width: float = 3.7               # 车宽 (m)
    height: float = 4.0              # 车高 (m)
    front_track: float = 2.8         # 前轮距 (m)
    rear_track: float = 2.8          # 后轮距 (m)

    # === 悬臂尺寸 ===
    front_overhang: float = 1.2      # 前轴到前保险杠距离 (m)
    rear_overhang: float = 1.1       # 后轴到后保险杠距离 (m)

    # === 质心位置 ===
    cog_to_front_axle: float = 2.1   # 前轴到质心距离 a (m)
    cog_to_rear_axle: float = 2.1    # 后轴到质心距离 b (m)

    # === 转向参数 ===
    steer_ratio: float = 20.0        # 转向传动比 i_s
    max_steer_angle: float = 35.0    # 最大前轮转角 (deg)

    # === 质量参数 (kg) ===
    mass_empty: float = 30000.0
    mass_full: float = 95000.0
    max_payload: float = 65000.0

    # === 制动参数 ===
    max_brake_pressure: float = 10.0 # 最大制动压力 (MPa)
    brake_gain: float = 0.5          # 制动增益 k_b (m/s²/MPa)

    # === 动力参数 ===
    max_speed: float = 30.0          # 最高车速 (km/h)
    speed_time_constant: float = 0.5 # 速度响应时间常数 τ_v (s)

    # === 轮胎参数 ===
    tire_radius: float = 0.85        # 轮胎滚动半径 (m)
    rolling_resistance: float = 0.02 # 滚动阻力系数

    # === 运动学约束 ===
    min_turn_radius: float = 15.0    # 最小转弯半径 (m)

    # === 导出属性 ===
    @property
    def max_steer_angle_rad(self) -> float:
        """最大前轮转角 (rad)"""
        import math
        return math.radians(self.max_steer_angle)

    @property
    def max_speed_ms(self) -> float:
        """最高车速 (m/s)"""
        return self.max_speed / 3.6

    @classmethod
    def from_yaml(cls, path: str | Path) -> "VehicleParams":
        """从 YAML 文件加载车辆参数"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        vehicle_data = data.get("vehicle", data)
        # 过滤掉非字段的键
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in vehicle_data.items() if k in field_names}
        return cls(**filtered)

    def to_yaml(self, path: str | Path) -> None:
        """保存车辆参数到 YAML 文件"""
        data = {"vehicle": {}}
        for f in self.__dataclass_fields__:
            data["vehicle"][f] = getattr(self, f)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
