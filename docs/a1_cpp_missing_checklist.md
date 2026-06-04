# C++ 代码工程功能开发 — 缺失项清单

> 版本：V3.5
> 日期：2026-06-04
> 编制依据：C++ 源码审查 (gateway/ planning/ control/ can_transformer) 对照仿真 Python 端
> 状态：持续更新

---

## 文档说明

本文档统计 C++ 工程代码中，对照 Python 仿真端已实现的功能，需在 C++ 端对应补充的缺失项，按模块分类：

- **B 类**：车云通信协议功能缺失
- **C 类**：规划管线功能缺失
- **D 类**：已确认的 C++ Bug

每项标注对应模块、Python 端现状、以及影响范围。

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

### C-02：路权（MA）端点处理与停车逻辑

**问题描述**（通俗版）：云端未发路权或发了空路权（"车辆无任务"、"车道非调度路径"）时，车辆应该停车等待，而不是自由行驶。等云端下发有效路权后，车辆再按路权终点行驶。

**技术细节**：`updateStopFromAuthority` 中，无 MA（`ma is None`）或 `endPoint` 为空（`lat=0, lon=0`）时，`autor_index` 直接置 0，min-tracking 将 `stop_index` 拉到 0，车辆停车。有效 MA 到达后，`autor_index > old_stop(0)` 触发扩展重置 → `stop_index` 更新为正确的路权值，车辆放行。云端下发有效 MA 后又发空 MA → 再次停车，再发有效 → 再走。

**Python 端对照**：已实现（2026-06-04 更新）：

- [x]无 MA 或空 endpoint → `autor_index=0` → stop_index=0 → 停车
- [x]有效 MA 到达 → autor_index > 0 → 扩展重置 sentinel → stop_index 更新 → 车辆放行
- [x]空 MA 诊断日志：打印云端下发原因（`safe.info`），便于排查
- [x]端点来源优先级：云端 `pointIndex` > GPS 全段匹配

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| C-02-C1 | 无 MA / 空 endpoint → 停车 | `business_decision.cc:updateStopFromAuthority` | `ma is None` 或 `endPoint=(0,0)` 时 `autor_index=0`，min-tracking 后 `stop_index=0` |
| C-02-C2 | 有效 MA 到达 → 放行 | `business_decision.cc:updateStopFromAuthority` | `autor_index > old_stop` 时重置 sentinel，允许扩大 |
| C-02-C3 | 空 MA 诊断日志 | `gateway.cc:DealMovemntAuthoritySend` | 收到空路权时输出 WARNING 日志，打印云端附带的原因信息 |

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

### C-04：Planning 未读取曲率数据 — A2-02 曲率约束校验缺失

**发现**：Gateway `traj_parser.cc:82` 已解析 `.traj` 第 13 列曲率并存入 protobuf `TaskTrajInfo.curvature`，但 Planning 管线完全未使用：

- `RoadPoint`（`road_point.h:6-18`）**无 curvature 字段**
- `Tool::TransTaskTrajToRoadPoint`（`tool.cc:68-82`）转换时**未拷贝 curvature**
- Planning 全模块（`rtk_planner`, `velocity_planner`, `business_decision`）**0 处 curvature 引用**

**影响**：A2-02（P0 安全关键）要求"路径曲率满足车辆动力学约束（转弯半径 ≥ 15m）"，当前 C++ 域控完全无法校验。曲率数据从解析到规划的数据流已断裂。

**Python 端对照**：`TrajPoint` 有 `curvature` 字段且 `traj_parser.py:114` 正确解析，但 Planning 管线同样不读曲率。仿真端也未实现 A2-02 曲率约束校验。

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| C-04-C1 | RoadPoint 增加 curvature 字段 | `road_point.h` | 新增 `double curvature = 0.0` 成员 |
| C-04-C2 | TransTaskTrajToRoadPoint 拷贝曲率 | `tool.cc` | `road_point.curvature = info.curvature()` |
| C-04-C3 | A2-02 曲率约束校验 | `planning.cc` 或新增 | 遍历规划路径点，检查 `\|κ\| ≤ 1/R_min`（R_min=15m），超限则告警/拒绝 |
| C-04-C4 | 曲率约束阈值配置化 | `planning_config.ini` | `min_turn_radius = 15.0` 可配置 |

---

### C-05：参考线行驶方向映射与段切换（前进↔倒车）未实现

**发现**：参考线按 `is_reverse` 标志拆分为多段，`advanceToNext()` 方法已定义但从未被调用。车辆永远停在第一段末尾，无法切入倒车段。`is_reverse` 到 `direction` 的映射关系未明确（数据约定：`is_reverse=True`(1)→前进，`is_reverse=False`(0)→倒车），`direction` 未与档位联动。

**Python 端对照**：已实现（2026-06-04 更新）：

