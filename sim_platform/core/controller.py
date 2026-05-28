"""轨迹跟踪控制器 — Pure Pursuit (横向) + PID (纵向)"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models.vehicle_params import VehicleParams
from ..models.trajectory import Trajectory, TrajectoryPoint
from ..core.vehicle_state import VehicleState

if TYPE_CHECKING:
    from ..config.control_config_loader import ControlConfig


@dataclass
class ControllerOutput:
    """控制器输出 — 由横向/纵向控制器计算后合并得到"""
    steer_angle: float = 0.0       # 前轮转角 (deg)，左正右负
    target_velocity: float = 0.0   # 目标车速 (km/h)
    throttle: float = 0.0          # 油门百分比 0-100
    brake: float = 0.0             # 制动百分比 0-100

    # 跟踪状态（调试/显示用）
    cross_track_error: float = 0.0
    heading_error: float = 0.0
    speed_error: float = 0.0


class Controller(ABC):
    """控制器基类"""

    @abstractmethod
    def update(self, state: VehicleState, traj: Trajectory, dt: float = 0.01) -> ControllerOutput:
        """根据当前状态和参考轨迹计算控制指令"""
        ...

    def reset(self):
        """重置控制器内部状态"""
        pass


class PurePursuitController(Controller):
    """Pure Pursuit 横向控制器

    参照 C++ control/src/controller/lat_controller/pure_pursuit_controller.h
    参数优先从 ControlConfig (control_config.ini) 读取，与 C++ 同源。
    """

    def __init__(self, params: VehicleParams,
                 lookahead_distance: float = 8.0,
                 lookahead_speed_gain: float = 0.3,
                 config: "ControlConfig | None" = None):
        self.params = params
        if config is not None:
            self.wheelbase = config.wheel_base
            self.max_steer_deg = config.max_steer_angle
            self.max_steer_rad = math.radians(config.max_steer_angle)
            self.lookahead_distance = config.lookahead_distance
        else:
            self.wheelbase = params.wheelbase
            self.max_steer_rad = params.max_steer_angle_rad
            self.max_steer_deg = params.max_steer_angle
            self.lookahead_distance = lookahead_distance
        self.lookahead_speed_gain = lookahead_speed_gain

    def update(self, state: VehicleState, traj: Trajectory, dt: float = 0.01) -> ControllerOutput:
        if not traj:
            return ControllerOutput()

        # 动态预瞄距离（速度越高看得越远）
        lookahead = self.lookahead_distance + abs(state.v) * self.lookahead_speed_gain

        # 查找预瞄点
        target = traj.get_lookahead_point(state.x, state.y, lookahead)
        if target is None:
            return ControllerOutput()

        # 将预瞄点转到车辆局部坐标系
        dx = target.x - state.x
        dy = target.y - state.y
        cos_t = math.cos(state.theta)
        sin_t = math.sin(state.theta)
        local_x = dx * cos_t + dy * sin_t
        local_y = -dx * sin_t + dy * cos_t

        # 横向偏差 = 预瞄点到车辆纵轴的距离
        cross_track_error = local_y

        # Pure Pursuit 公式: δ = arctan(2 * L * sin(α) / ld)
        # 其中 sin(α) = local_y / ld,  ld = sqrt(local_x² + local_y²)
        ld = math.sqrt(local_x ** 2 + local_y ** 2)
        if ld < 1e-3:
            return ControllerOutput()

        sin_alpha = local_y / ld
        steer_rad = math.atan(2.0 * self.wheelbase * sin_alpha / ld)
        steer_rad = max(-self.max_steer_rad, min(self.max_steer_rad, steer_rad))

        # 航向偏差
        heading_error = self._normalize_angle(target.heading - state.theta)

        # 参考速度
        ref_velocity = traj.get_velocity_at(state.x, state.y)

        return ControllerOutput(
            steer_angle=math.degrees(steer_rad),
            target_velocity=ref_velocity * 3.6,
            cross_track_error=cross_track_error,
            heading_error=math.degrees(heading_error),
        )

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """归一化到 [-π, π]"""
        return math.atan2(math.sin(angle), math.cos(angle))


class PIDLongitudinalController(Controller):
    """PID 纵向速度控制器

    参照 C++ control/src/controller/lon_controller/spd_pid_controller.h
    参数优先从 ControlConfig (control_config.ini) 读取，与 C++ 同源。
    """

    def __init__(self, params: VehicleParams,
                 kp: float = 0.8, ki: float = 0.12, kd: float = 0.15,
                 max_throttle: float = 100.0, max_brake: float = 100.0,
                 speed_dead_zone: float = 0.3,
                 config: "ControlConfig | None" = None):
        self.params = params
        if config is not None:
            self.kp = config.pid_kp
            self.ki = config.pid_ki
            self.kd = config.pid_kd
            self.speed_dead_zone = config.pid_speed_dead_zone
        else:
            self.kp = kp
            self.ki = ki
            self.kd = kd
            self.speed_dead_zone = speed_dead_zone
        self.max_throttle = max_throttle
        self.max_brake = max_brake
        self.max_speed_kmh = params.max_speed
        self.reset()

    def reset(self):
        self._last_error: float = 0.0
        self._integral: float = 0.0

    def update(self, state: VehicleState, traj: Trajectory, dt: float = 0.01) -> ControllerOutput:
        ref_velocity_ms = traj.get_velocity_at(state.x, state.y) if traj else 0.0
        ref_velocity_kmh = ref_velocity_ms * 3.6
        current_kmh = abs(state.v) * 3.6

        speed_error = ref_velocity_kmh - current_kmh

        # 死区
        if abs(speed_error) < self.speed_dead_zone:
            self._integral = 0.0
            self._last_error = speed_error
            return ControllerOutput(target_velocity=ref_velocity_kmh, speed_error=speed_error)

        # 积分分离
        if abs(speed_error) < 5.0:
            self._integral += speed_error * dt
        else:
            self._integral = 0.0

        # 积分限幅
        max_integral = 50.0
        self._integral = max(-max_integral, min(max_integral, self._integral))

        # PID 输出
        dt_safe = dt if dt > 0 else 0.01
        derivative = (speed_error - self._last_error) / dt_safe
        output = self.kp * speed_error + self.ki * self._integral + self.kd * derivative

        self._last_error = speed_error

        if output > 0:
            throttle = min(output, self.max_throttle)
            brake = 0.0
        else:
            throttle = 0.0
            brake = min(-output, self.max_brake)

        return ControllerOutput(
            target_velocity=ref_velocity_kmh,
            throttle=throttle,
            brake=brake,
            speed_error=speed_error,
        )


class LatLonController(Controller):
    """组合横向+纵向控制器"""

    def __init__(self, params: VehicleParams,
                 lookahead_distance: float = 8.0,
                 kp: float = 0.8, ki: float = 0.12, kd: float = 0.15,
                 config: "ControlConfig | None" = None):
        self.lat_controller = PurePursuitController(
            params, lookahead_distance=lookahead_distance, config=config)
        self.lon_controller = PIDLongitudinalController(
            params, kp=kp, ki=ki, kd=kd, config=config)

    def update(self, state: VehicleState, traj: Trajectory, dt: float = 0.01) -> ControllerOutput:
        lat_cmd = self.lat_controller.update(state, traj, dt)
        lon_cmd = self.lon_controller.update(state, traj, dt)

        return ControllerOutput(
            steer_angle=lat_cmd.steer_angle,
            target_velocity=lon_cmd.target_velocity,
            throttle=lon_cmd.throttle,
            brake=lon_cmd.brake,
            cross_track_error=lat_cmd.cross_track_error,
            heading_error=lat_cmd.heading_error,
            speed_error=lon_cmd.speed_error,
        )

    def reset(self):
        self.lon_controller.reset()
