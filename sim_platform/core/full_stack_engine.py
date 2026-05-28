"""全栈仿真引擎 — 编排 Gateway → Planning → Control → Kinematics 完整链路 (F-14)

FullStackEngine 继承 SimEngine，在保留现有运动学/控制能力的基础上，
通过 SimMessageBus 串联所有仿真模块：
  RealCloudClient(MQTT) → GatewaySim → PlanningSim → Controller → Kinematics
                                          ↓
                                    PerceptionSim
"""

import logging
import math
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

from .sim_engine import SimEngine, ControlMode
from .vehicle_state import VehicleState
from .controller import Controller, LatLonController
from .sim_message_bus import (
    SimMessageBus,
    LOCALIZATION,
    CHASSIS,
    CONTROL_CMD,
    CLOUD_DISPATCH_TASK,
)
from ..models.vehicle_params import VehicleParams
from ..models.trajectory import Trajectory, TrajectoryPoint
from ..models.sim_messages import (
    Localization,
    Chassis,
    PlanningResult,
    ControlCmd,
    CloudDispatchTask,
    MoveAuthority,
)
from ..gateway_sim.gateway_sim import GatewaySim
from ..gateway_sim.real_cloud_client import RealCloudClient
from ..gateway_sim.reference_line_mgr import ReferenceLineManager
from ..perception_sim.perception_sim import PerceptionSim
from ..planning_sim.planning_sim import PlanningSim
from ..planning_sim.coordinate_converter import LocalCoordinateConverter


