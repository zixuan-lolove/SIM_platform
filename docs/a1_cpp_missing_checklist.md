# C++ 代码工程功能开发 — 缺失项清单

> 版本：V3.2
> 日期：2026-06-02
> 编制依据：
> - 《测试用例集-决策+规划篇 v0.3》
> - C++ 源码审查：gateway/ planning/ control/ can_transformer/
> - 仿真 Python 端作为对照参考
> - 车云协议文档
> 状态：持续更新
>
> **V3.2 更新**: 新增 C-03 (B样条平滑后 heading 重算), Python 端已修复

---

## 文档说明

本文档统计 C++ 工程代码（Gateway / Planning / Control / CAN Transformer）中的**全部功能开发缺失项**，包括：

- **A 类**：A1 测试用例对应的数据质量验证功能缺失（源自测试用例集）
- **B 类**：车云通信协议功能缺失（源自协议文档与 Python 仿真端对照）
- **C 类**：规划管线功能缺失（源自算法源码审查）
- **D 类**：已确认的 C++ Bug（阻塞性缺陷）

每项标注对应模块、Python 端现状、以及影响范围。

---

## 概述

C++ 代码实现了数据路由**拓扑**（DDS pub/sub 和 MQTT topic 绑定）和基础规划控制管线，但存在大量**硬编码值、未集成模块、缺失的运行时验证**等问题。Python 仿真端已先行实现其中部分功能，可作为 C++ 开发的参考。

| 用例 | C++ 实现状态 | 缺失程度 |
|------|------------|---------|
| A1-01 数据路由验证 | ❌ 无运行时验证 | 全部缺失 |
| A1-02 时间戳验证 | ⚠️ 仅打时间戳，无验证 | 验证层缺失 |
| A1-03 周期处理验证 | ⚠️ 有漂移补偿，无丢帧检测 | 检测层缺失 |
| A1-04 延迟检测 | ⚠️ 有超时检测，但 Control 有 bug | 部分缺失 + bug |
| A1-05 故障处理 | ⚠️ 仅超时→停车，无故障诊断 | 诊断层缺失 |
| A1-06 航向跳变 | ❌ 无航向跳变检测 | 全部缺失 |
| A1-07 起点距离 | ⚠️ 有 2m 检查但无重规划，v0.3 要求 3m | 重规划缺失 + 阈值需更新 |

---

## 逐条详析

### A1-01：数据分类机制的准确性验证

**测试目标**：验证消息是否被正确路由到对应的 topic，消息类型是否与 topic 预期一致。

**C++ 现状**：
- 路由拓扑分散在三份 ini 配置文件中，无集中定义
- topic 名是运行时字符串，消息类型是编译期模板参数——两者无关联校验
- 无运行时消息类型验证（收到消息后直接 `ParseFromString`，不检查"这个 topic 上是否应该出现这个类型"）
- 无发布者身份检查

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-01-C1 | topic→消息类型映射表 | 全局 | 需要一份集中定义：`Localization topic ↔ common::Localization`，供所有模块引用和校验 |
| A1-01-C2 | DDS 消息类型运行时校验 | `planning.cc`, `control.cc`, `gateway.cc` | 各 DDS 回调中，收到消息后应先校验 topic 的预期类型是否与实际反序列化类型一致 |
| A1-01-C3 | MQTT→DDS 桥接路由校验 | `gateway.cc` | `deal_cloudmsg_map_` 已有 6 种 CloudMsg 分发，但缺少：分发后消息是否正确到达内部 topic 的确认 |
| A1-01-C4 | 发布者身份白名单 | 全局 | 定义每个 topic 允许的发布者集合：`Localization → {INS/IMU 模块}`，非白名单发布者应告警 |
| A1-01-C5 | 跨模块 topic 名一致性校验 | 构建期 / 启动期 | 校验 Gateway 的 `pub_task_topic` 与 Planning 的 `sub_task` 是否配置了相同的 topic URI |
| A1-01-C6 | 孤儿 topic 检测 | 启动期 | 检测已配置的 publisher 是否有对应的 subscriber，无人订阅应告警 |

---

### A1-02：时间戳记录的精度与完整性验证

