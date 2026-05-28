"""惯导定位数据模型 — 模拟 DDS LocalizationData 消息"""

from dataclasses import dataclass, field
import math

from ..core.vehicle_state import VehicleState


@dataclass
class InsData:
    """惯导定位数据
    模拟真实系统中通过 DDS 接收的 INS/IMU 融合定位数据。
    采用 ENU 局部坐标系，与运动学模型坐标系一致。
    """

    # === 原始惯导输入（WGS84 地理坐标） ===
    latitude: float = 0.0        # WGS84 纬度 (deg)
    longitude: float = 0.0       # WGS84 经度 (deg)
    heading_geo: float = 0.0     # 地理航向 (0=北, CW, deg)

    # === 位置（ENU 局部坐标，由经纬度转换得到） ===
    local_x: float = 0.0         # X 坐标 / 东向 (m)
    local_y: float = 0.0         # Y 坐标 / 北向 (m)
    local_z: float = 0.0         # Z 坐标 / 海拔高程 (m)

    # === 姿态角 ===
    yaw: float = 0.0             # 航向角 (deg)，与正东夹角，逆时针为正
    roll: float = 0.0            # 横滚角 (deg)
    pitch: float = 0.0           # 俯仰角 (deg)

    # === 速度 ===
    vel_east: float = 0.0        # 东向速度 (m/s)
    vel_north: float = 0.0       # 北向速度 (m/s)
    vel_up: float = 0.0          # 天向速度 (m/s)

    # === GNSS 状态 ===
    gnss_status: int = 0         # 定位状态: 0=无效, 1=单点, 2=差分, 3=RTK Fix, 4=RTK Float
    satellite_count: int = 0     # 可见卫星数
    hdop: float = 0.0            # 水平精度因子
    vdop: float = 0.0            # 垂直精度因子

    # === 时间戳 ===
    timestamp: float = 0.0       # 定位数据时间戳 (s)

    GNSS_STATUS_NAMES = {
        0: "无效", 1: "单点", 2: "差分", 3: "RTK Fix", 4: "RTK Float"
    }

    @property
    def gnss_status_name(self) -> str:
        return self.GNSS_STATUS_NAMES.get(self.gnss_status, "未知")

    @property
    def yaw_rad(self) -> float:
        """航向角 (rad)"""
        return math.radians(self.yaw)

    @property
    def speed(self) -> float:
        """合速度 (m/s)"""
        return math.sqrt(self.vel_east ** 2 + self.vel_north ** 2)

    def to_vehicle_state(self) -> VehicleState:
        """将惯导数据转换为车辆初始状态

        航向角 yaw 映射为运动学模型的 theta（均以正东为 0，逆时针为正）。
        合速度映射为纵向速度 v（忽略横向分量，矿卡场景侧滑可忽略）。
        """
        return VehicleState(
            x=self.local_x,
            y=self.local_y,
            theta=self.yaw_rad,
            v=self.speed,
            steer_angle=0.0,
            gear=2,              # 默认 N 档
            brake_pressure=0.0,
            acceleration=0.0,
            yaw_rate=0.0,
            timestamp=0.0,
        )

    @classmethod
    def from_vehicle_state(cls, state: VehicleState) -> "InsData":
        """从当前车辆状态反填惯导数据（捕获当前位置）"""
        return cls(
            local_x=state.x,
            local_y=state.y,
            local_z=0.0,
            yaw=state.theta_deg,
            roll=0.0,
            pitch=0.0,
            vel_east=state.v * math.cos(state.theta),
            vel_north=state.v * math.sin(state.theta),
            vel_up=0.0,
        )

    def clone(self) -> "InsData":
        return InsData(
            latitude=self.latitude, longitude=self.longitude, heading_geo=self.heading_geo,
            local_x=self.local_x, local_y=self.local_y, local_z=self.local_z,
            yaw=self.yaw, roll=self.roll, pitch=self.pitch,
            vel_east=self.vel_east, vel_north=self.vel_north, vel_up=self.vel_up,
            gnss_status=self.gnss_status, satellite_count=self.satellite_count,
            hdop=self.hdop, vdop=self.vdop, timestamp=self.timestamp,
        )
