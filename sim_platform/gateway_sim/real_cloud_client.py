"""真实云端通信客户端 — MQTT + Protobuf (替换 CloudCommSim)

对应 C++ gateway 中的 MqttProtobufClient + GateWay 云通信逻辑。

实现:
- paho-mqtt 连接/重连
- 鉴权: DeviceMsg{authentication} → CloudMsg{authenticationApply}
- 服务器参数查询: DeviceMsg{serverParamsQuery} → CloudMsg{serverParamsQueryResponse}
- 下行: CloudMsg{DispatchTask, MovemntAuthoritySend} → SimMessageBus
- 上行: SimMessageBus CLOUD_DEVICE_MSG → DeviceMsg 序列化 → MQTT publish
- HTTP tar.gz 下载 (收到 DispatchTask 后)
"""

import configparser
import logging
import os
import tarfile
import threading
import time
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

from ..core.sim_message_bus import (
    SimMessageBus,
    CLOUD_DISPATCH_TASK,
    MOVE_AUTHORITY,
    CLOUD_DEVICE_MSG,
)
from ..models.sim_messages import (
    CloudDispatchTask,
    CloudDeviceMsg,
    DispatchTask as SimDispatchTask,
    MoveAuthority as SimMoveAuthority,
    Action,
)
from .http_downloader import HttpDownloader

logger = logging.getLogger(__name__)


