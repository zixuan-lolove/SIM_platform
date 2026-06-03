"""仿真引擎 — 定时器驱动的主循环"""

import time
import enum
import math
from collections import deque
from typing import Optional, Callable

from ..models.vehicle_params import VehicleParams
from ..models.trajectory import Trajectory
from .vehicle_state import VehicleState
from .kinematics import KinematicEngine
from .data_logger import DataLogger


class ControlMode(enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"


class SimEngine:
    """仿真引擎
    管理仿真主循环，协调运动学更新与 UI 刷新。
    支持手动模式（UI控制）和自动模式（轨迹跟踪控制器）。
    """

    def __init__(
        self,
        params: VehicleParams,
        dt: float = 0.01,
        target_fps: int = 60,
    ):
        self.params = params
        self.dt = dt
        self.target_fps = target_fps
        self.kinematics = KinematicEngine(params, dt)

        # 车辆状态
        self.state = VehicleState()
        self._prev_state: Optional[VehicleState] = None

        # 控制输入（由 UI 面板或控制器写入）
        self.target_velocity_kmh: float = 0.0     # 目标车速 (km/h)
        self.target_steer_sw_deg: float = 0.0     # 目标方向盘转角 (deg)
        self.target_gear: int = 0                  # 目标档位 (P) — 无任务时默认驻车
        self.target_brake_pressure: float = 0.0    # 目标制动压力 (MPa)

        # 轨迹记录
        self.max_trail_points: int = 60000
        self.trail_x: deque[float] = deque(maxlen=self.max_trail_points)
        self.trail_y: deque[float] = deque(maxlen=self.max_trail_points)

        # 状态回调
        self._on_state_updated: Optional[Callable[[VehicleState], None]] = None

        # 运行状态
        self._running: bool = False
        self._paused: bool = False
        self._sim_time: float = 0.0
        self._last_step_time: float = 0.0
        self._step_count: int = 0

        # 控制模式
        self.control_mode: ControlMode = ControlMode.MANUAL
        self._controller: Optional[object] = None  # Controller 实例
        self._trajectory: Optional[Trajectory] = None
        self._last_cmd: Optional[object] = None    # ControllerOutput

        # 数据记录
        self.data_logger = DataLogger(max_points=10000)

        # 统计
        self.real_time_factor: float = 1.0  # 仿真时间 / 真实时间

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def sim_time(self) -> float:
        return self._sim_time

    @property
    def controller(self):
        return self._controller

    @property
    def trajectory(self) -> Optional[Trajectory]:
        return self._trajectory

    @property
    def last_cmd(self):
        return self._last_cmd

    def set_controller(self, controller):
        """设置轨迹跟踪控制器"""
        self._controller = controller

    def set_trajectory(self, trajectory: Trajectory):
        """设置参考轨迹"""
        self._trajectory = trajectory

    def set_control_mode(self, mode: ControlMode):
        """切换控制模式"""
        self.control_mode = mode
        if self._controller:
            self._controller.reset()

    def set_state_callback(self, callback: Callable[[VehicleState], None]):
        """设置状态更新回调（供 UI 刷新）"""
        self._on_state_updated = callback

    def reset(self, initial_state: Optional[VehicleState] = None, clear_trail: bool = True):
        """重置仿真"""
        if initial_state:
            self.state = initial_state.clone()
        else:
            self.state = VehicleState()
        self._sim_time = 0.0
        self._step_count = 0
        self._last_step_time = time.perf_counter()
        if clear_trail:
            self.trail_x.clear()
            self.trail_y.clear()
            self.data_logger.clear()
        self.real_time_factor = 1.0
        self._last_cmd = None
        if self._controller:
            self._controller.reset()

    def start(self):
        """启动仿真"""
        self._running = True
        self._paused = False
        self._last_step_time = time.perf_counter()

    def stop(self):
        """停止仿真"""
        self._running = False
        self._paused = False

    def pause(self):
        """暂停"""
        self._paused = True

    def resume(self):
        """恢复"""
        self._paused = False
        self._last_step_time = time.perf_counter()

    def toggle_pause(self):
        """切换暂停/恢复"""
        if self._paused:
            self.resume()
        else:
            self.pause()

    def clear_history(self):
        """清除轨迹记录和仿真时间（保留当前状态和控制模式）"""
        self._sim_time = 0.0
        self._step_count = 0
        self.trail_x.clear()
        self.trail_y.clear()
        self.real_time_factor = 1.0
        self._last_cmd = None
        self.data_logger.clear()

    def emergency_stop(self):
        """急停：速度置零，最大制动"""
        self.target_velocity_kmh = 0.0
        self.target_brake_pressure = self.params.max_brake_pressure

    def step(self) -> VehicleState:
        """执行一个仿真步（由定时器调用）"""
        if not self._running or self._paused:
            return self.state

        now = time.perf_counter()
        elapsed = now - self._last_step_time
        self._last_step_time = now

        # 实时因子
        if elapsed > 0:
            self.real_time_factor = self.dt / elapsed if elapsed > 0 else 1.0

        # --- 控制命令生成 ---
        if self.control_mode == ControlMode.AUTO and self._controller and self._trajectory:
            # 自动模式：调用轨迹跟踪控制器
            self._last_cmd = self._controller.update(self.state, self._trajectory, self.dt)
            # 控制器输出前轮转角 (deg) → 转为方向盘转角 → 运动学引擎再转回前轮转角
            self.target_steer_sw_deg = self._last_cmd.steer_angle * self.params.steer_ratio
            self.target_velocity_kmh = self._last_cmd.target_velocity
            self.target_gear = 3  # D 档
            # 制动: 将控制器 brake% 映射为制动压力
            self.target_brake_pressure = (self._last_cmd.brake / 100.0) * self.params.max_brake_pressure

            # 终点检测：接近末端减速，到达终点停车
            if self._trajectory and len(self._trajectory) > 1:
                n = len(self._trajectory.points)
                end_pt = self._trajectory.points[-1]
                dx = self.state.x - end_pt.x
                dy = self.state.y - end_pt.y
                dist_to_end = math.sqrt(dx * dx + dy * dy)
                closest_idx = self._trajectory.find_closest_index(self.state.x, self.state.y)
                progress = closest_idx / (n - 1)
                # 到达终点（进度 > 99% 且距离终点 < 1m）：强制停车
                if progress >= 0.99 and dist_to_end < 1.0:
                    self.target_velocity_kmh = 0.0
                    self.target_brake_pressure = self.params.max_brake_pressure
                # 接近末端（最后 15%）：线性降速
                elif progress > 0.85:
                    scale = (1.0 - progress) / 0.15  # 1.0 → 0
                    self.target_velocity_kmh *= scale
        # MANUAL 模式：target 值由 main_window._sim_step 从 ControlPanel 写入，此处直接使用

        # 执行运动学更新
        self._prev_state = self.state.clone()
        self.state = self.kinematics.step(
            self._prev_state,
            self.target_velocity_kmh,
            self.target_steer_sw_deg,
            self.target_gear,
            self.target_brake_pressure,
        )
        self.state.timestamp = self._sim_time
        self._sim_time += self.dt
        self._step_count += 1

        # 记录轨迹
        self.trail_x.append(self.state.x)
        self.trail_y.append(self.state.y)

        # 记录数据日志
        self._record_data()

        # 回调通知 UI
        if self._on_state_updated:
            self._on_state_updated(self.state)

        return self.state

    def _record_data(self):
        """记录当前步骤的所有信号到 DataLogger"""
        s = self.state
        t = self._sim_time

        signals = {
            "vehicle.speed": s.v_kmh,
            "vehicle.accel": s.acceleration,
            "vehicle.yaw_rate": math.degrees(s.yaw_rate),
            "vehicle.steer": s.steer_angle_deg,
            "vehicle.brake_pressure": s.brake_pressure,
            "position.x": s.x,
            "position.y": s.y,
            "position.heading": s.theta_deg,
            "control.target_speed": self.target_velocity_kmh,
            "control.steer_sw": self.target_steer_sw_deg,
        }
        if self._last_cmd:
            signals.update({
                "control.throttle": self._last_cmd.throttle,
                "control.brake": self._last_cmd.brake,
                "error.cross_track": self._last_cmd.cross_track_error,
                "error.heading": self._last_cmd.heading_error,
                "error.speed": self._last_cmd.speed_error,
            })
        self.data_logger.record(t, **signals)

    def get_trail_points(self) -> tuple[list[float], list[float]]:
        """获取轨迹点列表"""
        return list(self.trail_x), list(self.trail_y)
