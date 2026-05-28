#!/bin/bash
# 一键启动本地 MQTT Broker + Mock 云端平台
# 用于仿真平台全栈模式云端通信测试
#
# 使用方法:
#   1. 在此终端启动:  cd tools && ./start_local_cloud.sh
#   2. 在另一个终端启动仿真平台:
#      export SIM_USE_LOCAL_CLOUD=1
#      python main.py
#      (或在 VSCode 中设置环境变量 SIM_USE_LOCAL_CLOUD=1)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOSQ_DIR="$SCRIPT_DIR/mosquitto"
export LD_LIBRARY_PATH="$MOSQ_DIR/lib:$LD_LIBRARY_PATH"

cleanup() {
    echo ""
    echo "=== 关闭服务 ==="
    [ -n "$MOSQ_PID" ] && kill "$MOSQ_PID" 2>/dev/null && echo "  MQTT Broker 已关闭"
    [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null && echo "  Mock Cloud 已关闭"
    echo "完毕。"
}

trap cleanup EXIT INT TERM

echo "╔══════════════════════════════════════════════════════╗"
echo "║   SIM 仿真平台 - 本地云端测试环境                     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1. 启动 MQTT Broker
echo ">>> 启动 MQTT Broker (127.0.0.1:11883)..."
"$MOSQ_DIR/mosquitto" -c "$MOSQ_DIR/mosquitto.conf" &
MOSQ_PID=$!
sleep 1

if ! kill -0 "$MOSQ_PID" 2>/dev/null; then
    echo "ERROR: MQTT Broker 启动失败!"
    exit 1
fi
echo "  MQTT Broker PID=$MOSQ_PID"
echo ""

# 2. 启动 Mock Cloud
echo ">>> 启动 Mock Cloud Server..."
echo "  (在此终端输入命令: task <imei> 下发任务, status 查看状态, quit 退出)"
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  启动仿真平台前请设置环境变量:                         ║"
echo "║    export SIM_USE_LOCAL_CLOUD=1                      ║"
echo "║  或在 VSCode launch.json 中添加:                      ║"
echo "║    \"env\": {\"SIM_USE_LOCAL_CLOUD\": \"1\"}            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

python3 "$SCRIPT_DIR/mock_cloud_server.py" --broker 127.0.0.1 --port 11883 --project 12345 --device SIM-001 &
MOCK_PID=$!

# 等待 Mock Cloud 或用户中断
wait $MOCK_PID 2>/dev/null