**测试目标**：每条消息携带有效、单调递增的时间戳，精度满足要求。

**C++ 现状**：
- 时间戳工具类备妥：`gateway/src/time_stamp_util.h` 和 `planning/src/tools/time_stamp_util.h` 提供毫秒/微秒/纳秒级 Unix 时间戳
- Gateway 在构造上行消息时设置时间戳：`device_msg.set_timestamps(...)` （gateway.cc:406,492,561）
- Planning 在发布 PlanningResult 时设置 `time_stamp` （planning.cc:144）
- **但没有任何代码校验时间戳的有效性、单调性或精度**

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-02-C1 | 时间戳有效性检查 | 各 DDS 回调 | 收到消息后检查 `timestamp > 0` 且 `timestamp` 在合理范围（不能是未来时间） |
| A1-02-C2 | 时间戳单调性检查 | 各 DDS 回调 | 检查同一 topic 的消息时间戳是否严格递增（复位/重启时需考虑 epoch 重置） |
| A1-02-C3 | 时间戳精度检查 | `time_stamp_util.h` | 检查 `float` 时间戳的整数部分是否已经大到影响小数精度（虽然对 double 来说这是极其罕见的问题） |
| A1-02-C4 | 跨模块时间戳一致性 | 全局 | 来自不同时钟源（GNSS/系统时钟/MQTT 云端时间戳）的消息，时间戳偏差是否在可接受范围内 |
| A1-02-C5 | MQTT 消息时间戳可信度 | `gateway.cc` | 云端下发的 DispatchTask 中的时间戳与本地时间的偏差 > N 秒时应告警（云端时钟可能不同步） |

---

### A1-03：周期性数据处理逻辑验证

**测试目标**：验证各 topic 的消息按期望频率发布，无异常抖动或丢帧。

**C++ 现状**：
- 所有 4 个模块实现了 `periodic_task` / `periodic_tasks` 方法，带漂移补偿
- Gateway: 1s/10s/5s 周期任务
- Planning: 100ms 规划周期
- Control: 20ms 控制周期
- CAN Transformer: 20ms 发布周期
- 漂移补偿：当任务执行时间超过周期时，`last_time` 重置为 `now` 并打印警告
- **无序列号、无丢帧检测、无抖动统计**

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-03-C1 | 消息序列号 | 各模块 DDS publisher | 每条消息携带 per-topic 单调递增的序列号，供订阅者检测丢帧 |
| A1-03-C2 | 丢帧检测 | 各 DDS 回调 | 订阅者收到消息后比较当前 seq 与上次 seq，差值 > 1 表示丢帧 |
| A1-03-C3 | 频率抖动统计 | 全局日志/监控 | 周期性记录各 topic 的实际发布频率、最大抖动、丢帧累计数 |
| A1-03-C4 | 超期执行告警 | 现有 `periodic_task` | 现有漂移补偿只打印日志，应改为结构化告警（上报到监控系统） |

---

### A1-04：延迟检测计算逻辑与上报完整性验证

**测试目标**：测量模块间数据传输的端到端延迟，超过阈值时触发告警。

**C++ 现状**：
- Planning 有超时检测：`business_decision.cc:126-154`，`judgeOverTime()` 检查底盘/定位/感知数据是否在 500ms 内到达
- **Control 有 bug**：`hv_controller.cc:115` 无条件设置 `pre_frame.is_overtime = true`，第 112 行的超时判断结果被忽略
- **无端到端延迟测量**：无 publisher 端时间戳 → subscriber 端时间戳的差异计算
- 延迟上报不存在

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-04-C1 | 端到端延迟测量 | 各 DDS publisher + subscriber | Publisher 在消息中写入 `publish_timestamp`，Subscriber 收到后用 `now - publish_timestamp` 计算延迟 |
| A1-04-C2 | **Control 超时 bug 修复** | `hv_controller.cc:115` | `pre_frame.is_overtime = true` 应改为 `pre_frame.is_overtime = (条件判断结果)` |
| A1-04-C3 | 延迟阈值告警 | 全局 | 各 topic 定义可配置的延迟阈值（如 Localization < 50ms），超阈值时上报 |
| A1-04-C4 | MQTT RTT 测量 | `gateway.cc` / `mqtt_protobuf_client.cc` | 发送上行消息到收到下行应答的往返时间 |
| A1-04-C5 | 延迟统计上报 | `gateway.cc` 上行报告 | 将端到端延迟统计纳入周期性上行报告，供云端监控 |

