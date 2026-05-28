#!/usr/bin/env python3
"""Mock 云端平台 — 用于仿真平台 MQTT 通信测试 (F-17)

在本地 MQTT Broker 上模拟完整的云端交互协议:

  车端                                Mock Cloud
  ────                                ─────────
  CONNECT ─────────────────────────→  (broker)
  publish up/truck/{imei}:DeviceMsg{authentication}
                                      → publish down/truck/{imei}:CloudMsg{authenticationApply}
  publish up/truck/{imei}:DeviceMsg{serverParamsQuery}
                                      → publish down/truck/{imei}:CloudMsg{serverParamsQueryResponse}
                                      → publish /retain/down/status/truck/{imei}:CloudMsg{truckStatus}
                                      可选: 下发 DispatchTask

使用方法:
  1. 一键启动:       cd tools && ./start_local_cloud.sh
  2. 或手动两步:
     - 启动 Broker:  cd tools && ./start_mqtt_broker.sh
     - 启动 Mock:    cd tools && python mock_cloud_server.py
  3. 启动仿真平台, 设置环境变量:
     export SIM_MQTT_BROKER=tcp://127.0.0.1:11883
     或直接使用 cloud_config_local.ini
"""

import logging
import os
import signal
import sys
import threading
import time
from argparse import ArgumentParser
from typing import Optional

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MockCloud] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MockCloud")


