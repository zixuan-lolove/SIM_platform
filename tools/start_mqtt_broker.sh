#!/bin/bash
# 启动本地 MQTT Broker (mosquitto) 用于仿真平台云端通信测试
# Port: 11883 (匹配 cloud_config.ini 默认配置)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOSQ_DIR="$SCRIPT_DIR/mosquitto"

export LD_LIBRARY_PATH="$MOSQ_DIR/lib:$LD_LIBRARY_PATH"

echo "=== 启动本地 MQTT Broker ==="
echo "地址: tcp://127.0.0.1:11883"
echo "日志:"
echo ""

exec "$MOSQ_DIR/mosquitto" -c "$MOSQ_DIR/mosquitto.conf"
