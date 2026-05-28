"""Protobuf 编译产物 — 云端 MQTT 消息序列化

用法:
    from sim_platform.proto import ifmsg_pb2
    msg = ifmsg_pb2.DeviceMsg()
    msg.authentication.authCode = "200000000000001"
"""

import sys
from pathlib import Path

_proto_dir = Path(__file__).parent
if str(_proto_dir) not in sys.path:
    sys.path.insert(0, str(_proto_dir))