- `update_from_task()` — 映射：`is_reverse=True→direction=1(前进)`, `is_reverse=False→direction=0(倒车)`
- `BusinessDecision._check_segment_advance()` — 精简版：车到当前段末尾（`key_index ≥ end_index-3`）且 STOP 目标在下一段时切段
- `FullStackEngine.step()` — 档位联动：无任务/任务完成→P 档，`direction=1→D`档，`direction=0→R`档
- `kinematics.step()` — P 档强制速度为零，R 档时目标速度取负实现倒车

**缺失项**：

| 编号 | 缺失项 | 位置 | 说明 |
|------|--------|------|------|
| C-05-C1 | is_reverse→direction 映射 | `reference_line_mgr` | `is_reverse=True→direction=1(前进)`, `is_reverse=False→direction=0(倒车)` |
| C-05-C2 | direction→档位联动 | `planning.cc` 或 `control.cc` | 无任务/任务完成→P 档，direction=1→D 档，direction=0→R 档 |
| C-05-C3 | 参考线段切换判定 | `business_decision.cc` | 车到段尾且 STOP 目标在下一段时调用 `advanceToNext()` 切段 |

---

## D 类：已确认的 C++ Bug（阻塞性）

| Bug 编号 | 位置 | 描述 | 影响范围 |
|----------|------|------|---------|
| D-01 | `gateway.cc:199-201` | `sub_localization_` 的回调被错误绑定到 `subChassis`。正确的 `subLocalization` 函数（line 775-778）从未被注册。**定位数据被当作 `canbus::Chassis` 反序列化，静默失败** | B-01 (定位上报), A1-01 (路由), A1-02 (时间戳) |
| D-02 | `flag_set.h:4` + `business.cc` | `ref_line_valid` 初始化为 `false`，从未被设置为 `true`。`RTKPlanner::planning` 中的参考线有效性检查（`!frame.flags.ref_line_valid`）被绕过，导致规划器实际上永远返回 false | 规划器有效性判断（该用例已在 v0.3 中移除） |
| D-03 | `hv_controller.cc:115` | `pre_frame.is_overtime = true` 无条件赋值，与第 110-113 行的超时判断结果无关。超时检测逻辑完全失效 | A1-04 (延迟检测), A1-05 (故障处理) |

---

## E 类：Python 仿真端已修复 Bug（C++ 实现时需规避）

> 以下 Bug 在 Python 仿真端发现并已修复（2026-06-04）。C++ 端实现对应功能时需注意规避相同问题。

### E-01：RTKPlanner 全局索引当作段内局部索引使用

**发现位置**：`sim_platform/planning_sim/rtk_planner.py:53-60`

**问题**：`BusinessDecision._update_key_index()` 产出的是全局索引（在整个 task_trajectory 中搜索最近点），但 `RTKPlanner.plan()` 将它当作当前段内的局部索引使用：`pts[key_index]` 和 `range(key_index, len(pts))`。当车辆切换到第二段（倒车段）后，`key_index` 可能远超 `len(current_segment.points)`，导致 `run_road` 为空循环，规划返回空，`_planning_traj` 无法更新。

**现象**：车辆在前进段末尾正常行驶，段切换后 RTKPlanner 返回 `[]`，planning 返回 None，`_planning_traj` 保持前进段旧值，车辆用错误的旧轨迹继续行驶。多段轨迹（前进+倒车）必定触发。

**根因**：`find_closest_index()` 在全局点序列中搜索返回全局索引，但 `RTKPlanner` 只拿到 `ref_mgr.current`（当前段子集），索引坐标系不一致。

**修复**（`planning_sim.py:205-228`）：在 `PlanningSim.plan()` 中将全局索引转换为段内局部索引后再传入 `RTKPlanner.plan()`：
```python
seg_start = ref_line.start_index
local_key = frame.key_index - seg_start
local_stop = self._ref_mgr.stop_index - seg_start  # sentinel 10^9 保持不动
# ... RTKPlanner.plan(key_index=local_key, stop_index=local_stop)
# 结果写回: self._ref_mgr.stop_index = updated_stop + seg_start
```

**C++ 端影响**：实现 C-05（前进倒车方向切换）时，务必确保 `key_index` 与 `current_reference_line` 的索引坐标系一致。建议参照 Python 修复方案，在 planning 入口处做全局→局部索引转换。

---

### E-02：PurePursuitController 倒车时转向角符号未取反

**发现位置**：`sim_platform/core/controller.py:97-100`

**问题**：Pure Pursuit 公式 `δ = atan(2L·sinα/ld)` 是在**前向行驶**假设下推导的——δ 的正负与后轴横移方向一致。倒车时运动学发生反转：δ>0 使后轴右移（而非左移），导致车辆转向背离目标点。

**几何推演**：车辆倒车，目标在运动方向左侧。sinα>0 → steer>0（左转）。运动学：v<0, steer>0 → yaw_rate = v·tan(δ)/L < 0 → 车头 CW 旋转 → 后轴右移远离目标。应是 steer<0（右转）→ 后轴左移靠近目标。

