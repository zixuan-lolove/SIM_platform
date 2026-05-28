"""车辆状态数据模型"""

from dataclasses import dataclass
import math


@dataclass
class VehicleState:
    """车辆实时状态"""
    x: float = 0.0              # 后轴中心 X 坐标 (m)
    y: float = 0.0              # 后轴中心 Y 坐标 (m)
    theta: float = 0.0          # 航向角 (rad)
    v: float = 0.0              # 纵向速度 (m/s)
    steer_angle: float = 0.0    # 前轮转角 (rad)
    gear: int = 2               # 档位: 0=P, 1=R, 2=N, 3=D
    brake_pressure: float = 0.0 # 制动压力 (MPa)
    acceleration: float = 0.0   # 纵向加速度 (m/s²)
    yaw_rate: float = 0.0       # 横摆角速度 (rad/s)
    timestamp: float = 0.0      # 仿真时间戳 (s)

    GEAR_NAMES = {0: "P", 1: "R", 2: "N", 3: "D"}

    @property
    def theta_deg(self) -> float:
        """航向角 (deg)"""
        return math.degrees(self.theta)

    @property
    def v_kmh(self) -> float:
        """纵向速度 (km/h)"""
        return self.v * 3.6

    @property
    def steer_angle_deg(self) -> float:
        """前轮转角 (deg)"""
        return math.degrees(self.steer_angle)

    @property
    def gear_name(self) -> str:
        """档位名称"""
        return self.GEAR_NAMES.get(self.gear, "?")

    @property
    def turn_radius(self) -> float:
        """当前转弯半径 (m), 直行时为 inf"""
        if abs(self.steer_angle) < 1e-6 or abs(self.v) < 1e-3:
            return float("inf")
        # R = L / tan(δ), 需要轴距, 此处返回曲率半径由外部计算
        return float("inf")

    def turn_radius_with_wheelbase(self, wheelbase: float) -> float:
        """根据轴距计算转弯半径"""
        if abs(self.steer_angle) < 1e-6:
            return float("inf")
        return wheelbase / math.tan(abs(self.steer_angle))

    @property
    def curvature(self) -> float:
        """行驶曲率 (1/m)"""
        if abs(self.v) < 1e-3:
            return 0.0
        return self.yaw_rate / self.v if abs(self.v) > 1e-3 else 0.0

    def front_axle_position(self, wheelbase: float) -> tuple[float, float]:
        """前轴中心全局坐标"""
        return (
            self.x + wheelbase * math.cos(self.theta),
            self.y + wheelbase * math.sin(self.theta),
        )

    def cog_position(self, cog_to_rear_axle: float) -> tuple[float, float]:
        """质心全局坐标"""
        return (
            self.x + cog_to_rear_axle * math.cos(self.theta),
            self.y + cog_to_rear_axle * math.sin(self.theta),
        )

    def clone(self) -> "VehicleState":
        """深拷贝"""
        return VehicleState(
            x=self.x, y=self.y, theta=self.theta,
            v=self.v, steer_angle=self.steer_angle,
            gear=self.gear, brake_pressure=self.brake_pressure,
            acceleration=self.acceleration, yaw_rate=self.yaw_rate,
            timestamp=self.timestamp,
        )
