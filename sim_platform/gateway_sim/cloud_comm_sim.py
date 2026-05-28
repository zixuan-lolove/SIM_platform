"""云端通信仿真模块 — 模拟 MineServer 与车端 V2X 交互 (F-13)

模拟云端职责:
1. 鉴权握手机制 (AuthenticationApply)
2. 任务派发 (DispatchTask)
3. 路权下发 (MoveAuthority)
4. 服务器参数查询 (ServerParamsQueryResponse)
5. 接收车端上行消息并记录
"""

import time
import uuid
from typing import Optional

from ..core.sim_message_bus import (
    SimMessageBus,
    CLOUD_DISPATCH_TASK,
    CLOUD_DEVICE_MSG,
)
from ..models.sim_messages import (
    CloudDispatchTask,
    CloudDeviceMsg,
    DispatchTask,
    MoveAuthority,
    AuthenticationApply,
    ServerParamsQueryResponse,
    Action,
)


class CloudCommSim:
    """云端通信仿真器 — 模拟 MineServer 与车端交互

    发布:
      - CloudDispatchTask  → GatewaySim 接收 (鉴权应答、任务派发、路权、参数查询响应)

    订阅:
      - CloudDeviceMsg      ← GatewaySim 上行上报 (位置、监控、状态报告)
    """

    def __init__(self, bus: SimMessageBus, device_name: str = "SIM_TRUCK_001"):
        self._bus = bus
        self._device_name = device_name
        self._imei: str = "SIM000000000001"
        self._project_id: str = "SIM_MINE_01"

        # 鉴权状态
        self._authenticated: bool = False
        self._auth_flow_id: str = ""

        # 上行消息日志
        self._uplink_log: list[CloudDeviceMsg] = []
        self._max_uplink_log: int = 1000

        # 订阅上行消息
        self._bus.subscribe(CLOUD_DEVICE_MSG, self._on_device_msg)

        # 当前任务/路权句柄
        self._current_task_sn: str = ""
        self._dispatch_count: int = 0

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def uplink_log(self) -> list[CloudDeviceMsg]:
        return self._uplink_log

    @property
    def uplink_count(self) -> int:
        return len(self._uplink_log)

    def clear_uplink_log(self) -> None:
        self._uplink_log.clear()

    # ========== 鉴权 ==========

    def start_auth_handshake(self) -> str:
        """发起鉴权握手 → 下发 AuthenticationApply

        Returns:
            flow_id (用于追踪此次鉴权)
        """
        flow_id = str(uuid.uuid4())[:8]
        self._auth_flow_id = flow_id

        msg = CloudDispatchTask(
            msg_type="authentication_apply",
            authentication_apply=AuthenticationApply(
                flow_id=flow_id,
                reply_id="",
                result_code=0,
                device_name=self._device_name,
                mode=1,
                project_id=self._project_id,
            ),
            timestamp=time.time(),
        )
        self._bus.publish(CLOUD_DISPATCH_TASK, msg)
        self._authenticated = True
        return flow_id

    # ========== 任务派发 ==========

    def publish_dispatch_task(
        self,
        task_file_path: str,
        task_type: int = 1,
        action_seq: Optional[list[Action]] = None,
        target_name: str = "LOAD_POINT_A",
        command_type: int = 0,
    ) -> str:
        """下发运输任务 (DispatchTask)

        Args:
            task_file_path: 任务轨迹文件路径 (本地 .traj 文件)
            task_type: 1=LOAD, 2=UNLOAD, 10=PULLOVER_PARKING
            action_seq: 动作序列
            target_name: 目标区域名称
            command_type: 指令类型

        Returns:
            task_sn (任务流水号)
        """
        self._dispatch_count += 1
        task_sn = f"TASK-{self._dispatch_count:06d}"
        self._current_task_sn = task_sn

        dispatch = DispatchTask(
            task_sn=task_sn,
            task_type=task_type,
            task_file_path=task_file_path,
            file_md5="",
            action_seq=list(action_seq) if action_seq else [],
            command_type=command_type,
            target_name=target_name,
            target_element_id="",
            target_type=0,
            dispatch_result=0,
        )

        msg = CloudDispatchTask(
            msg_type="dispatch_task",
            dispatch_task=dispatch,
            timestamp=time.time(),
        )
        self._bus.publish(CLOUD_DISPATCH_TASK, msg)
        return task_sn

    # ========== 路权下发 ==========

    def publish_move_authority(
        self,
        right_of_way_index: int = 0,
        stop_index: int = 0,
        endpoint_lat: float = 0.0,
        endpoint_lon: float = 0.0,
        endpoint_heading: float = 0.0,
    ) -> None:
        """下发路权信息 (MoveAuthority)"""
        ma = MoveAuthority(
            right_of_way_index=right_of_way_index,
            stop_index=stop_index,
            endpoint_lat=endpoint_lat,
            endpoint_lon=endpoint_lon,
            endpoint_heading=endpoint_heading,
            timestamp=time.time(),
        )
        msg = CloudDispatchTask(
            msg_type="move_authority",
            move_authority=ma,
            timestamp=time.time(),
        )
        self._bus.publish(CLOUD_DISPATCH_TASK, msg)

    # ========== 服务器参数查询 ==========

    def publish_server_params(
        self,
        map_file_name: str = "",
        map_md5: str = "",
        download_url: str = "",
    ) -> str:
        """下发服务器参数查询响应"""
        flow_id = str(uuid.uuid4())[:8]

        msg = CloudDispatchTask(
            msg_type="server_params_response",
            server_params_response=ServerParamsQueryResponse(
                flow_id=flow_id,
                map_file_name=map_file_name,
                map_md5=map_md5,
                download_url=download_url,
            ),
            timestamp=time.time(),
        )
        self._bus.publish(CLOUD_DISPATCH_TASK, msg)
        return flow_id

    # ========== 快捷组合 ==========

    def quick_dispatch(
        self,
        task_file_path: str,
        task_type: int = 1,
        action_seq: Optional[list[Action]] = None,
    ) -> str:
        """一键派发: 鉴权 + 下发任务 + 下发路权"""
        if not self._authenticated:
            self.start_auth_handshake()

        task_sn = self.publish_dispatch_task(
            task_file_path=task_file_path,
            task_type=task_type,
            action_seq=action_seq,
        )
        self.publish_move_authority()
        return task_sn

    # ========== 上行消息回调 ==========

    def _on_device_msg(self, topic: str, msg: CloudDeviceMsg) -> None:
        """接收车端上行消息并记录"""
        self._uplink_log.append(msg)
        if len(self._uplink_log) > self._max_uplink_log:
            self._uplink_log = self._uplink_log[-self._max_uplink_log:]

    # ========== 统计/诊断 ==========

    def get_stats(self) -> dict:
        """获取云通信统计"""
        msg_types = {}
        for entry in self._uplink_log:
            t = entry.msg_type
            msg_types[t] = msg_types.get(t, 0) + 1
        return {
            "authenticated": self._authenticated,
            "dispatch_count": self._dispatch_count,
            "current_task_sn": self._current_task_sn,
            "uplink_total": len(self._uplink_log),
            "uplink_by_type": msg_types,
        }

    def reset(self) -> None:
        self._authenticated = False
        self._auth_flow_id = ""
        self._uplink_log.clear()
        self._dispatch_count = 0
        self._current_task_sn = ""