**修复**（`controller.py:101-103`）：倒车时对 Pure Pursuit 输出取反：
```python
if reverse:
    steer_rad = -steer_rad
```

**C++ 端影响**：实现 C-05-C2（direction→档位联动）时，C++ `pure_pursuit_controller` 同样需要感知行驶方向。当前 C++ 控制器接口无 `reverse` 参数，倒车横向控制必然发散。

---

### E-03：PurePursuitController 倒车时坐标变换未使用运动方向

**发现位置**：`sim_platform/core/controller.py:80-88`

**问题**：倒车时 `motion_theta = state.theta + π`。若用 `state.theta`（车头朝向）做坐标变换，"前方"是车头方向而非实际运动方向，计算出的 `local_y` 符号与物理含义相反（目标在运动方向左侧却被判为右侧）。

**修复**（`controller.py:82`）：倒车时用 `motion_theta = state.theta + math.pi` 做坐标变换，确保 `local_y` 的符号表示"偏离运动纵轴的方向"（正=运动方向左侧）。

**注意**：此修复与 E-02 存在数学等价关系——`motion_theta` 旋转 180° 使 `local_y` 反号，再对 steer 取反，**净效果与不旋转+不取反相同**。但方案 A（当前实现）的好处是 `cross_track_error = local_y` 基于运动方向，物理语义清晰，正确反映到 DataLogger 和 UI 显示。

**C++ 端影响**：C++ 控制器实现倒车支持时，两种等价方案择一即可。推荐方案 A（motion_theta 变换 + steer 取反），与 Python 端保持一致。

---

### E-04：planning 返回 None 时 FullStackEngine 保留旧轨迹

**发现位置**：`sim_platform/core/full_stack_engine.py:362-364`

**问题**：`planning.plan()` 返回 None 时，`_planning_traj` 未被更新——保留了上一次成功规划周期的轨迹。当段切换瞬间 plan() 返回 None（因 E-01 索引越界），控制器拿着前进段旧轨迹在倒车段上跑。

**现象**：前进段直线轨迹与倒车段起点共线时，`cross_track_error` 恒为 0，车辆沿直线倒退出道路。若轨迹不共线，车辆朝错误方向转向。

**修复**（`full_stack_engine.py:384-387`）：连续 3 次 planning 返回 None → 设置 `_planning_traj = None` → 档位逻辑检测到无轨迹 → 挂 P 档安全停车。

**C++ 端影响**：C++ `planning.cc:mainProc()` 返回空轨迹时，`control.cc` 应挂 P 档停车，而非使用上一个周期的旧 Command。


## 汇总

```
总计缺失项: 42 项 (+ 3 个阻塞性 Bug + 4 个 Python 端已修复 Bug)


B 类 — 车云通信协议功能缺失 (19 项):
├── B-01 实时定位数据上行:    4 项
├── B-02 高精地图匹配:       4 项
├── B-03 停车原因计算上报:    4 项
├── B-04 驾驶模式上报:       3 项
└── B-05 actionStatus 上报:  4 项    ← 2026-06-01 新增

C 类 — 规划管线功能缺失 (19 项):
├── C-01 B样条平滑器集成:     3 项
├── C-02 空端点 MA 容错:      3 项
├── C-03 平滑后heading重算:    3 项
├── C-04 曲率数据未读取:       4 项
└── C-05 前进倒车方向切换:     3 项    ← 2026-06-03 新增 (Python 端已实现)

D 类 — 阻塞性 Bug (3 项):
├── D-01 localization 回调绑定错误 (严重)
├── D-02 ref_line_valid 永为 false (中等)
└── D-03 is_overtime 无条件 true (中等)

E 类 — Python 端已修复 Bug, C++ 实现需规避 (4 项):    ← 2026-06-04 新增
├── E-01 RTKPlanner 全局索引当局部索引用导致多段轨迹失效
├── E-02 PurePursuit 倒车转向角符号未取反
├── E-03 PurePursuit 倒车坐标变换未用运动方向
└── E-04 planning 返回 None 时旧轨迹残留
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
| 路权端点处理：无MA/空MA→停车，有效MA→放行 | 无 MA 或空 MA 时未停车 | C-02-C1~C3 |
| B样条平滑后 heading 重算 | 原样复制旧 heading，平滑后几何与航向不一致 | C-03-C1~C3 |
| 曲率数据读取与校验 | 未读取曲率 | C-04-C1~C4 |
| 前进倒车方向切换 | advanceToNext 未调用，direction 未联动档位 | C-05-C1~C3 |
| RTKPlanner 全局/局部索引转换 | 未实现，需注意 index 坐标系一致 | E-01 |
| PurePursuit 倒车转向角取反 | 未实现 | E-02 |
| PurePursuit 倒车坐标变换（运动方向） | 未实现 | E-03 |
| planning 失败时清理旧轨迹 | 未实现，需防旧轨迹残留 | E-04 |