---

### A1-05：故障处理动作执行正确性验证

**测试目标**：验证超时→停车→上报的故障处理链完整执行。

**C++ 现状**：
- 超时检测存在（A1-04 中所述）
- `_judge_stop` 在超时时设置 `frame.stop = true` （business_decision.cc:202）
- Planning 在 `frame.stop` 为 true 时发布 `DRIVE_OFF` 命令（planning.cc:161-171）
- **无故障诊断码（DTC）**、**无故障上报链路**、**无故障恢复逻辑**

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-05-C1 | 故障诊断码（DTC）定义 | 全局 | 定义超时、丢帧、参考线无效等故障对应的 DTC |
| A1-05-C2 | 故障上报链路 | `gateway.cc` 上行报告 | 将当前 DTC 状态纳入 StopObstacleInfo 或 TruckPositionReport 上行 |
| A1-05-C3 | 故障恢复检测 | `business_decision.cc` | 超时恢复后（数据重新到达），应清除 DTC 并上报恢复事件 |
| A1-05-C4 | 故障分级处理 | `planning.cc` | 区分可恢复故障（如短暂超时）vs 不可恢复故障（如参考线永久丢失） |

---

### A1-06：参考线航向角跳变时的异常检测

**测试目标**：检测相邻轨迹点航向角跳变 > 10°，触发报警并过滤，保证轨迹无突变。

**C++ 现状**：
- 航向角从 `.traj` 中解析（`traj_parser.cc:61`），存储在每个轨迹点的 `heading` 字段
- 航向角用于控制计算（Pure Pursuit、Stanley、DWA）和停车位姿设置
- **无航向角跳变检测**：全代码库无 `abs(heading[i] - heading[i-1]) > threshold` 类检测逻辑
- **无航向角规范化**：解析后未将航向角归一化到 $[-\pi, \pi]$ 或 $[0, 2\pi)$ 范围
- **无跳变告警**：检测到航向异常后无上报机制
- B 样条平滑器（`b_spline_smoother.cc`）仅平滑 XY 空间坐标，不涉及航向角处理

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-06-C1 | 航向跳变检测 | `traj_parser.cc` 或 `business.cc` | 参考线加载时检查相邻点航向差 > 10°（v0.3 阈值），标记异常点 |
| A1-06-C2 | 航向角规范化 | `traj_parser.cc` | 确保解析后的航向角在 $[-\pi, \pi]$ 范围内，消除角度环绕导致的误检 |
| A1-06-C3 | 航向跳变告警 | `planning.cc` | 检测到航向跳变后上报异常事件日志 |
| A1-06-C4 | 异常航向过滤/平滑 | `b_spline_smoother.cc` 或 `business.cc` | 对航向异常点进行过滤或插值修正，保证输出轨迹航向连续 |

---

### A1-07：参考线起点距车辆过远时的重规划

**测试目标**（v0.3）：验证车辆到参考线起点距离 ≤ 3m 时可成功规划，> 3m 时触发重规划或拒绝。v0.3 将阈值从 2m 提升到 3m。

**C++ 现状**：
- `business_decision.cc:22-31`：收到新任务时计算车辆到轨迹最近点距离
- 若 > **2m**（v0.2 旧阈值），记录错误 `"下发路径与车辆位置偏远，轨迹无效！"` 并**跳过更新参考线**
- **阈值需更新到 3m** 以匹配 v0.3 要求
- **无重规划**——系统只是拒绝无效轨迹，不会主动请求新的
- **无上报通知云端**轨迹无效

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| A1-07-C1 | 阈值更新 2m → 3m | `business_decision.cc` | 将邻近校验阈值从 2m 更新为 3m，匹配 v0.3 要求 |
| A1-07-C2 | 重规划请求 | `gateway.cc` | 参考线被拒绝后，向云端请求重新下发任务（包含当前车辆位置） |
| A1-07-C3 | 轨迹无效上报 | `gateway.cc` 上行报告 | 将"轨迹无效"事件通过上行消息通知云端 |
| A1-07-C4 | 距离阈值配置化 | `planning_config.ini` | 阈值应可配置（不同矿卡车型、不同场景可能需要不同阈值） |