class MockCloudServer:
    """模拟云端服务器

    监听 MQTT uplink topic，按协议返回 CloudMsg 响应。
    """

    def __init__(
        self,
        broker: str = "127.0.0.1",
        port: int = 11883,
        project_id: int = 12345,
        device_name: str = "SIM-001",
    ):
        self._broker = broker
        self._port = port
        self._project_id = project_id
        self._device_name = device_name
        self._running = False

        # MQTT client
        self._client = mqtt.Client(
            client_id=f"mock_cloud_{os.getpid()}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
            callback_api_version=CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # 已鉴权的设备 IMEI 集合
        self._authenticated_devices: set[str] = set()

        # 统计
        self._msg_count: int = 0
        self._lock = threading.Lock()

    # ========== 生命周期 ==========

    def start(self) -> None:
        logger.info(f"Mock Cloud 启动中... broker={self._broker}:{self._port}")
        self._running = True
        try:
            self._client.connect_async(self._broker, self._port, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            logger.error(f"连接 broker 失败: {e}")
            self._running = False
            return

        self._print_info()
        self._wait_forever()

    def stop(self) -> None:
        logger.info("Mock Cloud 关闭中...")
        self._running = False
        self._client.loop_stop()
        self._client.disconnect()

    # ========== MQTT 回调 ==========

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        if reason_code.value == 0:
            logger.info(f"已连接到 broker ({self._broker}:{self._port})")
            client.subscribe("up/truck/+", qos=1)
            logger.info("已订阅: up/truck/+")
        else:
            logger.error(f"连接失败: reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"断开连接 (rc={reason_code})")
        if self._running:
            logger.info("自动重连中...")

    def _on_message(self, client, userdata, msg):
        """收到车端上行消息 → 解析 → 响应"""
        with self._lock:
            self._msg_count += 1

        # 从 topic 提取 IMEI
        imei = self._extract_imei(msg.topic)
        if not imei:
            logger.warning(f"无法从 topic 提取 IMEI: {msg.topic}")
            return

        logger.info(f"收到上行消息: topic={msg.topic}, imei={imei}, len={len(msg.payload)}")

        try:
            from sim_platform.proto import ifmsg_pb2
            device_msg = ifmsg_pb2.DeviceMsg()
            device_msg.ParseFromString(msg.payload)
            self._handle_device_msg(client, imei, device_msg)
        except Exception as e:
            logger.error(f"解析 DeviceMsg 失败: {e}")

    # ========== 消息分发 ==========

    def _handle_device_msg(self, client, imei: str, device_msg):
        msg_type = device_msg.WhichOneof("MsgUnion")
        if msg_type is None:
            logger.warning(f"DeviceMsg 无 MsgUnion: imei={imei}")
            return

        logger.info(f"  └─ 消息类型: {msg_type}")

        if msg_type == "authentication":
            self._handle_auth(client, imei, device_msg)
        elif msg_type == "serverParamsQuery":
            self._handle_params_query(client, imei, device_msg)
        elif msg_type == "truckPositionReport":
            self._log_position_report(imei, device_msg.truckPositionReport)
        elif msg_type == "truckMonitorReport":
            logger.info(f"  └─ Monitor: speed={device_msg.truckMonitorReport.speed:.1f}")
        elif msg_type == "truckSateReport":
            logger.info(f"  └─ State: mileage={device_msg.truckSateReport.mileage:.1f}")
        elif msg_type == "stopObstacleInfo":
            logger.info(f"  └─ StopObstacle: ts={device_msg.stopObstacleInfo.ts}")
        else:
            logger.info(f"  └─ (未处理的消息类型: {msg_type})")

    # ========== 鉴权应答 ==========

    def _handle_auth(self, client, imei: str, device_msg):
        auth = device_msg.authentication
        logger.info(f"  └─ 鉴权请求: authCode={auth.authCode}")

        # 构造 CloudMsg{authenticationApply}
        from sim_platform.proto import ifmsg_pb2, cloudmsg_pb2

        cloud_msg = ifmsg_pb2.CloudMsg()
        cloud_msg.timeStamps = int(time.time() * 1000)
        cloud_msg.flowId = device_msg.flowId

        auth_apply = cloud_msg.authenticationApply
        auth_apply.flowId = device_msg.flowId
        auth_apply.replyId = 3  # 对应 DeviceMsg.authentication field number
        auth_apply.resultCode = 0  # 0 = 成功
        auth_apply.deviceName = f"{self._device_name}_{imei[-6:]}"
        auth_apply.mode = 1
        auth_apply.projectId = self._project_id

        payload = cloud_msg.SerializeToString()
        topic = f"down/truck/{imei}"

        client.publish(topic, payload, qos=1)
        self._authenticated_devices.add(imei)
        logger.info(
            f"  └─ 鉴权应答: resultCode=0, projectId={self._project_id}, "
            f"device={auth_apply.deviceName} → {topic}"
        )

    # ========== 服务器参数查询 ==========

    def _handle_params_query(self, client, imei: str, device_msg):
        logger.info(f"  └─ 参数查询: imei={imei}")

        from sim_platform.proto import ifmsg_pb2, cloudmsg_pb2

        cloud_msg = ifmsg_pb2.CloudMsg()
        cloud_msg.timeStamps = int(time.time() * 1000)
        cloud_msg.flowId = device_msg.flowId

        resp = cloud_msg.serverParamsQueryResponse
        resp.flowId = device_msg.flowId

        params = [
            (0xF000, "sim_test_map.bin"),
            (0xF001, "d41d8cd98f00b204e9800998ecf8427e"),
            (0xF002, ""),
        ]
        for param_id, param_val in params:
            param = resp.list.add()
            param.id = param_id
            param.length = len(param_val)
            param.content = param_val

        resp.contentLength = resp.list.__len__()

        payload = cloud_msg.SerializeToString()
        topic = f"down/truck/{imei}"

        client.publish(topic, payload, qos=1)
        logger.info(f"  └─ 参数查询应答: {len(params)} 条参数 → {topic}")

        # 自动下发 TruckStatus (retained topic)
        self._publish_truck_status(client, imei)

    # ========== TruckStatus 下发 (retained) ==========

    def _publish_truck_status(self, client, imei: str):
        from sim_platform.proto import ifmsg_pb2

        cloud_msg = ifmsg_pb2.CloudMsg()
        cloud_msg.timeStamps = int(time.time() * 1000)

        ts = cloud_msg.truckStatus
        ts.deviceName = f"{self._device_name}_{imei[-6:]}"
        ts.operationalState = 1  # 就绪运行
        ts.taskStatus = 0  # 空闲
        ts.loadState = 1  # 空载
        ts.obeyStatus = 1  # 按令行驶

        topic = f"/retain/down/status/truck/{imei}"
        client.publish(topic, cloud_msg.SerializeToString(), qos=1, retain=True)
        logger.info(f"  └─ TruckStatus 下发: taskStatus=0, loadState=1 → {topic}")

    # ========== 任务下发 (可选, 通过 API 触发) ==========

    def dispatch_task(
        self,
        imei: str,
        task_sn: int = 1001,
        task_type: int = 5,  # TEST
        command_type: int = 0,
        target_name: str = "仿真测试点",
        actions: list | None = None,
    ) -> None:
        """下发 DispatchTask 到指定设备

        可通过 IPC (stdin / HTTP / socket) 调用，用于手动触发任务下发。
        """
        from sim_platform.proto import ifmsg_pb2, cloudmsg_pb2

        cloud_msg = ifmsg_pb2.CloudMsg()
        cloud_msg.timeStamps = int(time.time() * 1000)

        dt = cloud_msg.dispatchTask
        dt.taskSn = task_sn
        dt.taskType = task_type
        dt.dispatchResult = 1  # SUCCESS
        dt.dispatchTarget.targetName = target_name
        dt.dispatchTarget.targetElementId = 100
        dt.dispatchTarget.targetType = 3  # 其他

        cmd = dt.command
        cmd.commandType = command_type
        cmd.commandTargetName = target_name
        cmd.path = ""
        cmd.fileMd5 = ""

        if actions:
            for act in actions:
                a = cmd.actionSeq.add()
                a.actionType = act.get("action_type", 1)
                a.toPoint.longitude = act.get("lon", 0.0)
                a.toPoint.latitude = act.get("lat", 0.0)
                a.toPoint.heading = act.get("heading", 0.0)

        topic = f"down/truck/{imei}"
        self._client.publish(topic, cloud_msg.SerializeToString(), qos=1)
        logger.info(f"  └─ DispatchTask 下发: taskSn={task_sn} → {topic}")

    # ========== 上行报告日志 ==========

    def _log_position_report(self, imei: str, rpt):
        """打印位置报告摘要 (节流)"""
        logger.info(
            f"  └─ Position: "
            f"lat={rpt.latitude:.6f}, lon={rpt.longitude:.6f}, "
            f"heading={rpt.direction:.1f}°, speed={rpt.speed:.1f}km/h, "
            f"taskSn={rpt.taskSn}, taskStatus={rpt.taskStatus}"
        )

    # ========== 工具 ==========

    @staticmethod
    def _extract_imei(topic: str) -> Optional[str]:
        parts = topic.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "up" and parts[1] == "truck":
            return parts[2]
        return None

    def _print_info(self) -> None:
        logger.info("═" * 50)
        logger.info("Mock Cloud 已就绪")
        logger.info(f"  Broker:   {self._broker}:{self._port}")
        logger.info(f"  Project:  {self._project_id}")
        logger.info(f"  Device:   {self._device_name}_XXXXXX")
        logger.info("")
        logger.info("  通信流程:")
        logger.info("    1. 等待车端鉴权 (Authentication)")
        logger.info("    2. 应答鉴权成功 (authenticationApply)")
        logger.info("    3. 响应参数查询 (serverParamsQueryResponse)")
        logger.info("    4. 下发 TruckStatus (retained)")
        logger.info("    5. 持续接收 PositionReport / MonitorReport")
        logger.info("")
        logger.info("  输入命令:")
        logger.info("    task <imei> [task_sn]  — 下发测试任务")
        logger.info("    status                  — 显示当前状态")
        logger.info("    quit                    — 退出")
        logger.info("═" * 50)

    def _print_status(self) -> None:
        with self._lock:
            logger.info(f"  已鉴权设备: {self._authenticated_devices or '(无)'}")
            logger.info(f"  消息总数: {self._msg_count}")

    def _wait_forever(self) -> None:
        """等待用户输入 (支持交互式命令)"""
        try:
            while self._running:
                try:
                    line = input()
                except EOFError:
                    # 非交互模式，等待信号
                    signal.pause()
                    continue

                line = line.strip()
                if not line:
                    continue

                parts = line.split()
                cmd = parts[0].lower()

                if cmd == "quit" or cmd == "exit":
                    self.stop()
                    break
                elif cmd == "status":
                    self._print_status()
                elif cmd == "task" and len(parts) >= 2:
                    imei = parts[1]
                    task_sn = int(parts[2]) if len(parts) >= 3 else 1001
                    self.dispatch_task(imei, task_sn=task_sn)
                elif cmd == "help":
                    self._print_info()
                else:
                    logger.info(f"  未知命令: {cmd} (输入 help 查看帮助)")
        except KeyboardInterrupt:
            self.stop()


# ========== CLI ==========

def main():
    parser = ArgumentParser(description="Mock 云端平台 - SIM 仿真 MQTT 测试")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT broker 地址")
    parser.add_argument("--port", type=int, default=11883, help="MQTT broker 端口")
    parser.add_argument("--project", type=int, default=12345, help="项目 ID")
    parser.add_argument("--device", default="SIM-001", help="设备名称前缀")
    args = parser.parse_args()

    server = MockCloudServer(
        broker=args.broker,
        port=args.port,
        project_id=args.project,
        device_name=args.device,
    )
    server.start()


if __name__ == "__main__":
    main()
