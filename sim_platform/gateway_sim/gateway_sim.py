"""Gateway 仿真模块 — 车端网关核心逻辑 (F-08)

模拟真实 Gateway 的职责:
1. 接收云端下发的 DispatchTask（通过 SimMessageBus 订阅 CloudDispatchTask）
2. 解析轨迹文件 → 构建参考线 → 发布 TaskToPlanning + MoveAuthority
3. 订阅 Localization/Chassis → 缓存 → 周期性构造上行上报消息
"""

import logging
import math
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from ..core.sim_message_bus import (
    SimMessageBus,
    CLOUD_DISPATCH_TASK,
    TASK_TO_PLANNING,
    MOVE_AUTHORITY,
    PLANNING_RESULT,
    LOCALIZATION,
    CHASSIS,
    CONTROL_CMD,
    CLOUD_DEVICE_MSG,
)
from ..models.sim_messages import (
    TaskToPlanning,
    MoveAuthority,
    PlanningResult,
    Localization,
    Chassis,
    ControlCmd,
    CloudDeviceMsg,
    CloudDispatchTask,
    DispatchTask,
    Action,
)
from .traj_parser import TrajParser
from .reference_line_mgr import ReferenceLineManager, ReferenceLine
from .hdmap_matcher import HdMapMatcher

# stopReason 20-bit 位图 (车云协议 Table[13])
# Bit N = 0: 停车原因 N 生效中, Bit N = 1: 已恢复
# 正常行驶 (无任何停车): 全部 20 bit 置 1 = 0xFFFFF
STOP_REASON_ALL_CLEAR = 0xFFFFF  # 1048575

STOP_REASON_BIT = {
    "no_task": 0,          # 无任务停车
    "fault": 1,            # 故障停车
    "obstacle": 2,         # 遇障停车
    "remote_safe": 3,      # 遥控手柄安全停车
    "remote_emergency": 4, # 遥控手柄紧急停车
    "platform_safe": 5,    # 平台安全停车
    "platform_emergency": 6,  # 平台紧急停车
    "excavator_safe": 7,   # 挖机安全停车
    "excavator_emergency": 8,  # 挖机紧急停车
    "cooling_row": 9,      # 凉车触发路权停止更新
    "aeb": 10,             # AEB停车
    "heartbeat_lost": 11,  # 故障心跳丢失停车
    "remote_drive_safe": 12,   # 遥控驾驶安全停车
    "remote_drive_emergency": 13,  # 遥控驾驶紧急停车
    "row_end": 14,         # 路权终点停车
    "hmi_safe": 15,        # HMI安全停车
    "hmi_emergency": 16,   # HMI紧急停车
    "no_row": 17,          # 无路权停车
    "past_row_end": 18,    # 超过路权终点停车
    "vcu_emergency": 19,   # VCU遥控器紧急停车
}