---

## B 类：车云通信协议功能缺失

> 核验方法：对照车云协议文档，逐字段审查 C++ gateway.cc 上报消息构造逻辑。
> Python 端对照：`sim_platform/gateway_sim/gateway_sim.py` 上行报告已实现动态值。

### B-01：实时定位数据上行（TruckPositionReport / TruckSateReport / TruckMonitorReport）

**发现**：三个周期性上行报告中，位置经纬度和航向角来自 `simulationData()` 方法的**硬编码 GPS 坐标点**，不是来自 DDS 定位订阅的实际数据。

**根因**：DDS localization 订阅 `sub_localization_` 的回调被**错误绑定到 `subChassis` 函数**（Bug D-01）。正确的 `subLocalization` 函数（gateway.cc:775-778）是死代码，从未被注册为回调。

**硬编码值清单**：

| 报告 | 字段 | 硬编码值 | 来源 |
|------|------|---------|------|
| TruckPositionReport | longitude, latitude | 5 个硬编码 GPS 点循环 | `simulationData()` (gateway.cc:742-765) |
| TruckPositionReport | direction (heading) | 110.0° | `simulationData()` |
| TruckPositionReport | altitude | 0.0 | 硬编码 |
| TruckPositionReport | speed | 0.0 | 硬编码 |
| TruckPositionReport | forwardAcceleration | 0.0 | 硬编码 |
| TruckPositionReport | lateralAcceleration | 0.0 | 硬编码 |
| TruckPositionReport | yawAngularAcceleration | 0.0 | 硬编码 |
| TruckPositionReport | pointIndex | 0 | 硬编码 |
| TruckPositionReport | roadResidualDistance | 0.0 | 硬编码 |
| TruckMonitorReport | speed | 12.5 | 硬编码 |
| TruckMonitorReport | lateralError | 0.15 | 硬编码 |
| TruckMonitorReport | spin (发动机转速) | 1500.0 | 硬编码 |
| TruckMonitorReport | throttleOpenAuto | 30.0 | 硬编码 |
| TruckMonitorReport | brakeOpenAuto | 0.0 | 硬编码 |
| TruckMonitorReport | brakeOpenManual | 10.0 | 硬编码 |
| TruckMonitorReport | limitSpeed | 20.0 | 硬编码 |
| TruckSateReport | frontWheelDirection | 15.5° | 硬编码 |
| TruckSateReport | frontWheelAngularError | 0.2° | 硬编码 |
| TruckSateReport | oilPressure | 450.0 | 硬编码 |
| TruckSateReport | coolantTemperature | 85.5 | 硬编码 |
| TruckSateReport | batteryVoltage | 27.6 | 硬编码 |
| TruckSateReport | fuelLevel | 65.0 | 硬编码 |
| TruckSateReport | mileage | 12345.6 | 硬编码 |
| TruckSateReport | liftAngle | 0.0 | 硬编码 |

**Python 端对照**：`gateway_sim.py` 的 `_publish_position_report()` 从 `self._latest_localization`（由 SimMessageBus `Localization` topic 实时推送）获取位置/速度/航向，从 `self._latest_chassis` 获取底盘数据，动态填充上报字段。**Python 端已实现，C++ 端需同步实现。**

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| B-01-C1 | **修复 DDS localization 订阅回调绑定** | `gateway.cc:199-201` | `sub_localization_` 回调应从 `subChassis` 改为 `subLocalization`（同 Bug D-01） |
| B-01-C2 | 使用 real-time localization 填充上报位置 | `gateway.cc` 三个上报函数 | 从 `localization_` protobuf 成员读取 lat/lon/altitude/speed/heading，替代 `simulationData()` 的硬编码值 |
| B-01-C3 | 使用 real-time chassis 填充车辆状态 | `gateway.cc` 三个上报函数 | 从 `chassis_` protobuf 成员读取 engine_rpm/oil_pressure/coolant_temp/battery_voltage/mileage 等字段 |
| B-01-C4 | 移除 `simulationData()` 线程 | `gateway.cc:111-114, 742-765` | 该线程仅为测试提供假 GPS 数据，功能完成后应移除或改为条件编译 |