class RealCloudClient:
    """真实云端通信客户端

    通过 MQTT + Protobuf 连接 MineServer，实现完整的车云交互协议。

    状态:
      DISCONNECTED → CONNECTING → CONNECTED → AUTHENTICATING → AUTHENTICATED → RUNNING
    """

    STATE_DISCONNECTED = "disconnected"
    STATE_CONNECTING = "connecting"
    STATE_CONNECTED = "connected"
    STATE_AUTHENTICATING = "authenticating"
    STATE_AUTHENTICATED = "authenticated"
    STATE_RUNNING = "running"

    def __init__(
        self,
        bus: SimMessageBus,
        config_path: str = "",
    ):
        self._bus = bus
        self._state: str = self.STATE_DISCONNECTED
        self._config = configparser.ConfigParser()

        if config_path and Path(config_path).exists():
            self._config.read(config_path)
        else:
            self._load_default_config()

        self._broker: str = os.environ.get("SIM_MQTT_BROKER") or self._config.get("mqtt", "broker", fallback="tcp://127.0.0.1:11883")
        self._username: str = os.environ.get("SIM_MQTT_USERNAME") or self._config.get("mqtt", "username", fallback="")
        self._password: str = os.environ.get("SIM_MQTT_PASSWORD") or self._config.get("mqtt", "password", fallback="")
        self._keepalive: int = int(os.environ.get("SIM_MQTT_KEEPALIVE", "0")) or self._config.getint("mqtt", "keepalive", fallback=60)
        self._imei: str = os.environ.get("SIM_DEVICE_IMEI") or self._config.get("device", "imei", fallback="200000000000001")
        self._client_id: str = self._config.get("mqtt", "client_id_prefix", fallback="device_") + self._imei
        self._task_file_folder: str = os.environ.get("SIM_TASK_DIR") or self._config.get("download", "task_file_folder", fallback="/tmp/sim_tasks/")
        self._map_file_folder: str = os.environ.get("SIM_MAP_DIR") or self._config.get("download", "map_file_folder", fallback=self._task_file_folder)

        # 解析 broker URI → host + port (paho-mqtt 2.x connect_async 不解析 URI 端口)
        self._broker_host, self._broker_port = self._parse_broker_uri(self._broker)

        # 鉴权后获取的参数
        self._project_id: str = ""
        self._auth_flow_id: int = 0
        self._download_base_url: str = ""
        self._map_file_name: str = ""
        self._map_md5: str = ""

        # 云端下发的车辆状态
        self._task_status: int = 0
        self._load_state: int = 0

        # MQTT 客户端
        self._mqtt: mqtt.Client = mqtt.Client(
            client_id=self._client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        self._mqtt.username_pw_set(self._username, self._password)
        self._mqtt.on_connect = self._on_mqtt_connect
        self._mqtt.on_disconnect = self._on_mqtt_disconnect
        self._mqtt.on_message = self._on_mqtt_message
        self._mqtt.reconnect_delay_set(min_delay=1, max_delay=60)

        # 鉴权线程
        self._auth_thread: Optional[threading.Thread] = None
        self._auth_running: bool = False
        self._auth_success: bool = False
        self._params_queried: bool = False
        self._params_query_sent: bool = False
        self._map_download_status: str = ""  # ""=未开始, "downloading"=下载中, "success"=已下载, "failed"=下载失败
        self._map_download_path: str = ""    # 下载成功后的本地文件路径

        # 任务下载状态
        self._task_download_status: str = ""   # ""=未开始, "downloading"=下载中, "success"=已下载, "failed"=下载失败
        self._task_download_url: str = ""      # 任务下载使用的完整 URL (含参数)
        self._task_download_path: str = ""     # 下载成功后的本地文件路径
        self._task_download_name: str = ""     # 任务文件名
        self._task_md5: str = ""               # 任务文件 MD5

        # 缓存: 服务器参数未就绪时收到的 DispatchTask (等 URL 就绪后重放)
        self._pending_dispatch_proto = None

        # 消息统计
        self._stats_lock = threading.Lock()
        self._uplink_count: int = 0
        self._downlink_count: int = 0
        self._last_error: str = ""

        # 订阅 SimMessageBus 上行消息
        self._bus.subscribe(CLOUD_DEVICE_MSG, self._on_uplink_device_msg)

        # MQTT Topics
        self._topic_uplink = f"up/truck/{self._imei}"
        self._downlink_topics = [
            (f"down/truck/{self._imei}", 1),
            (f"/retain/down/status/truck/{self._imei}", 1),
            (f"/retain/down/dispatch/task/truck/{self._imei}", 1),
        ]

    # ========== 属性 ==========

    @property
    def state(self) -> str:
        return self._state

    @property
    def authenticated(self) -> bool:
        return self._auth_success

    @property
    def uplink_count(self) -> int:
        return self._uplink_count

    @property
    def downlink_count(self) -> int:
        return self._downlink_count

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def task_status(self) -> int:
        return self._task_status

    @property
    def load_state(self) -> int:
        return self._load_state

    # ========== 连接管理 ==========

    @staticmethod
    def _parse_broker_uri(uri: str) -> tuple[str, int]:
        """解析 broker URI → (host, port)

        paho-mqtt 2.x 的 connect_async 不会从 URI 解析端口，
        始终使用默认 1883，因此需要手动解析。
        """
        host = uri
        port = 1883
        if "://" in host:
            _, host = host.split("://", 1)
        if ":" in host:
            host, port_str = host.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 1883
        return host, port

    def connect(self) -> None:
        """连接到 MQTT Broker (非阻塞，后台自动重连)"""
        if self._state != self.STATE_DISCONNECTED:
            return
        self._state = self.STATE_CONNECTING
        try:
            self._mqtt.connect_async(self._broker_host, self._broker_port, keepalive=self._keepalive)
            self._mqtt.loop_start()
        except Exception as e:
            self._state = self.STATE_DISCONNECTED
            self._last_error = str(e)
            logger.error(f"[RealCloud] MQTT connect failed: {e}")

    def disconnect(self) -> None:
        """断开连接"""
        self._stop_auth()
        try:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
        except Exception:
            pass
        self._state = self.STATE_DISCONNECTED

    # ========== MQTT 回调 ==========

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._state = self.STATE_CONNECTED
            logger.info(f"[RealCloud] MQTT connected to {self._broker}")
            # 订阅下行 topics
            for topic, qos in self._downlink_topics:
                client.subscribe(topic, qos)
                logger.info(f"[RealCloud] Subscribed: {topic}")
            # 启动鉴权
            self._start_auth()
        else:
            self._state = self.STATE_DISCONNECTED
            self._last_error = f"MQTT connect rc={rc}"
            logger.error(f"[RealCloud] MQTT connect failed: rc={rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        self._state = self.STATE_DISCONNECTED
        self._auth_success = False
        self._params_query_sent = False
        self._params_queried = False
        self._download_base_url = ""
        self._map_download_status = ""
        self._map_download_path = ""
        self._task_download_status = ""
        self._task_download_url = ""
        self._task_download_path = ""
        self._task_download_name = ""
        self._task_md5 = ""
        self._pending_dispatch_proto = None
        self._stop_auth()
        logger.warning(f"[RealCloud] MQTT disconnected (rc={rc}), auto-reconnecting...")

    def _on_mqtt_message(self, client, userdata, msg):
        """收到云端下行消息 → 反序列化 Protobuf → 分发到 SimMessageBus"""
        with self._stats_lock:
            self._downlink_count += 1
        try:
            from ..proto import ifmsg_pb2
            cloud_msg = ifmsg_pb2.CloudMsg()
            cloud_msg.ParseFromString(msg.payload)
            logger.info(f"[RealCloud] ↓ CloudMsg:\n{cloud_msg}")
            self._dispatch_cloud_msg(cloud_msg, msg.topic)
        except Exception as e:
            logger.error(f"[RealCloud] Failed to parse CloudMsg: {e}")

    # ========== 鉴权 ==========

    def _start_auth(self):
        if self._auth_running:
            return
        self._auth_running = True
        self._auth_success = False
        self._state = self.STATE_AUTHENTICATING
        self._auth_thread = threading.Thread(target=self._auth_loop, daemon=True)
        self._auth_thread.start()

    def _stop_auth(self):
        self._auth_running = False
        if self._auth_thread and self._auth_thread.is_alive():
            self._auth_thread.join(timeout=2)
        self._auth_thread = None

    def _auth_loop(self):
        """鉴权循环: 每 5s 发送 Authentication 消息直到成功"""
        from ..proto import ifmsg_pb2, devicemsg_pb2

        while self._auth_running and not self._auth_success:
            try:
                device_msg = ifmsg_pb2.DeviceMsg()
                device_msg.timeStamps = int(time.time() * 1000)
                device_msg.authentication.authCode = self._imei

                payload = device_msg.SerializeToString()
                logger.info(f"[RealCloud] ↑ DeviceMsg (auth):\n{device_msg}")
                self._mqtt.publish(self._topic_uplink, payload, qos=1)
                with self._stats_lock:
                    self._uplink_count += 1
            except Exception as e:
                logger.error(f"[RealCloud] Auth send failed: {e}")

            # 等待 5 秒或直到停止
            for _ in range(50):
                if not self._auth_running or self._auth_success:
                    break
                time.sleep(0.1)

    # ========== 云端消息分发 ==========

    def _dispatch_cloud_msg(self, cloud_msg, topic: str):
        """根据 CloudMsg oneof 类型分发处理"""
        msg_type = cloud_msg.WhichOneof("MsgUnion")
        if msg_type is None:
            return

        if msg_type == "authenticationApply":
            self._handle_auth_response(cloud_msg.authenticationApply)
        elif msg_type == "commonResult":
            self._handle_common_result(cloud_msg.commonResult)
        elif msg_type == "serverParamsQueryResponse":
            self._handle_server_params(cloud_msg.serverParamsQueryResponse)
        elif msg_type == "dispatchTask":
            self._handle_dispatch_task(cloud_msg.dispatchTask)
        elif msg_type == "movemntAuthoritySend":
            self._handle_move_authority(cloud_msg.movemntAuthoritySend)
        elif msg_type == "truckStatus":
            self._handle_truck_status(cloud_msg.truckStatus)

    def _handle_auth_response(self, auth_apply):
        """处理鉴权应答"""
        if auth_apply.resultCode == 0:
            self._auth_success = True
            self._project_id = str(auth_apply.projectId) if auth_apply.projectId else ""
            self._state = self.STATE_AUTHENTICATED
            logger.info(
                f"[RealCloud] Authentication success. "
                f"device={auth_apply.deviceName}, project={self._project_id}"
            )
            # 查询服务器参数
            self._query_server_params()
        else:
            logger.warning(f"[RealCloud] Authentication failed: resultCode={auth_apply.resultCode}")

    def _handle_common_result(self, common_result):
        """处理通用应答 (对应 C++ DealCommonResult)"""
        logger.info(
            f"[RealCloud] CommonResult: flowId={common_result.flowId}, "
            f"replyId={common_result.replyId}, resultCode={common_result.resultCode}"
        )

    def _handle_truck_status(self, truck_status):
        """处理云端下发的 TruckStatus (对应 C++ DealTruckStatus)

        存储 taskStatus 和 loadState，供上行报告使用。
        """
        self._task_status = truck_status.taskStatus
        self._load_state = truck_status.loadState
        logger.info(
            f"[RealCloud] TruckStatus: taskStatus={self._task_status}, "
            f"loadState={self._load_state}"
        )
        # 每次收到云端状态时检查是否有失败的下载需要重试
        self._retry_failed_downloads()

    def _query_server_params(self):
        """发送服务器参数查询"""
        from ..proto import ifmsg_pb2
        try:
            device_msg = ifmsg_pb2.DeviceMsg()
            device_msg.timeStamps = int(time.time() * 1000)
            device_msg.serverParamsQuery.SetInParent()
            payload = device_msg.SerializeToString()
            logger.info(f"[RealCloud] ↑ DeviceMsg (params_query):\n{device_msg}")
            self._mqtt.publish(self._topic_uplink, payload, qos=1)
            with self._stats_lock:
                self._uplink_count += 1
            self._params_query_sent = True
            logger.info("[RealCloud] Server params query sent")
        except Exception as e:
            logger.error(f"[RealCloud] Server params query failed: {e}")

    def _handle_server_params(self, response):
        """处理服务器参数查询应答 (对应 C++ DealServerParamsQueryResponse)"""
        self._params_queried = True
        for param in response.list:
            if param.id == 0xF000:
                self._map_file_name = param.content
            elif param.id == 0xF001:
                self._map_md5 = param.content
            elif param.id == 0xF002:
                self._download_base_url = param.content
        logger.info(
            f"[RealCloud] Server params: map={self._map_file_name}, "
            f"md5={self._map_md5}, dl={self._download_base_url}"
        )
        self._state = self.STATE_RUNNING

        # 自动下载地图文件 (对应 C++ DealServerParamsQueryResponse → downloadFile(map_info))
        if self._map_file_name and self._download_base_url:
            self._download_map_file()

        # 重放缓存的 DispatchTask (保留消息在鉴权完成前到达)
        if self._pending_dispatch_proto is not None:
            logger.info("[RealCloud] Replaying cached DispatchTask")
            cached = self._pending_dispatch_proto
            self._pending_dispatch_proto = None
            self._handle_dispatch_task(cached)

    def _retry_failed_downloads(self) -> None:
        """周期重试失败的下载 (地图 / 任务)

        云端可能在仿真启动后才上传文件，首次请求 404 不代表文件永远不可用。
        每次收到 TruckStatus 时触发重试，间隔由云端下发频率决定 (~2s)。
        """
        import os
        now = time.time()

        # ── 地图下载重试 ──
        if self._map_download_status == "failed" and self._map_file_name and self._download_base_url:
            if not getattr(self, '_last_map_retry_time', 0) or now - self._last_map_retry_time >= 30:
                self._last_map_retry_time = now
                logger.info(f"[RealCloud] Retrying map download: {self._map_file_name}")
                self._download_map_file()
                # 地图下载成功后，若之前任务因 URL 未就绪而缓存，立即重放
                if self._map_download_status == "success" and self._pending_dispatch_proto is not None:
                    logger.info("[RealCloud] Replaying cached DispatchTask after map download success")
                    cached = self._pending_dispatch_proto
                    self._pending_dispatch_proto = None
                    self._handle_dispatch_task(cached)

        # ── 任务下载重试 ──
        if self._task_download_status == "failed" and self._task_download_name and self._download_base_url:
            if not getattr(self, '_last_task_retry_time', 0) or now - self._last_task_retry_time >= 30:
                self._last_task_retry_time = now
                logger.info(f"[RealCloud] Retrying task download: {self._task_download_name}")
                self._download_and_retry_task()

    def _download_and_retry_task(self) -> None:
        """重试下载任务文件，成功后发布到 SimMessageBus"""
        if not self._task_download_name:
            return
        task_path = self._download_and_extract_task(self._task_download_name)
        if not task_path:
            return

        # 重新构造 DispatchTask 并发布
        dispatch = SimDispatchTask(
            task_sn=self._pending_task_sn if hasattr(self, '_pending_task_sn') else "",
            task_type=self._pending_task_type if hasattr(self, '_pending_task_type') else 0,
            task_file_path=task_path,
            file_md5=getattr(self, '_pending_task_md5', ""),
            action_seq=list(getattr(self, '_pending_action_seq', [])),
            command_type=getattr(self, '_pending_command_type', 0),
            target_name=getattr(self, '_pending_target_name', ""),
            dispatch_result=getattr(self, '_pending_dispatch_result', 1),
        )
        cd_task = CloudDispatchTask(
            msg_type="dispatch_task",
            dispatch_task=dispatch,
            timestamp=time.time(),
        )
        self._bus.publish(CLOUD_DISPATCH_TASK, cd_task)

    def _download_map_file(self) -> None:
        """下载地图文件 (对应 C++ DealServerParamsQueryResponse 中 downloadFile(map_info))

        C++: downloadFile(map_info_, file_address_, map_folder)
             → 保存到 map_folder + info.name (config "addr.map_file_folder")
        """
        import os
        self._map_download_status = "downloading"
        os.makedirs(self._map_file_folder, exist_ok=True)
        dest = HttpDownloader.download_task_file(
            base_url=self._download_base_url,
            file_name=self._map_file_name,
            dest_dir=self._map_file_folder,
            project_id=self._project_id,
        )
        if dest:
            self._map_download_status = "success"
            self._map_download_path = dest
            logger.info(f"[RealCloud] Map downloaded: {dest}")
        else:
            self._map_download_status = "failed"
            self._map_download_path = ""
            logger.warning(f"[RealCloud] Map download failed: {self._map_file_name}")

    # ========== 下行 → SimMessageBus ==========

    def _handle_dispatch_task(self, dispatch_task_proto):
        """收到 DispatchTask → 下载 tar.gz → 发布到 SimMessageBus

        对应 C++ GateWay::DealDispatchTask (gateway.cc:619)
        """
        # 检查调度结果 (对应 C++ dispatchresult() != 0x01)
        dispatch_result = dispatch_task_proto.dispatchResult
        if dispatch_result != 1:
            self._task_download_status = "failed"
            logger.warning(
                f"[RealCloud] DispatchTask rejected: dispatchResult={dispatch_result}, "
                f"reason={dispatch_task_proto.failReason}"
            )
            return

        command = dispatch_task_proto.command
        task_sn = str(dispatch_task_proto.taskSn)
        file_name = command.path if command.path else ""
        file_md5 = command.fileMd5 if command.fileMd5 else ""

        # 解析 actions (protobuf: Action{actionType, toPoint{longitude, latitude, heading}})
        actions = []
        for act in command.actionSeq:
            tp = act.toPoint
            actions.append(Action(
                action_type=act.actionType,
                lon=tp.longitude,
                lat=tp.latitude,
                heading=tp.heading,
            ))

        self._task_download_name = file_name
        self._task_md5 = file_md5

        # 缓存任务信息以便下载失败后重试
        self._pending_task_sn = task_sn
        self._pending_task_type = dispatch_task_proto.taskType
        self._pending_task_md5 = file_md5
        self._pending_action_seq = actions
        self._pending_command_type = command.commandType
        self._pending_target_name = command.commandTargetName
        self._pending_dispatch_result = dispatch_result

        # HTTP 下载并解压任务文件 → 获得本地路径
        if not file_name:
            self._task_download_status = "failed"
            logger.warning("[RealCloud] DispatchTask skipped: command.path is empty")
            return
        if not self._download_base_url:
            # 服务器参数尚未就绪 (保留消息在鉴权前到达)，缓存等 URL 就绪后重放
            self._task_download_status = "pending"
            self._pending_dispatch_proto = dispatch_task_proto
            logger.info(
                f"[RealCloud] DispatchTask cached (awaiting server params): "
                f"sn={task_sn}, file={file_name}"
            )
            return

        download_url = f"{self._download_base_url.rstrip('/')}?fileName={file_name}"
        self._task_download_url = download_url
        logger.info(f"[RealCloud] Task download URL: {download_url}")
        task_path = self._download_and_extract_task(file_name)
        if not task_path:
            return

        # 发布到 SimMessageBus（仅在下载和解压全部成功后）
        dispatch = SimDispatchTask(
            task_sn=task_sn,
            task_type=dispatch_task_proto.taskType,
            task_file_path=task_path,
            file_md5=file_md5,
            action_seq=actions,
            command_type=command.commandType,
            target_name=command.commandTargetName,
            dispatch_result=dispatch_result,
        )
        cd_task = CloudDispatchTask(
            msg_type="dispatch_task",
            dispatch_task=dispatch,
            timestamp=time.time(),
        )
        self._bus.publish(CLOUD_DISPATCH_TASK, cd_task)

    def _download_and_extract_task(self, file_name: str) -> str:
        """下载并解压任务文件 (.tar.gz)，返回解压后的目录路径；失败返回空字符串

        对应 C++ DealDispatchTask → downloadFile + publicTaskToPnc (gateway.cc:635-652)
        """
        self._task_download_status = "downloading"
        os.makedirs(self._task_file_folder, exist_ok=True)
        dest = HttpDownloader.download_task_file(
            base_url=self._download_base_url,
            file_name=file_name,
            dest_dir=self._task_file_folder,
            project_id=self._project_id,
        )
        if not dest:
            self._task_download_status = "failed"
            self._task_download_path = ""
            logger.error(f"[RealCloud] Task file download failed: {file_name}")
            return ""

        self._task_download_path = dest
        extract_dir = os.path.join(
            self._task_file_folder,
            f"task_{os.path.splitext(os.path.splitext(file_name)[0])[0]}",
        )
        try:
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(dest, "r:gz") as tar:
                tar.extractall(extract_dir)
            self._task_download_status = "success"
            logger.info(f"[RealCloud] Task extracted to: {extract_dir}")
            return extract_dir
        except Exception as e:
            self._task_download_status = "failed"
            logger.error(f"[RealCloud] Extract failed: {e}")
            return ""

    def _handle_move_authority(self, ma_proto):
        """收到 MovemntAuthoritySend → 发布到 SimMessageBus MOVE_AUTHORITY

        提取全部路权字段 (对应 C++ DealMovemntAuthoritySend + BussinessDecision):
          - safeOccupied.startPoint / endPoint
          - MovemntAuthor list (分段车道信息)
          - lineSnQ (车道线序号序列)
        """
        # safeOccupied
        safe = ma_proto.safeOccupied
        start_pt = safe.startPoint
        end_pt = safe.endPoint

        # lineSnQ → 逗号分隔字符串
        line_snq = ",".join(str(sn) for sn in safe.lineSnQ)

        # MovemntAuthor list
        segment_count = len(ma_proto.list)
        last_lane_id = 0
        last_point_index = 0
        last_direction = 0.0
        ep_lat, ep_lon = 0.0, 0.0
        if ma_proto.list:
            last = ma_proto.list[-1]
            last_lane_id = last.laneId
            last_point_index = last.pointIndex
            last_direction = last.direction
            ep_lat = last.lat
            ep_lon = last.lon

        # stop_index 初始用 endPoint 的 index (后续由 BusinessDecision 在参考线上计算)
        ma = SimMoveAuthority(
            endpoint_lat=end_pt.lat if end_pt.lat else ep_lat,
            endpoint_lon=end_pt.lon if end_pt.lon else ep_lon,
            end_point_index=end_pt.index,
            end_point_line_sn=end_pt.lineSn,
            start_point_lat=start_pt.lat,
            start_point_lon=start_pt.lon,
            start_point_index=start_pt.index,
            start_point_line_sn=start_pt.lineSn,
            right_of_way_index=last_point_index,
            stop_index=last_point_index,
            segment_count=segment_count,
            last_lane_id=last_lane_id,
            last_point_index=last_point_index,
            last_direction=last_direction,
            line_snq=line_snq,
            timestamp=time.time(),
        )
        self._bus.publish(MOVE_AUTHORITY, ma)

    # ========== 上行: SimMessageBus → Protobuf → MQTT ==========

    def _on_uplink_device_msg(self, topic: str, msg: CloudDeviceMsg):
        """收到内部总线的上行消息 → 序列化为 Protobuf → MQTT 发布

        对应 C++ GateWay::checkStatus(): MQTT 已连接 + 已鉴权 + 已初始化(参数已获取)。
        鉴权成功即发送上行报告。
        """
        if not self._auth_success:
            logger.debug("[RealCloud] Uplink blocked: not authenticated")
            return

        from ..proto import ifmsg_pb2

        try:
            device_msg = ifmsg_pb2.DeviceMsg()
            device_msg.timeStamps = int(time.time() * 1000)

            if msg.msg_type == "position_report":
                self._fill_position_report(device_msg, msg.payload)
            elif msg.msg_type == "monitor_report":
                self._fill_monitor_report(device_msg, msg.payload)
            elif msg.msg_type == "state_report":
                self._fill_state_report(device_msg, msg.payload)
            elif msg.msg_type == "stop_obstacle_info":
                self._fill_stop_obstacle_info(device_msg, msg.payload)
            else:
                return

            logger.info(f"[RealCloud] ↑ DeviceMsg ({msg.msg_type}):\n{device_msg}")
            payload = device_msg.SerializeToString()
            self._mqtt.publish(self._topic_uplink, payload, qos=1)
            with self._stats_lock:
                self._uplink_count += 1
        except Exception as e:
            logger.error(f"[RealCloud] Uplink failed: {e}")

    @staticmethod
    def _safe_int(v, default: int = 0) -> int:
        """安全转换为 int（处理 protobuf uint32/uint64 字段类型拒绝 str 的问题）"""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return default
        try:
            return int(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_float(v, default: float = 0.0) -> float:
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return default
        return float(v) if v is not None else default

    @staticmethod
    def _safe_bool(v, default: bool = False) -> bool:
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v) if v is not None else default

    def _fill_position_report(self, device_msg, payload: dict):
        rpt = device_msg.truckPositionReport
        rpt.longitude = self._safe_float(payload.get("longitude"))
        rpt.latitude = self._safe_float(payload.get("latitude"))
        rpt.altitude = self._safe_float(payload.get("altitude"))
        rpt.direction = self._safe_float(payload.get("direction"))
        rpt.speed = self._safe_float(payload.get("speed"))
        rpt.battery = self._safe_float(payload.get("battery", 85.0))
        rpt.batteryCapacity = self._safe_float(payload.get("batteryCapacity", 300.0))
        rpt.roadId = self._safe_int(payload.get("roadId"))
        rpt.pointIndex = self._safe_int(payload.get("pointIndex"))
        rpt.roadResidualDistance = self._safe_float(payload.get("roadResidualDistance"))
        rpt.operationType = self._safe_int(payload.get("operationType", 1))
        rpt.reasonCode = self._safe_int(payload.get("reasonCode"))
        rpt.runState = self._safe_int(payload.get("runState", 1))
        rpt.stopReason = self._safe_int(payload.get("stopReason"))
        rpt.taskSn = self._safe_int(payload.get("taskSn"), 0)
        rpt.taskType = self._safe_int(payload.get("taskType"))
        rpt.taskStatus = self._safe_int(payload.get("taskStatus"))
        rpt.commandType = self._safe_int(payload.get("commandType"))
        rpt.actionType = self._safe_int(payload.get("actionType"))
        rpt.actionStatus = self._safe_int(payload.get("actionStatus"))
        rpt.utcMilliSeconds = self._safe_int(payload.get("utcMilliSeconds"))
        rpt.speedDeviation = self._safe_float(payload.get("speedDeviation"))
        rpt.subMachineState = str(payload.get("subMachineState", "0"))
        rpt.detourStatus = self._safe_int(payload.get("detourStatus"))
        rpt.isAgileObstacle = self._safe_bool(payload.get("isAgileObstacle"))
        rpt.wirelessSignal = self._safe_int(payload.get("wirelessSignal", 80))
        rpt.status.accState = 1
        rpt.status.GPSState = 3
        rpt.status.drivingMode = 1  # 01=自动驾驶 (00=人工驾驶, 10=远程接管)
        rpt.status.lockState = 0
        rpt.status.brakeState = 0
        rpt.status.vehicleGearState = 3

    def _fill_monitor_report(self, device_msg, payload: dict):
        rpt = device_msg.truckMonitorReport
        rpt.longitude = self._safe_float(payload.get("longitude"))
        rpt.latitude = self._safe_float(payload.get("latitude"))
        rpt.altitude = self._safe_float(payload.get("altitude"))
        rpt.direction = self._safe_float(payload.get("direction"))
        rpt.speed = self._safe_float(payload.get("speed"))
        rpt.lateralError = self._safe_float(payload.get("lateralError"))
        rpt.spin = self._safe_float(payload.get("spin"))
        rpt.throttleOpenAuto = self._safe_float(payload.get("throttleOpenAuto"))
        rpt.throttleOpenManual = self._safe_float(payload.get("throttleOpenManual"))
        rpt.brakeOpenAuto = self._safe_float(payload.get("brakeOpenAuto"))
        rpt.brakeOpenManual = self._safe_float(payload.get("brakeOpenManual"))
        rpt.limitSpeed = self._safe_float(payload.get("limitSpeed", 30.0))

    def _fill_state_report(self, device_msg, payload: dict):
        rpt = device_msg.truckSateReport
        rpt.longitude = self._safe_float(payload.get("longitude"))
        rpt.latitude = self._safe_float(payload.get("latitude"))
        rpt.altitude = self._safe_float(payload.get("altitude"))
        rpt.direction = self._safe_float(payload.get("direction"))
        rpt.frontWheelDirection = self._safe_float(payload.get("frontWheelDirection"))
        rpt.frontWheelAngularError = self._safe_float(payload.get("frontWheelAngularError"))
        rpt.oilPressure = self._safe_float(payload.get("oilPressure", 350.0))
        rpt.coolantTemperature = self._safe_float(payload.get("coolantTemperature", 85.0))
        rpt.batteryVoltage = self._safe_float(payload.get("batteryVoltage", 600.0))
        rpt.fuelLevel = self._safe_float(payload.get("fuelLevel", 85.0))
        rpt.mileage = self._safe_float(payload.get("mileage"))
        rpt.liftAngle = self._safe_float(payload.get("liftAngle"))

    def _fill_stop_obstacle_info(self, device_msg, payload: dict):
        """构造 StopObstacleInfo protobuf (对应 C++ recvPerceptionFrontMsg)"""
        info = device_msg.stopObstacleInfo
        info.ts = self._safe_int(payload.get("ts"))
        info.stopTs = self._safe_int(payload.get("stopTs"))
        info.impactType = self._safe_int(payload.get("impactType"))
        # currentPose
        cp = payload.get("currentPose", {})
        if cp:
            info.currentPose.lon = self._safe_float(cp.get("lon"))
            info.currentPose.lat = self._safe_float(cp.get("lat"))
            info.currentPose.heading = self._safe_float(cp.get("heading"))
        # impactPose
        ip = payload.get("impactPose", {})
        if ip:
            info.impactPose.lon = self._safe_float(ip.get("lon"))
            info.impactPose.lat = self._safe_float(ip.get("lat"))
            info.impactPose.heading = self._safe_float(ip.get("heading"))
        # impactObstacle polygons
        for obs in payload.get("impactObstacle", []):
            poly = info.impactObstacle.add()
            for pt in obs.get("pointList", []):
                gps = poly.pointList.add()
                gps.lat = self._safe_float(pt.get("lat"))
                gps.lon = self._safe_float(pt.get("lon"))
        # otherObstacle polygons
        for obs in payload.get("otherObstacle", []):
            poly = info.otherObstacle.add()
            for pt in obs.get("pointList", []):
                gps = poly.pointList.add()
                gps.lat = self._safe_float(pt.get("lat"))
                gps.lon = self._safe_float(pt.get("lon"))

    # ========== 配置 ==========

    def _load_default_config(self):
        self._config["mqtt"] = {
            "broker": os.environ.get("SIM_MQTT_BROKER", "tcp://127.0.0.1:11883"),
            "client_id_prefix": "device_",
            "username": os.environ.get("SIM_MQTT_USERNAME", ""),
            "password": os.environ.get("SIM_MQTT_PASSWORD", ""),
            "keepalive": "60",
        }
        self._config["device"] = {
            "imei": os.environ.get("SIM_DEVICE_IMEI", "200000000000001"),
        }
        self._config["download"] = {
            "task_file_folder": os.environ.get("SIM_TASK_DIR", "/tmp/sim_tasks/"),
            "map_file_folder": os.environ.get("SIM_MAP_DIR", "/tmp/sim_maps/"),
        }

    # ========== 统计/兼容接口 ==========

    def get_stats(self) -> dict:
        with self._stats_lock:
            return {
                "state": self._state,
                "authenticated": self._auth_success,
                "params_query_sent": self._params_query_sent,
                "params_queried": self._params_queried,
                "mqtt_broker": self._broker,
                "imei": self._imei,
                "project_id": self._project_id,
                "uplink_count": self._uplink_count,
                "downlink_count": self._downlink_count,
                "task_status": self._task_status,
                "load_state": self._load_state,
                "map_file": self._map_file_name,
                "map_md5": self._map_md5,
                "download_base_url": self._download_base_url,
                "map_download_status": self._map_download_status,
                "map_download_path": self._map_download_path,
                "task_download_status": self._task_download_status,
                "task_download_url": self._task_download_url,
                "task_download_path": self._task_download_path,
                "task_download_name": self._task_download_name,
                "task_md5": self._task_md5,
                "last_error": self._last_error,
            }

    def start_auth_handshake(self) -> str:
        """兼容 CloudCommSim 接口"""
        self.connect()
        return str(self._auth_flow_id)

    def reset(self):
        self.disconnect()
        self._auth_success = False
        self._params_query_sent = False
        self._params_queried = False
        self._map_download_status = ""
        self._map_download_path = ""
        self._task_download_status = ""
        self._task_download_url = ""
        self._task_download_path = ""
        self._task_download_name = ""
        self._task_md5 = ""
        self._task_status = 0
        self._load_state = 0
        with self._stats_lock:
            self._uplink_count = 0
            self._downlink_count = 0
            self._last_error = ""
