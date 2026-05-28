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
    LOCALIZATION,
    CHASSIS,
    CONTROL_CMD,
    CLOUD_DEVICE_MSG,
)
from ..models.sim_messages import (
    TaskToPlanning,
    MoveAuthority,
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

    def __init__(self, bus: SimMessageBus):
        self._bus = bus
        self._traj_parser = TrajParser()
        self._ref_mgr = ReferenceLineManager()

        # 当前任务信息
        self._current_task_sn: str = ""
        self._current_task_type: int = 0
        self._task_status: int = 0       # 0=idle, 1=executing, 2=complete
        self._action_seq: list[Action] = []

        # 缓存最新车辆数据（用于上行上报）
        self._latest_localization: Optional[Localization] = None
        self._latest_chassis: Optional[Chassis] = None
        self._latest_control_cmd: Optional[ControlCmd] = None

        # 上行上报节流
        self._last_position_report_time: float = 0.0
        self._last_state_report_time: float = 0.0

        # 最新一次上行报告中的停车相关字段 (供 UI 可视化)
        self._last_reason_code: int = 0
        self._last_run_state: int = 0
        self._last_stop_reason: int = 0

        # 订阅
        self._bus.subscribe(CLOUD_DISPATCH_TASK, self._on_cloud_dispatch_task)
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
                return False

            self._ref_mgr.update_from_task(task_traj)
            self._current_task_sn = task_traj.task_id or str(file_path)
            self._current_task_type = 1  # LOAD
            self._task_status = 1        # executing

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

        result = self.load_task_file(file_path)
        if result:
            self._current_task_sn = dispatch_task.task_sn
            self._current_task_type = dispatch_task.task_type
            self._action_seq = list(dispatch_task.action_seq)
        return result

    def _publish_task_and_authority(self, task_traj) -> None:
        """发布 TaskToPlanning 和 MoveAuthority 到 SimMessageBus"""
        now = time.time()

        # TaskToPlanning
        t2p = TaskToPlanning(
            task_traj=task_traj,
            action_seq=list(self._action_seq),
            task_sn=self._current_task_sn,
            task_type=self._current_task_type,
            timestamp=now,
        )
        self._bus.publish(TASK_TO_PLANNING, t2p)

        # MoveAuthority
        ma = MoveAuthority(
            right_of_way_index=self._ref_mgr.right_of_way_index,
            stop_index=self._ref_mgr.stop_index,
            timestamp=now,
        )
        self._bus.publish(MOVE_AUTHORITY, ma)

    # ========== SimMessageBus 回调 ==========

    def _on_cloud_dispatch_task(self, topic: str, msg: CloudDispatchTask) -> None:
        """收到云端下发的任务"""
        if msg.msg_type == "dispatch_task" and msg.dispatch_task is not None:
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

        # 10s 周期: TruckSateReport
        if sim_time - self._last_state_report_time >= 10.0:
            self._publish_state_report(sim_time)
            self._last_state_report_time = sim_time

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
            "battery": ch.battery_voltage if ch else 0.0,
            "batteryCapacity": 300.0,
            "materialCode": 0,
            "forwardAcceleration": 0.0,
            "lateralAcceleration": 0.0,
            "yawAngularAcceleration": math.degrees(loc.yaw_rate) if loc.yaw_rate else 0.0,
            "roadId": 0,
            "pointIndex": 0,
            "roadResidualDistance": 0.0,
            "operationType": 1,
            "reasonCode": 0,
            "runState": 1 if self._task_status == 1 else 0,
            "stopReason": 1,
            "taskSn": self._current_task_sn,
            "taskType": self._current_task_type,
            "taskStatus": self._task_status,
            "commandType": 0,
            "actionType": 0,
            "actionStatus": 0,
            "utcMilliSeconds": int(sim_time * 1000),
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
            "ts": int(sim_time * 1000),
            "stopTs": int(sim_time * 1000),
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
