"""车辆运动学引擎 — 阿克曼转向模型（自行车模型）"""

import math
from ..models.vehicle_params import VehicleParams
from .vehicle_state import VehicleState


class KinematicEngine:
    """阿克曼转向运动学引擎
    采用后轴中心为参考点的自行车模型，欧拉积分递推。
    """

    def __init__(self, params: VehicleParams, dt: float = 0.01):
        self.params = params
        self.dt = dt

    def step(
        self,
        state: VehicleState,
        target_velocity_kmh: float,
        target_steer_sw_deg: float,
        gear: int,
        brake_pressure: float,
    ) -> VehicleState:
        """执行一步运动学更新

        Args:
            state: 当前车辆状态
            target_velocity_kmh: 目标车速 (km/h)
            target_steer_sw_deg: 目标方向盘转角 (deg)
            gear: 档位 (0=P, 1=R, 2=N, 3=D)
            brake_pressure: 制动压力 (MPa)

        Returns:
            更新后的车辆状态（新对象）
        """
        new_state = state.clone()
        new_state.timestamp += self.dt

        # --- 档位处理 ---
        if gear == 0:  # P 档: 速度强制为 0
            new_state.v = 0.0
            new_state.acceleration = 0.0
            new_state.yaw_rate = 0.0
            new_state.gear = gear
            new_state.brake_pressure = brake_pressure
            return new_state

        new_state.gear = gear
        new_state.brake_pressure = brake_pressure

        # --- 转向角计算 ---
        # 方向盘转角 → 前轮转角
        target_steer_rad = math.radians(target_steer_sw_deg) / self.params.steer_ratio
        # 限幅
        max_sr = self.params.max_steer_angle_rad
        target_steer_rad = max(-max_sr, min(max_sr, target_steer_rad))
        new_state.steer_angle = target_steer_rad

        # --- 速度计算 ---
        target_v_ms = target_velocity_kmh / 3.6
        # 限幅
        target_v_ms = max(0.0, min(self.params.max_speed_ms, target_v_ms))

        # 倒车时速度取负
        if gear == 1:  # R 档
            target_v_ms = -target_v_ms

        # 一阶惯性环节平滑过渡
        tau = self.params.speed_time_constant
        if tau > 0:
            alpha = self.dt / tau
            alpha = min(alpha, 1.0)  # 防止过冲
            new_state.v = state.v + alpha * (target_v_ms - state.v)
        else:
            new_state.v = target_v_ms

        # 制动减速
        if brake_pressure > 0 and abs(new_state.v) > 1e-6:
            brake_decel = self.params.brake_gain * brake_pressure
            speed_sign = 1.0 if new_state.v > 0 else -1.0
            new_state.v = new_state.v - speed_sign * brake_decel * self.dt
            # 速度不反向（制动不能把前进变成倒退）
            if speed_sign > 0 and new_state.v < 0:
                new_state.v = 0.0
            elif speed_sign < 0 and new_state.v > 0:
                new_state.v = 0.0

        # N 档: 无驱动力，仅受制动和阻力影响
        if gear == 2:
            if brake_pressure < 1e-6:
                # 滚动阻力减速
                resist = self.params.rolling_resistance * 9.81
                speed_sign = 1.0 if new_state.v > 0 else (-1.0 if new_state.v < 0 else 0)
                new_state.v -= speed_sign * resist * self.dt
                if speed_sign > 0 and new_state.v < 0:
                    new_state.v = 0.0
                elif speed_sign < 0 and new_state.v > 0:
                    new_state.v = 0.0

        # --- 加速度 ---
        new_state.acceleration = (new_state.v - state.v) / self.dt

        # --- 位姿更新（欧拉积分） ---
        v = new_state.v
        theta = state.theta
        steer = new_state.steer_angle

        new_state.x = state.x + v * math.cos(theta) * self.dt
        new_state.y = state.y + v * math.sin(theta) * self.dt

        # 横摆角速度
        if abs(v) > 1e-6:
            new_state.yaw_rate = v * math.tan(steer) / self.params.wheelbase
        else:
            new_state.yaw_rate = 0.0

        new_state.theta = theta + new_state.yaw_rate * self.dt
        # 航向角归一化到 [-π, π]
        new_state.theta = math.atan2(
            math.sin(new_state.theta), math.cos(new_state.theta)
        )

        return new_state