---

### B-02：高精地图匹配——根据 GPS 坐标查找当前道路 ID

**发现**：`TruckPositionReport.roadId` 硬编码为 `7`。C++ 代码中**没有任何地图匹配逻辑**——无 SQLite 访问、无 HDMap 查询、无 GPS→lane 最近邻查找。

**Python 端对照**：`sim_platform/gateway_sim/hdmap_matcher.py` 已实现完整的高精地图匹配器：
- 加载 SQLite `.db` 地图数据库（从云端下载）
- 查询 `HDMAP_LANE` 表获取车道轨迹点（WKT 格式）
- 回退到 `HDMAP_LANENODE` 节点数据
- 对 `(lat, lon)` 做最近邻搜索返回 `lane_id`
- 无地图文件时返回 0

C++ 端 `DealServerParamsQueryResponse`（gateway.cc:651-682）已下载地图文件，但**下载后直接丢弃，从未加载或使用**。

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| B-02-C1 | SQLite3 地图数据库加载 | `gateway/src/` 新增文件 | 参照 Python `hdmap_matcher.py`，实现 `HdMapMatcher` 类 |
| B-02-C2 | GPS 坐标→车道 ID 最近邻匹配 | `gateway/src/hdmap_matcher.h/cc` | 解析 WKT 格式的 `HDMAP_LANE.trajectory`，对 `(lon, lat)` 做欧氏距离最近邻搜索 |
| B-02-C3 | 匹配结果接入上行报告 | `gateway.cc:sendVehiclePositionToCloud` | 将 `msg.set_roadid(7)` 改为 `msg.set_roadid(matcher_.find_lane_id(lat, lon))` |
| B-02-C4 | 地图文件下载后自动加载 | `gateway.cc:DealServerParamsQueryResponse` | 下载地图文件后调用 `HdMapMatcher` 加载，而非丢弃 |

---

### B-03：停车原因上报——根据车云协议计算 20-bit 位图

**发现**：`TruckPositionReport` 中的 `reasonCode`、`runState`、`stopReason` 全部硬编码为 `0`。`sendVehiclePositionToCloud()` 可以访问 `chassis_` 成员（通过 `subChassis` DDS 回调填充），但**从不读取**。没有函数解析车辆实际状态来计算停车原因。

车云协议定义了 20-bit 的 `stopReason` 位图（协议 Table[13]），每 bit 对应一种停车原因。Python 端已实现完整的位图计算逻辑。

**Python 端对照**：`gateway_sim.py` 的 `STOP_REASON_BIT` 字典定义了 20 个停车原因位：
```python
STOP_REASON_BIT = {
    "heartbeat_loss": 0, "localization_loss": 1, "perception_loss": 2,
    "planning_fail": 3, "control_fail": 4, "obstacle_stop": 5,
    "endpoint_stop": 6, "authority_stop": 7, "emergency_stop": 8, ...
}
```

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| B-03-C1 | 停车原因位图计算函数 | `gateway.cc` 新增函数 | 读取 `chassis_`（档位/制动）、`localization_`（定位状态）、`task_status_`，按协议位定义计算 20-bit stopReason |
| B-03-C2 | 故障原因码（reasonCode）计算 | `gateway.cc` 新增函数 | 根据当前活跃的故障类型映射到协议定义的 reasonCode 枚举值 |
| B-03-C3 | 运行状态（runState）计算 | `gateway.cc` | 根据任务状态和车辆运动状态判断：0=待命，1=运行中 |
| B-03-C4 | 停车原因接入上行报告 | `gateway.cc:sendVehiclePositionToCloud` | 将 `msg.set_stopreason(0)` 改为动态计算值 |

---

### B-04：驾驶模式上报（operationType + StatusType）

**发现**：`TruckPositionReport` 中 `operationType` 硬编码为 `0`，`StatusType` 子消息设置为空的默认实例。没有逻辑从实际驾驶模式（自动驾驶/人工驾驶/远程接管）中读取状态。