class GatewaySim:
    """车端 Gateway 仿真器

    订阅:
      - CloudDispatchTask  ← 接收云端派发任务
      - Localization        ← 缓存最新定位数据
      - Chassis             ← 缓存最新底盘数据

    发布:
      - TaskToPlanning      → 任务轨迹给 Planning
      - MoveAuthority        → 路权信息给 Planning
      - CloudDeviceMsg       → 上行状态报告给 CloudCommSim
    """

    def __init__(self, bus: SimMessageBus, map_folder: str = ""):
        self._bus = bus
        self._traj_parser = TrajParser()
        self._ref_mgr = ReferenceLineManager()

        # 高精地图匹配器 (用于上行报告中查找当前所在车道 ID)
        self._map_matcher = HdMapMatcher(map_folder) if map_folder else None

        # 当前任务信息
        self._current_task_sn: str = ""
        self._current_task_file: str = ""  # 当前任务的轨迹文件路径
        self._current_task_type: int = 0
        self._command_type: int = 0       # 从下发任务转发的 Command.commandType
        self._task_status: int = 0       # 0=idle, 1=executing, 2=complete
        self._action_seq: list[Action] = []

        # 缓存最新车辆数据（用于上行上报）
        self._latest_localization: Optional[Localization] = None
        self._latest_chassis: Optional[Chassis] = None
        self._latest_control_cmd: Optional[ControlCmd] = None
        self._latest_planning_result: Optional[PlanningResult] = None

        # action 完成 latch: 确保 status=2 至少被一次位置上报捕获
        self._pending_action_completed: bool = False
        self._completed_action_type: int = 0

        # 上行上报节流
        self._last_position_report_time: float = 0.0
        self._last_state_report_time: float = 0.0

        # 最新一次上行报告中的停车相关字段 (供 UI 可视化)
        self._last_reason_code: int = 0
        self._last_run_state: int = 0
        self._last_stop_reason: int = 0

        # 订阅
        self._bus.subscribe(CLOUD_DISPATCH_TASK, self._on_cloud_dispatch_task)
        self._bus.subscribe(PLANNING_RESULT, self._on_planning_result)
        self._bus.subscribe(LOCALIZATION, self._on_localization)
        self._bus.subscribe(CHASSIS, self._on_chassis)
        self._bus.subscribe(CONTROL_CMD, self._on_control_cmd)

    # ========== 属性 ==========

    @property
    def reference_line_manager(self) -> ReferenceLineManager:
        return self._ref_mgr

    @property
    def current_reference_line(self) -> ReferenceLine:
        return self._ref_mgr.current

    @property
    def task_status(self) -> int:
        return self._task_status

    @property
    def current_task_sn(self) -> str:
        return self._current_task_sn

    @property
    def current_task_type(self) -> int:
        return self._current_task_type

    # ========== 任务加载 ==========

    def load_task_file(self, file_path: str | Path) -> bool:
        """从本地文件或目录加载任务轨迹

        支持:
        - .traj 文件 → TrajParser 解析
        - .tar.gz 压缩包 → 自动解压后加载
        - 目录 (已解压的任务) → TrajParser.parse_folder

        完整流程:
        1. 解析轨迹文件
        2. 构建 ReferenceLineManager
        3. 公开发布 TaskToPlanning + MoveAuthority 到 SimMessageBus

        Returns:
            True 表示加载成功
        """
        file_path = Path(file_path)
        try:
            path_str = str(file_path)

            # .tar.gz 压缩包 → 解压
            if path_str.endswith(".tar.gz"):
                path_str = self._extract_tar_gz(path_str)
                if not path_str:
                    return False
                file_path = Path(path_str)

            if file_path.is_dir():
                task_traj = self._traj_parser.parse_folder(str(file_path))
            else:
                task_traj = self._traj_parser.parse_file(str(file_path))

            if not task_traj.points:
                logger.warning(f"[GatewaySim] Task file has no points: {file_path}")
                return False

            self._ref_mgr.update_from_task(task_traj)
            self._current_task_sn = task_traj.task_id or str(file_path)
            self._current_task_type = 1  # LOAD
            self._task_status = 1        # executing
            # 新任务开始：清除上次 action 完成 latch
            self._pending_action_completed = False
            self._completed_action_type = 0

            logger.info(f"[GatewaySim] Task loaded: {len(task_traj.points)} points, "
                        f"sn={self._current_task_sn}")
            self._publish_task_and_authority(task_traj)
            return True

        except Exception as e:
            logger.warning(f"Failed to load task file: {file_path} — {e}")
            return False

    @staticmethod
    def _extract_tar_gz(tar_path: str) -> str:
        """解压 .tar.gz 到同名目录，返回解压后的目录路径"""
        import tarfile
        extract_dir = os.path.splitext(os.path.splitext(tar_path)[0])[0]
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(extract_dir)
        return extract_dir

    def load_task_from_dispatch(self, dispatch_task: DispatchTask) -> bool:
        """从 DispatchTask 加载任务"""
        file_path = dispatch_task.task_file_path
        if not file_path:
            return False

        # 同任务号 + 同轨迹文件 → 真正的重复下发，跳过加载
        # 同任务号 + 不同文件 → 云端更新了任务，需重新加载
        same_sn = (dispatch_task.task_sn == self._current_task_sn and self._current_task_sn)
        same_file = (file_path == self._current_task_file)
        if same_sn and same_file:
            if dispatch_task.command_type != self._command_type:
                logger.info(f"[GatewaySim] Task sn={dispatch_task.task_sn} commandType "
                            f"updated: {self._command_type} → {dispatch_task.command_type}")
                self._command_type = dispatch_task.command_type
            return True

        # 必须在 load_task_file 之前设置 _action_seq，
        # 因为 load_task_file → _publish_task_and_authority 会立即发布 TaskToPlanning
        self._action_seq = list(dispatch_task.action_seq)

        result = self.load_task_file(file_path)
        if result:
            self._current_task_sn = dispatch_task.task_sn
            self._current_task_file = file_path
            self._current_task_type = dispatch_task.task_type
            # 从下发任务转发 commandType (Command.commandType)
            self._command_type = dispatch_task.command_type
            # 重置上行上报计时器，避免 sim_time 归零后计时器不触发
            self._last_position_report_time = 0.0
            self._last_state_report_time = 0.0
        return result

    def _publish_task_and_authority(self, task_traj) -> None:
        """发布 TaskToPlanning 到 SimMessageBus

        MoveAuthority 仅由云端下发 (RealCloudClient._handle_move_authority)，
        不在本地任务加载时发布，与 C++ publicTaskToPnc 行为一致。
        """
        now = time.time()

        t2p = TaskToPlanning(
            task_traj=task_traj,
            action_seq=list(self._action_seq),
            task_sn=self._current_task_sn,
            task_type=self._current_task_type,
            timestamp=now,
        )
        logger.info(f"[GatewaySim] Publishing TaskToPlanning: "
                    f"actions={len(t2p.action_seq)}, "
                    f"types={[a.action_type for a in t2p.action_seq]}")
        self._bus.publish(TASK_TO_PLANNING, t2p, publisher="GatewaySim")

    # ========== SimMessageBus 回调 ==========

    def _on_cloud_dispatch_task(self, topic: str, msg: CloudDispatchTask) -> None:
        """收到云端下发的任务"""
        if msg.msg_type == "dispatch_task" and msg.dispatch_task is not None:
            dt = msg.dispatch_task
            logger.info(f"[GatewaySim] Cloud dispatch received: sn={dt.task_sn}, "
                        f"path={dt.task_file_path}")
            self.load_task_from_dispatch(msg.dispatch_task)
        elif msg.msg_type == "move_authority" and msg.move_authority is not None:
            ma = msg.move_authority
            self._ref_mgr.right_of_way_index = ma.right_of_way_index
            self._ref_mgr.stop_index = ma.stop_index
            self._bus.publish(MOVE_AUTHORITY, ma)

    def _on_localization(self, topic: str, msg: Localization) -> None:
        self._latest_localization = msg

    def _on_chassis(self, topic: str, msg: Chassis) -> None:
        self._latest_chassis = msg

    def _on_control_cmd(self, topic: str, msg: ControlCmd) -> None:
        self._latest_control_cmd = msg

    def _on_planning_result(self, topic: str, msg: PlanningResult) -> None:
        """缓存最新规划结果，latch action_status=2 确保被位置上报捕获

        C++ 等价行为: BussinessDecision 检测到 action 完成时设置 status=2，
        GateWay::sendVehiclePositionToCloud 在下次上报中读取并发送。
        由于规划 (10Hz) 快于位置上报 (1Hz)，需要 latch 机制避免完成信号被覆盖。
        """
        self._latest_planning_result = msg
        # 诊断: 首次收到规划结果时输出 action 状态
        if not hasattr(self, '_pr_logged'):
            self._pr_logged = True
            logger.info(f"[GatewaySim] First PlanningResult received: "
                        f"action_type={msg.action_type}, action_status={msg.action_status}")
        # latch: action 完成时缓存 status=2，确保被下一次位置上报捕获
        if msg.action_status == 2:
            self._pending_action_completed = True
            self._completed_action_type = msg.action_type
            logger.info(f"[GatewaySim] Action completed: type={msg.action_type}, "
                        f"task_finish={msg.task_finish}")
        # 任务完成: 所有 action 执行完毕，更新 _task_status → runState 跳变
        if msg.task_finish and self._task_status == 1:
            self._task_status = 2
            logger.info(f"[GatewaySim] Task finished: _task_status 1 → 2, "
                        f"runState will report 1 (complete)")

    @staticmethod
    def _theta_to_geo_heading(theta_rad: float) -> float:
        """数学角度 (0=东, CCW) → 地理航向 (0=北, CW, deg)"""
        return (90.0 - math.degrees(theta_rad)) % 360.0

    # ========== 周期性上行上报 (由 FullStackEngine 驱动) ==========

    def update_uplink_reports(self, sim_time: float) -> None:
        """检查并执行周期性上行上报"""
        # 1s 周期: TruckPositionReport + TruckMonitorReport
        if sim_time - self._last_position_report_time >= 1.0:
            self._publish_position_report(sim_time)
            self._publish_monitor_report(sim_time)
            self._last_position_report_time = sim_time
            logger.debug(f"[GatewaySim] 1s uplink: position + monitor (t={sim_time:.1f})")

        # 10s 周期: TruckSateReport
        if sim_time - self._last_state_report_time >= 10.0:
            self._publish_state_report(sim_time)
            self._last_state_report_time = sim_time

    def _compute_stop_reason(self) -> int:
        """根据当前状态计算 stopReason 20-bit 位图

        车云协议 Table[13]: 每 bit 对应一种停车原因
          Bit = 0: 该停车原因生效中
          Bit = 1: 已恢复 (正常行驶)

        Returns:
            20-bit 位图 (0x00000 ~ 0xFFFFF)
        """
        # 从全恢复开始 (正常行驶，无任何停车)
        mask = STOP_REASON_ALL_CLEAR

        # 无任务时: bit 0 置 0 (无任务停车生效)
        if self._task_status != 1:
            mask &= ~(1 << STOP_REASON_BIT["no_task"])

        return mask

    def _get_action_type(self) -> int:
        """当前 action 类型 (从云端下发任务实时转发)

        执行中转发当前 action 的 actionType，完成后持续转发已完成 action 的类型。
        值直接来自云端 DispatchTask.command.actionSeq[i].actionType。
        """
        if self._pending_action_completed:
            return self._completed_action_type  # 转发云端下发的原始值
        pr = self._latest_planning_result
        return pr.action_type if pr else 0

    def _get_action_status(self) -> int:
        """当前 action 状态 (0=idle, 1=executing, 2=complete)

        latch 机制: action_status=2 后持久保持，直到新任务下发时清除。
        这确保完成信号持续上报，不会因单次消费而丢失。
        """
        if self._pending_action_completed:
            return 2
        pr = self._latest_planning_result
        return pr.action_status if pr else 0

    def _get_road_id(self, lat: float, lon: float) -> int:
        """根据 GPS 坐标从高精地图匹配当前所在车道 ID

        Args:
            lat: 纬度
            lon: 经度

        Returns:
            laneid (int), 地图未加载或无匹配时返回 0
        """
        if self._map_matcher is None:
            return 0
        return self._map_matcher.find_lane_id(lat, lon)

    def _publish_position_report(self, sim_time: float) -> None:
        """构造并发布 TruckPositionReport (34 字段，对应 C++ sendVehiclePositionToCloud)"""
        if self._latest_localization is None:
            return
        loc = self._latest_localization
        ch = self._latest_chassis
        cmd = self._latest_control_cmd

        payload = {
            "longitude": loc.lon,
            "latitude": loc.lat,
            "altitude": loc.z,
            "direction": self._theta_to_geo_heading(loc.theta),
            "speed": abs(loc.v) * 3.6,
            "battery": 100.0,
            "batteryCapacity": 100.0,
            "materialCode": 0,
            "forwardAcceleration": 0.0,
            "lateralAcceleration": 0.0,
            "yawAngularAcceleration": math.degrees(loc.yaw_rate) if loc.yaw_rate else 0.0,
            "roadId": self._get_road_id(loc.lat, loc.lon),
            "pointIndex": self._ref_mgr.find_closest_by_latlon(loc.lat, loc.lon),
            "roadResidualDistance": 0.0,
            "operationType": 1,
            "reasonCode": 0,
            # runState: 0=idle, 1=complete, 2=running
            "runState": 2 if self._task_status == 1 else (1 if self._task_status == 2 else 0),
            "stopReason": self._compute_stop_reason(),
            "taskSn": self._current_task_sn,
            "taskType": self._current_task_type,
            "taskStatus": self._task_status,
            # 从下发任务实时转发 (Command.commandType)
            "commandType": self._command_type,
            "actionType": self._get_action_type(),
            "actionStatus": self._get_action_status(),
            "utcMilliSeconds": int(time.time() * 1000),
            "currentPathName": "",
            "curAreaBoundaryName": "",
            "status": 0,
            "speedDeviation": cmd.speed_error if cmd else 0.0,
            "subMachineState": "0",
            "detourStatus": 0,
            "isAgileObstacle": False,
            "autoExitReasons": 0,
            "wirelessSignal": 80 if ch else 50,
        }
        self._last_reason_code = payload["reasonCode"]
        self._last_run_state = payload["runState"]
        self._last_stop_reason = payload["stopReason"]

        logger.debug(f"[GatewaySim] Position report: stopReason=0x{payload['stopReason']:05X} "
                     f"({payload['stopReason']}), runState={payload['runState']}, "
                     f"taskStatus={self._task_status}, "
                     f"actionType={payload['actionType']}, actionStatus={payload['actionStatus']}, "
                     f"pos=({payload['longitude']:.6f},{payload['latitude']:.6f}) "
                     f"dir={payload['direction']:.1f}° theta={loc.theta:.3f}rad")

        msg = CloudDeviceMsg(
            msg_type="position_report",
            imei="SIM000000000001",
            payload=payload,
            timestamp=sim_time,
        )
        self._bus.publish(CLOUD_DEVICE_MSG, msg)

    def get_uplink_stats(self) -> dict:
        """返回最新一次上行报告中的停车相关字段"""
        return {
            "reason_code": self._last_reason_code,
            "run_state": self._last_run_state,
            "stop_reason": self._last_stop_reason,
        }

    def _publish_monitor_report(self, sim_time: float) -> None:
        """构造并发布 TruckMonitorReport (对应 C++ sendVehicleMonitorToCloud)"""
        if self._latest_localization is None:
            return
        loc = self._latest_localization
        ch = self._latest_chassis
        cmd = self._latest_control_cmd

        payload = {
            "longitude": loc.lon,
            "latitude": loc.lat,
            "altitude": loc.z,
            "direction": self._theta_to_geo_heading(loc.theta),
            "speed": abs(loc.v) * 3.6,
            "lateralError": cmd.cross_track_error if cmd else 0.0,
            "spin": ch.engine_rpm if ch else 0.0,
            "throttleOpenAuto": cmd.throttle if cmd else 0.0,
            "throttleOpenManual": 0.0,
            "brakeOpenAuto": cmd.brake if cmd else 0.0,
            "brakeOpenManual": 0.0,
            "limitSpeed": 30.0,
        }
        msg = CloudDeviceMsg(
            msg_type="monitor_report",
            imei="SIM000000000001",
            payload=payload,
            timestamp=sim_time,
        )
        self._bus.publish(CLOUD_DEVICE_MSG, msg)

    def _publish_state_report(self, sim_time: float) -> None:
        """构造并发布 TruckSateReport (10s 周期, 对应 C++ sendVehicleStatusToCloud)"""
        if self._latest_localization is None:
            return
        loc = self._latest_localization
        ch = self._latest_chassis

        payload = {
            "longitude": loc.lon,
            "latitude": loc.lat,
            "altitude": loc.z,
            "direction": self._theta_to_geo_heading(loc.theta),
            "frontWheelDirection": math.degrees(abs(ch.steer_angle)) if ch else 0.0,
            "frontWheelAngularError": 0.0,
            "oilPressure": ch.oil_pressure if ch else 350.0,
            "coolantTemperature": ch.coolant_temp if ch else 85.0,
            "batteryVoltage": ch.battery_voltage if ch else 600.0,
            "fuelLevel": 85.0,
            "mileage": ch.mileage if ch else 0.0,
            "liftAngle": 0.0,
        }
        msg = CloudDeviceMsg(
            msg_type="state_report",
            imei="SIM000000000001",
            payload=payload,
            timestamp=sim_time,
        )
        self._bus.publish(CLOUD_DEVICE_MSG, msg)

    # ========== StopObstacleInfo 上行 (事件驱动) ==========

    def publish_stop_obstacle_info(
        self,
        sim_time: float,
        obstacles: list[dict],
        impact_type: int = 0,
    ) -> None:
        """发布 StopObstacleInfo 上行消息 (对应 C++ recvPerceptionFrontMsg)

        将障碍物角点从 ENU 局部坐标转为 WGS84 经纬度后上报云端。

        Args:
            sim_time: 仿真时间
            obstacles: 障碍物列表，每个 dict 包含 corners (list of (x,y)) 和 type
            impact_type: 碰撞类型 0=无效 1=障碍物碰撞 2=挡墙碰撞
        """
        if self._latest_localization is None:
            return
        loc = self._latest_localization
        cos_lat = math.cos(math.radians(loc.lat))
        lat2m = 111319.0
        lon2m = 111319.0 * cos_lat if cos_lat > 0 else 111319.0

        payload = {
            "ts": int(time.time() * 1000),
            "stopTs": int(time.time() * 1000),
            "impactType": impact_type,
            "currentPose": {
                "lon": loc.lon,
                "lat": loc.lat,
                "heading": self._theta_to_geo_heading(loc.theta),
            },
            "impactPose": {
                "lon": loc.lon,
                "lat": loc.lat,
                "heading": self._theta_to_geo_heading(loc.theta),
            },
            "impactObstacle": [],
            "otherObstacle": [],
        }

        for obs in obstacles:
            polygon = {"pointList": []}
            for cx, cy in obs.get("corners", []):
                polygon["pointList"].append({
                    "lat": loc.lat + cy / lat2m,
                    "lon": loc.lon + cx / lon2m,
                })
            if impact_type > 0:
                payload["impactObstacle"].append(polygon)
            else:
                payload["otherObstacle"].append(polygon)

        msg = CloudDeviceMsg(
            msg_type="stop_obstacle_info",
            imei="SIM000000000001",
            payload=payload,
            timestamp=sim_time,
        )
        self._bus.publish(CLOUD_DEVICE_MSG, msg)