class FullStackEngine(SimEngine):
    """全栈仿真引擎 — 完整车端软件栈

    模块:
      - SimMessageBus      进程内消息总线
      - RealCloudClient    真实 MQTT + Protobuf 云通信
      - GatewaySim         车端网关仿真
      - PerceptionSim      感知仿真
      - PlanningSim        规划仿真 (BSpline + RTK + Velocity + Decision)
      - Controller         轨迹跟踪控制 (PurePursuit + PID)
      - KinematicEngine    车辆运动学 (继承自 SimEngine)

    周期:
      - 100Hz  运动学更新 + 控制指令
      - 20Hz   感知发布
      - 10Hz   规划周期
      - 1Hz    上行位置/监控报告
      - 0.1Hz  上行状态报告
    """

    def __init__(
        self,
        params: VehicleParams,
        dt: float = 0.01,
        target_fps: int = 60,
        controller: Optional[Controller] = None,
    ):
        super().__init__(params, dt, target_fps)

        # 消息总线
        self.bus = SimMessageBus()

        # 参考线管理器 (Gateway 和 Planning 共享)
        self.ref_mgr = ReferenceLineManager()

        # 各仿真模块
        self.gateway = GatewaySim(self.bus)

        # 云端配置: 环境变量 SIM_CLOUD_CONFIG 优先; SIM_USE_LOCAL_CLOUD=1 切换本地
        _cloud_config_path = os.environ.get("SIM_CLOUD_CONFIG", "")
        if not _cloud_config_path:
            _local_cfg = os.path.join(os.path.dirname(__file__), "..", "config", "cloud_config_local.ini")
            if os.environ.get("SIM_USE_LOCAL_CLOUD") == "1" and os.path.exists(_local_cfg):
                _cloud_config_path = _local_cfg
            else:
                _cloud_config_path = os.path.join(os.path.dirname(__file__), "..", "config", "cloud_config.ini")

        self.cloud = RealCloudClient(self.bus, config_path=_cloud_config_path)
        self.perception = PerceptionSim(self.bus)
        self.planning = PlanningSim(self.bus, self.ref_mgr)

        # 订阅云端任务下发 (在 GatewaySim 之后订阅，确保回调在 Gateway 加载完成后执行)
        self.bus.subscribe(CLOUD_DISPATCH_TASK, self._on_cloud_task_dispatched)

        # 控制器
        self._full_stack_controller: Controller = controller or LatLonController(params)

        # 当前规划结果转换的轨迹
        self._planning_traj: Optional[Trajectory] = None

        # 最新的 PlanningResult (用于 UI 显示)
        self._latest_planning_result: Optional[PlanningResult] = None

        # 最新的 ControlCmd (用于发布到总线)
        self._latest_control_cmd: Optional[ControlCmd] = None

        # WGS84 参考原点 (从轨迹第一个点获取，用于 ENU → 经纬度转换)
        self._ref_lat: float = 0.0
        self._ref_lon: float = 0.0
        self._converter = LocalCoordinateConverter()

        # 节流时间戳
        self._last_planning_time: float = -1.0
        self._last_perception_time: float = -1.0
        self._last_gateway_time: float = -1.0

        # 当前任务 SN (用于判断 retained 消息是否重复)
        self._last_task_sn: str = ""

        # 默认 AUTO 模式
        self.control_mode = ControlMode.AUTO
        self._full_stack_controller.reset()

    # ========== 属性 ==========

    @property
    def planning_traj(self) -> Optional[Trajectory]:
        return self._planning_traj

    @property
    def latest_planning_result(self) -> Optional[PlanningResult]:
        return self._latest_planning_result

    @property
    def latest_control_cmd(self) -> Optional[ControlCmd]:
        return self._latest_control_cmd

    @property
    def latest_move_authority(self) -> Optional[MoveAuthority]:
        return self.planning._latest_move_authority

    @property
    def bus_stats(self) -> dict:
        return self.bus.get_stats()

    # ========== 任务加载 ==========

    def _on_cloud_task_dispatched(self, topic: str, msg: CloudDispatchTask) -> None:
        """云端任务下发后的初始化 — 在 GatewaySim 加载完成后执行

        bus 回调顺序保证: GatewaySim 先订阅 → PlanningSim → FullStackEngine
        因此此回调执行时 ref_mgr 已包含最新任务轨迹点。
        """
        if msg.msg_type != "dispatch_task" or msg.dispatch_task is None:
            return

        dt = msg.dispatch_task
        if not dt.task_file_path:
            return

        # 同一任务号不重复初始化 (MQTT 重连时 retained 消息重复下发)
        if dt.task_sn == self._last_task_sn and self._last_task_sn:
            logger.debug(f"[FullStack] Task sn={dt.task_sn} already initialized, skipping")
            return

        ref = self.gateway.reference_line_manager.current
        if not ref.points:
            return

        logger.info(f"[FullStack] Cloud task initializing: sn={dt.task_sn}, "
                    f"points={len(ref.points)}")
        self._last_task_sn = dt.task_sn

        # 若 INS 未设定参考原点，回退用轨迹第一个点
        if self._ref_lat == 0.0 and self._ref_lon == 0.0:
            self._ref_lat = ref.points[0].lat
            self._ref_lon = ref.points[0].lon
            self._converter.set_reference(self._ref_lat, self._ref_lon)

        # 用 converter 从 lat/lon 重新计算所有轨迹点的 ENU 坐标
        self._recompute_traj_enu()

        self._full_stack_controller.reset()

        # 车辆初始位置设为轨迹起点，航向取轨迹第一个点
        init_theta = ref.points[0].theta if ref.points else 0.0
        self.reset(VehicleState(x=0.0, y=0.0, theta=init_theta), clear_trail=False)

    def _recompute_traj_enu(self) -> None:
        """用 converter 从 WGS84 lat/lon 重新计算所有参考线点的 ENU (x,y,theta,s)

        在 INS 设定参考原点之后调用。替换 .traj 文件中采图时的原始 ENU 坐标。

        若 self.ref_mgr 为空（PlanningSim 2m 检查拒绝了任务），
        则先从 GatewaySim 的 ref_mgr 同步参考线数据。
        """
        import math

        all_pts = self.ref_mgr.get_all_points()
        if not all_pts:
            # PlanningSim 的 2m 邻近检查可能因坐标框架不一致而拒绝任务，
            # 此时 self.ref_mgr 为空。从 GatewaySim 的 ref_mgr 同步数据，
            # 确保 UI 能绘制参考线。
            gw_ref = self.gateway.reference_line_manager.current
            if not gw_ref.points:
                return
            self.ref_mgr.update_current(gw_ref)
            all_pts = self.ref_mgr.get_all_points()
            if not all_pts:
                return

        for pt in all_pts:
            pt.x, pt.y = self._converter.latlon_to_xy(pt.lat, pt.lon)
            pt.theta = math.pi / 2 - math.radians(pt.heading)

        # 重新计算累计里程
        s = 0.0
        for i, pt in enumerate(all_pts):
            if i > 0:
                prev = all_pts[i - 1]
                s += math.hypot(pt.x - prev.x, pt.y - prev.y)
            pt.s = s

    def connect_cloud(self) -> None:
        """连接真实云端 MQTT Broker (非阻塞)"""
        logger.info(f"[FullStack] Cloud connecting to {self.cloud._broker}")
        logger.info(f"[FullStack] Cloud broker: {self.cloud._broker} (IMEI={self.cloud._imei})")
        self.cloud.connect()

    def disconnect_cloud(self) -> None:
        self.cloud.disconnect()

    # ========== 主循环 (100Hz) ==========

    def step(self) -> VehicleState:
        """执行一个全栈仿真步"""
        if not self._running or self._paused:
            return self.state

        now = time.perf_counter()
        elapsed = now - self._last_step_time
        self._last_step_time = now
        if elapsed > 0:
            self.real_time_factor = self.dt / elapsed

        # ── 阶段 1: 发布里程计 (Localization + Chassis) ──
        self._publish_odometry()

        # ── 阶段 2: 感知更新 (20Hz) ──
        if self._sim_time - self._last_perception_time >= 0.05:
            self.perception.update(self._sim_time, self._sim_time - self._last_perception_time)
            self._last_perception_time = self._sim_time

        # ── 阶段 3: 规划更新 (10Hz) ──
        if self._sim_time - self._last_planning_time >= 0.10:
            self._latest_planning_result = self.planning.plan(self._sim_time)
            if self._latest_planning_result and self._latest_planning_result.points:
                self._planning_traj = self._planning_result_to_traj(self._latest_planning_result)
            self._last_planning_time = self._sim_time

        # ── 阶段 4: 控制指令生成 ──
        if (
            self.control_mode == ControlMode.AUTO
            and self._full_stack_controller
            and self._planning_traj
        ):
            cmd = self._full_stack_controller.update(self.state, self._planning_traj, self.dt)
            self.target_steer_sw_deg = cmd.steer_angle * self.params.steer_ratio
            self.target_velocity_kmh = cmd.target_velocity
            self.target_brake_pressure = (cmd.brake / 100.0) * self.params.max_brake_pressure
            self._latest_control_cmd = ControlCmd(
                steer_angle=cmd.steer_angle,
                target_velocity=cmd.target_velocity,
                throttle=cmd.throttle,
                brake=cmd.brake,
                cross_track_error=cmd.cross_track_error,
                heading_error=cmd.heading_error,
                speed_error=cmd.speed_error,
                timestamp=self._sim_time,
            )
            self.bus.publish(CONTROL_CMD, self._latest_control_cmd)

            # 终点检测 (进度 > 99% → 停车)
            if self._planning_traj and len(self._planning_traj) > 1:
                n = len(self._planning_traj.points)
                end_pt = self._planning_traj.points[-1]
                dx = self.state.x - end_pt.x
                dy = self.state.y - end_pt.y
                dist_to_end = math.sqrt(dx * dx + dy * dy)
                closest_idx = self._planning_traj.find_closest_index(self.state.x, self.state.y)
                progress = closest_idx / (n - 1) if n > 1 else 0.0
                if progress >= 0.99 and dist_to_end < 1.0:
                    self.target_velocity_kmh = 0.0
                    self.target_brake_pressure = self.params.max_brake_pressure
                elif progress > 0.85:
                    scale = (1.0 - progress) / 0.15
                    self.target_velocity_kmh *= scale

        # ── 阶段 5: 运动学更新 ──
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

        # 数据记录
        self._record_full_stack_data()

        # 通知 UI
        if self._on_state_updated:
            self._on_state_updated(self.state)

        # ── 阶段 6: Gateway 上行上报 ──
        self.gateway.update_uplink_reports(self._sim_time)

        return self.state

    # ========== 里程计发布 ==========

    def _publish_odometry(self) -> None:
        """从 VehicleState 构建 Localization + Chassis 并发布到总线"""
        s = self.state

        # ENU 局部坐标 → WGS84 经纬度 (供 Gateway 上行报告使用)
        lat, lon = self._converter.xy_to_latlon(s.x, s.y)

        loc = Localization(
            x=s.x,
            y=s.y,
            z=0.0,
            theta=s.theta,
            v=s.v,
            yaw_rate=s.yaw_rate,
            gear=s.gear,
            timestamp=self._sim_time,
            lat=lat,
            lon=lon,
            gnss_status=3,  # RTK
            satellite_count=20,
            hdop=0.8,
        )
        self.bus.publish(LOCALIZATION, loc)

        ch = Chassis(
            gear=s.gear,
            brake_pressure=s.brake_pressure,
            steer_angle=math.radians(s.steer_angle_deg),
            speed_kmh=s.v_kmh,
            timestamp=self._sim_time,
        )
        self.bus.publish(CHASSIS, ch)

    # ========== 数据记录 ==========

    def _record_full_stack_data(self) -> None:
        """记录全栈信号"""
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

        cmd = self._latest_control_cmd
        if cmd:
            signals.update({
                "control.throttle": cmd.throttle,
                "control.brake": cmd.brake,
                "error.cross_track": cmd.cross_track_error,
                "error.heading": cmd.heading_error,
                "error.speed": cmd.speed_error,
            })

        pr = self._latest_planning_result
        if pr:
            signals.update({
                "planning.point_count": len(pr.points),
                "planning.lift_cmd": pr.lift_cmd,
                "planning.stop": 1.0 if pr.stop else 0.0,
                "planning.task_finish": 1.0 if pr.task_finish else 0.0,
                "planning.time_ms": pr.planning_time_ms,
            })

        self.data_logger.record(t, **signals)

    # ========== 轨迹转换 ==========

    @staticmethod
    def _planning_result_to_traj(result: PlanningResult) -> Trajectory:
        """将 PlanningResult 转为 Controller 可用的 Trajectory"""
        pts = []
        for pp in result.points:
            pts.append(TrajectoryPoint(
                x=pp.x,
                y=pp.y,
                heading=pp.heading,
                velocity=pp.velocity,
                curvature=pp.curvature,
                s=pp.s,
            ))
        return Trajectory(pts)

    # ========== 重置/清理 ==========

    def reset(self, initial_state: Optional[VehicleState] = None, clear_trail: bool = True) -> None:
        super().reset(initial_state, clear_trail=clear_trail)
        self._planning_traj = None
        self._latest_planning_result = None
        self._latest_control_cmd = None
        self._last_planning_time = -1.0
        self._last_perception_time = -1.0
        self._last_gateway_time = -1.0
        if clear_trail:
            self._ref_lat = 0.0
            self._ref_lon = 0.0
            self._last_task_sn = ""
        self._full_stack_controller.reset()

    def emergency_stop(self) -> None:
        super().emergency_stop()
        self.perception.clear_all()