**Python 端对照**：`gateway_sim.py` 的 `_publish_position_report()` 根据控制模式设置 `operationType=1`（自动驾驶），`StatusType` 包含 driving_mode、acc_state、gps_state、gear、brake、lock、emergency_brake、load_state 等 28 位状态字。

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| B-04-C1 | StatusType 28 位状态字构造 | `gateway.cc` 新增函数 | 读取 `chassis_` 和 `localization_`，按协议定义填充 StatusType 的 28 个位字段 |
| B-04-C2 | operationType 驾驶模式判断 | `gateway.cc` | 根据控制模式（0=人工，1=自动驾驶，2=远程接管）设置 operationType |
| B-04-C3 | StatusType 接入上行报告 | `gateway.cc:sendVehiclePositionToCloud` | 将空 `StatusType` 替换为实际构造的状态字 |

---

### B-05：actionStatus / actionType 上报动态化

**发现**：`TruckPositionReport` 中 `actionType` 和 `actionStatus` 硬编码为 `0`。C++ 代码中没有从 BusinessDecision 读取当前 action 执行状态的逻辑。车云协议定义 `actionStatus` 为：0=executing, 1=pause, 2=complete。当每个 action 完成时，应上报 `actionStatus=2` 和已完成 action 的 `actionType`。

**Python 端对照**：已实现完整链路（2026-06-01 更新）：

- `BusinessDecision.proc()` [`planning_sim/business_decision.py`] — `_current_task_finish()` 返回 True 时设置 `frame.action_status=2`，否则 `status=0`；同步设置 `frame.action_type` 为当前/已完成 action 类型
- `PlanningResult` [`models/sim_messages.py`] — 新增 `action_type: int` 和 `action_status: int` 字段
- `GatewaySim._on_planning_result()` [`gateway_sim/gateway_sim.py`] — 订阅 `PLANNING_RESULT` topic，latch `status=2` 确保 10Hz 规划产生的完成信号不被 1Hz 位置上报错过
- `GatewaySim._publish_position_report()` — 动态填充 `actionType` 和 `actionStatus`

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| B-05-C1 | BusinessDecision 输出 action 状态 | `business_decision.cc` | `proc()` 中：`_current_task_finish()` 返回 True 时设 `frame.action_status=2`，否则 `status=0` |
| B-05-C2 | PlanningResult 扩展 action 字段 | `planning.cc` / DDS IDL | `PlanningResult` 消息新增 `action_type` 和 `action_status` 字段 |
| B-05-C3 | Gateway 读取 action 状态并 latch | `gateway.cc` | 订阅 PlanningResult，latch `status=2` 确保完成信号被至少一次位置上报捕获 |
| B-05-C4 | actionStatus/actionType 接入上行报告 | `gateway.cc:sendVehiclePositionToCloud` | 将 `actionType=0, actionStatus=0` 改为动态计算值 |

---

## C 类：规划管线功能缺失

### C-01：路径平滑器（B 样条）未集成到规划管线

**发现**：`BSplineSmoother` 类已经在 `planning/src/smooth/b_spline_smoother.h/cc` 中**完整实现**——包含经纬度→XY 坐标转换、三次 B 样条基函数计算、固定步长（0.2m）重采样。但该平滑器**从未在规划管线中被实例化或调用**：

- `planning.cc` 的 `init()` 仅创建 `RTKPlanner`，不创建平滑器
- `mainProc()` 的流程是 `BussinessDecision::proc → RTKPlanner::planning → publishMsg`，**无平滑步骤**
- 全代码库中 `BSplineSmoother` 或 `Smoother` 只在定义文件中出现，零处调用

**Python 端对照**：`planning_sim/planning_sim.py` 在 `_handle_new_task` 中会对参考线进行 B 样条平滑，将平滑后的轨迹用于规划。**Python 端已集成，C++ 端平滑器存在但未接入管线。**

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| C-01-C1 | 在 `init()` 中创建 BSplineSmoother 实例 | `planning.cc:init()` | `smoother_ = new BSplineSmoother();` |
| C-01-C2 | 在 `mainProc()` 中调用平滑 | `planning.cc:mainProc()` | 在 `bussiness_decision.proc(frame)` 之前或之后，对参考线进行平滑：`smoother_->smooth(reference_line)` |
| C-01-C3 | 平滑后的轨迹传给规划器 | `planning.cc` | 确保 `RTKPlanner::planning(frame)` 使用的 reference_line 是平滑后的版本 |

---

### C-02：空端点路权（MA）容错 — 防止车辆被"假停车指令"锁死

**问题描述**（通俗版）：云端在没有任务时会先发一条"停车"指令（`endPoint` 为空，附带信息"车辆无任务"），程序收到后把允许行驶的终点锁在起点位置。等云端真正分配任务、下发有效路权终点后，程序的安全机制要求"终点只能缩小不能扩大"，导致有效终点被忽略，车辆永远停在原地。

**技术细节**：云端下发的 `MovemntAuthoritySend` 中 `safeOccupied.endPoint` 为空时（`lat=0, lon=0`），查找参考线上离 `(0,0)` 最近的点 → 索引为 0。min-tracking 机制执行 `stop_index = min(stop_index, autor_index)` 后 `stop_index` 变为 0，VelocityPlanner 将所有轨迹点速度置零。后续即使收到有效路权（endPoint 坐标 = 轨迹终点），`min(0, 1894) = 0` 导致无法恢复。

**Python 端对照**：已实现容错（2026-06-01 更新）：

- [x]空 endpoint 守卫：`endPoint` 为 `(0,0)` 时视为无效指令，跳过不处理
- [x]空 MA 诊断日志：打印云端下发的具体原因（`safe.info`），便于排查
- [x]修复 endpoint fallback 的真值判断 bug（Python 中 `0.0` 是 falsy，导致空值错误回退到另一个同样为 0 的备用值）

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| C-02-C1 | 空端点 MA 守卫 | `business_decision.cc:updateStopFromAuthority` | `endPoint` 为 `(0,0)` 时识别为无效路权指令，不更新 `stop_index` |
| C-02-C2 | 空 MA 诊断日志 | `gateway.cc:DealMovemntAuthoritySend` | 收到空路权时输出 WARNING 日志，打印云端附带的原因信息 |
| C-02-C3 | endpoint fallback 健壮性 | `gateway.cc:DealMovemntAuthoritySend` | `end_pt.lat == 0` 时不应 fallback 到 `list[-1].lat`（同样为 0），应保持为 0 让下游识别 |

---

### C-03：B 样条平滑后未从几何重算 heading/theta（A1-06 关联）

**发现**：`BSplineSmoother::smooth()`（`b_spline_smoother.cc:42-57`）和 Python 端 `BSplineSmoother.smooth()`（`b_spline_smoother.py:46-70`）在平滑后构造输出点时，通过 `CopyFrom(input_points[i])` 或 `_find_nearest_point()` 从原始点**原样复制** `heading` 和 `theta` 字段。但平滑改变了 XY 空间位置，从新几何推导出的航向角已经发生变化——旧 heading 值与平滑后的轨迹方向不一致。

**后果**：A1-06 航向跳变检测即使对平滑后的轨迹执行，仍会检出原始轨迹的航向异常（因为 heading 值未更新）。平滑可以消除空间上的尖角，但 heading 字段中的跳变被保留下来，造成"轨迹已平滑但航向仍跳变"的不一致状态。

**Python 端对照**：已修复（2026-06-02）。在 `b_spline_smoother.py` 平滑管线末尾，从平滑后的 XY 几何用中心差分重算每个点的 `theta` 和 `heading`：
- 内部点：`dx = pts[i+1].x - pts[i-1].x`，`theta = atan2(dy, dx)`
- 首点：前向差分
- 尾点：后向差分
- `heading` 由 `theta` 推导：`heading = 90° - theta_deg`，归一化到 `[0, 360)`

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| C-03-C1 | 平滑后从 XY 几何重算 theta | `b_spline_smoother.cc:smooth()` | 在重采样输出点后，用中心差分 `atan2(dy, dx)` 计算每个点的 theta，替代从原始点复制的旧值 |
| C-03-C2 | theta → heading 转换 | `b_spline_smoother.cc:smooth()` | 由 theta(math 弧度) 推导 heading(地理度)：`heading = 90° - theta_deg`，归一化到 [0, 360) |
| C-03-C3 | 首尾点边界处理 | `b_spline_smoother.cc:smooth()` | 首点用前向差分 (pts[1]-pts[0])，尾点用后向差分 (pts[-1]-pts[-2]) |

---

## D 类：已确认的 C++ Bug（阻塞性）

| Bug 编号 | 位置 | 描述 | 影响范围 |
|----------|------|------|---------|
| D-01 | `gateway.cc:199-201` | `sub_localization_` 的回调被错误绑定到 `subChassis`。正确的 `subLocalization` 函数（line 775-778）从未被注册。**定位数据被当作 `canbus::Chassis` 反序列化，静默失败** | B-01 (定位上报), A1-01 (路由), A1-02 (时间戳) |
| D-02 | `flag_set.h:4` + `business.cc` | `ref_line_valid` 初始化为 `false`，从未被设置为 `true`。`RTKPlanner::planning` 中的参考线有效性检查（`!frame.flags.ref_line_valid`）被绕过，导致规划器实际上永远返回 false | 规划器有效性判断（该用例已在 v0.3 中移除） |
| D-03 | `hv_controller.cc:115` | `pre_frame.is_overtime = true` 无条件赋值，与第 110-113 行的超时判断结果无关。超时检测逻辑完全失效 | A1-04 (延迟检测), A1-05 (故障处理) |

---

## 汇总

```
总计缺失项: 63 项 (+ 3 个阻塞性 Bug)

A 类 — A1 测试用例数据验证功能缺失 (32 项):
├── A1-01 路由验证:         6 项
├── A1-02 时间戳验证:       5 项
├── A1-03 周期处理:         4 项
├── A1-04 延迟检测:         5 项
├── A1-05 故障处理:         4 项
├── A1-06 航向跳变:         4 项
└── A1-07 起点距离:         4 项

B 类 — 车云通信协议功能缺失 (19 项):
├── B-01 实时定位数据上行:    4 项
├── B-02 高精地图匹配:       4 项
├── B-03 停车原因计算上报:    4 项
├── B-04 驾驶模式上报:       3 项
└── B-05 actionStatus 上报:  4 项    ← 2026-06-01 新增

C 类 — 规划管线功能缺失 (12 项):
├── C-01 B样条平滑器集成:     3 项
├── C-02 空端点 MA 容错:      3 项    ← 2026-06-01 新增 (Python 端已修复)
└── C-03 平滑后heading重算:    3 项    ← 2026-06-02 新增 (Python 端已修复, A1-06 关联)

D 类 — 阻塞性 Bug (3 项):
├── D-01 localization 回调绑定错误 (严重)
├── D-02 ref_line_valid 永为 false (中等)
└── D-03 is_overtime 无条件 true (中等)
```

### Python 端已实现、C++ 端需同步的能力

| Python 端已实现 | C++ 端状态 | 涉及缺失项 |
|---------------|-----------|-----------|
| HDMap 地图匹配 (`hdmap_matcher.py`) | 无任何地图匹配代码 | B-02-C1~C4 |
| 动态定位数据上报 (gateway_sim.py) | 使用硬编码 GPS 模拟数据 | B-01-C1~C4 |
| 停车原因 20-bit 位图计算 | 全部硬编码为 0 | B-03-C1~C4 |
| driving mode 上报 | 空默认实例 | B-04-C1~C3 |
| actionStatus/actionType 动态上报 | 硬编码为 0 | B-05-C1~C4 ← **2026-06-01 新增** |
| B 样条路径平滑集成 | 完整实现但未接入管线 | C-01-C1~C3 |
| 鉴权成功后未发路权，导致路权终点空置所死 | 无守卫，stop_index 一旦为 0 无法恢复 | C-02-C1~C3 |
| B样条平滑后 heading 重算 | 原样复制旧 heading，平滑后几何与航向不一致 | C-03-C1~C3 ← **2026-06-02 新增** |
| A1 数据质量验证层 | 完全不存在 | A 类全部 32 项 |
