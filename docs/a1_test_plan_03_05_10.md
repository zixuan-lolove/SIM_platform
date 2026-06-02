# A1-03 / A1-05~A1-10 测试方案

> 日期：2026-06-01
> 状态：待确认

---

## 总览

| 用例 | 当前触发方式 | 测试难度 | 需要的基础设施 |
|------|------------|---------|--------------|
| A1-03 周期处理 | step() 每1s触发 | 低 | 持续仿真 5-10s |
| A1-05 故障处理 | 跟踪 PlanningResult | **需修复** | `is_over_time` 未暴露到消息中 |
| A1-06 参考线中断 | 参考线加载时 | 低 | 含跳点的测试轨迹 |
| A1-07 曲率跳变 | 参考线加载时 | 低 | 含曲率突变的测试轨迹 |
| A1-08 航向跳变 | 参考线加载时 | 低 | 含航向突变的测试轨迹 |
| A1-09 起点过远 | 参考线加载时 | 低 | 远离轨迹起点的初始位姿 |
| A1-10 缺失字段 | DispatchTask/TaskToPlanning | **需修复** | 字段为空的 mock 消息 |

---

## 一、A1-03 周期性数据处理逻辑验证

### 1.1 验证机制

当前实现：每 1 秒，`A1ValidationEngine.step()` 调用 `validate_periodic()`，
分析 5 个周期性 topic (Localization/Chassis/PlanningResult/ControlCmd/Obstacles)
的到达间隔统计（均值、标准差、丢帧数）。

### 1.2 测试方法

**方案 A：真实仿真运行（推荐）**

```
1. 进入全栈仿真模式
2. 加载 sim_test_mission.traj
3. 启动仿真，运行 ≥ 10 秒
4. 观察 A1 仪表盘中 A1-03 的状态变化
```

判定标准：
- 频率偏差 < 20%：PASS
- 频率偏差 ≥ 20%：WARN
- 检测到丢帧（序列号跃变 > 1）：WARN
- 样本不足（< 3 次发布）：不触发判定，保持 PENDING

### 1.3 验证脚本（离线）

```python
# 模拟 100Hz Localization 发布
for i in range(1000):  # 10s @ 100Hz
    loc = Localization(x=..., timestamp=i*0.01)
    bus.publish(LOCALIZATION, loc, "Kinematics")
    time.sleep(0.008)  # 模拟 ~8ms 处理时间（正常）
    engine.step(i * 0.01)
```

### 1.4 当前状态

✅ 可测试。只需持续运行仿真即可获得判定。
⚠️ 注意：当前 `step()` 中的周期性检查每 1s 触发一次，首次触发在仿真运行 1s 后。
   前 1s 内 A1-03 无判定输出（PENDING 状态），这是正常行为。

---

## 二、A1-05 故障处理动作执行正确性验证

### 2.1 设计思路

验证链路：**传感器数据超时 → Planning 判定 is_over_time → 触发 stop → 上行报告停车原因**

### 2.2 当前问题

`PlanningResult` 消息体**没有 `is_over_time` 字段**，导致 A1ValidationEngine 无法
从总线上观测到超时事件。当前 `_track_fault_state` 尝试通过 `getattr(msg, "is_over_time", False)`
读取，永远返回 False。

### 2.3 修复方案

**方案（推荐）：在 PlanningResult 中增加 `is_over_time` 字段**

```python
# sim_platform/models/sim_messages.py — PlanningResult
@dataclass
class PlanningResult:
    points: list[PlanningTrajectoryPoint]
    lift_cmd: int = 0
    task_finish: bool = False
    stop: bool = False
    is_over_time: bool = False     # 新增
    planner_type: str = "rtk"
    planning_time_ms: float = 0.0
    timestamp: float = 0.0
```

```python
# sim_platform/planning_sim/planning_sim.py — plan() 方法
result = PlanningResult(
    ...,
    stop=frame.stop,
    is_over_time=frame.is_over_time,  # 新增
    ...,
)
```

### 2.4 测试方法

**方案 A：注入模拟延迟（推荐）**

在 PlanningSim 中临时注入一个传感器数据延迟：
```python
# 修改 planning_sim._on_localization 中记录的时间戳
self._last_localization_time = msg.timestamp - 1.0  # 模拟 1s 延迟
```

此时 `_judge_over_time` 检测到 `loc_age > 0.5s`，设置 `frame.is_over_time = True`，
随后 `_judge_stop` 设置 `frame.stop = True`。

A1ValidationEngine 观测到 `PlanningResult(is_over_time=True)` 后记录状态，
下一个周期检查 `PlanningResult(stop=True)`，链路完整 → PASS。

**方案 B：单元测试级**

```python
# 直接构造 PlanningResult 发布到总线
from sim_platform.models.sim_messages import PlanningResult, PlanningTrajectoryPoint

# Step 1: 发布超时
result1 = PlanningResult(points=[...], is_over_time=True, stop=False, timestamp=1.0)
bus.publish(PLANNING_RESULT, result1, "PlanningSim")
engine.step(1.0)

# Step 2: 发布停车
result2 = PlanningResult(points=[...], is_over_time=True, stop=True, timestamp=1.1)
bus.publish(PLANNING_RESULT, result2, "PlanningSim")
engine.step(1.1)

# 检查 A1-05 判定
```

### 2.5 当前状态

❌ 需先修复 `is_over_time` 未暴露的问题，否则无法测试。

---

## 三、A1-06 参考线数据中断时的故障处理

### 3.1 验证机制

`validate_ref_line_continuity()` 遍历参考线相邻点，检测间距 > 5m 的中断。

### 3.2 测试方法

**方案：构造含跳点的测试轨迹**

生成一段轨迹，其中故意插入一个 >5m 的跳跃：

```python
import math
from sim_platform.models.sim_messages import TrajPoint

def make_gap_traj():
    """构造含跳点的测试轨迹"""
    points = []
    for i in range(100):
        x = i * 1.0  # 1m 步长
        y = 0.0
        if i == 50:
            x += 20.0  # 在中间插入 20m 跳变
        pts.append(TrajPoint(x=x, y=y, lat=..., lon=..., ...))
    return pts
```

然后在测试中手动调用：
```python
engine.validate_ref_line(points)
anomalies = recorder.get_anomalies()
# 期望: 1 条 AnomalySeverity.ERROR, anomaly_type="reference_line_gap"
```

### 3.3 当前状态

✅ 验证逻辑已实现。需要构造测试轨迹文件或编写单元测试。

---

## 四、A1-07 参考线曲率突变时的过滤处理

### 4.1 验证机制

`validate_curvature_filter()` 检测相邻点曲率差 > 0.1 (1/m)。

### 4.2 测试方法

```python
# 构造含曲率跳变的轨迹点
pts = []
for i in range(50):
    pt = TrajPoint(x=i*1.0, y=0.0, ...)
    pt.curvature = 0.0
    pts.append(pt)

# 在点 25 处插入曲率跳变
pts[25].curvature = 0.15  # Jump from 0.0 to 0.15

engine.validate_ref_line(pts)

# 期望: 1 条 AnomalySeverity.WARNING, anomaly_type="curvature_jump"
anomalies = recorder.get_anomalies_by_severity(AnomalySeverity.WARNING)
assert any(a.anomaly_type == "curvature_jump" for a in anomalies)
```

### 4.3 注意事项

- 当前轨迹文件 (`.traj`) 中的 `curvature` 字段可能全为 0（未设置），
  此时验证逻辑会**静默跳过**（两个相邻点的 curvature 都为 0 时不触发）
- 要测试此用例，需要在轨迹生成时**填入真实的曲率值**，或手工修改 TrajPoint

### 4.4 当前状态

✅ 验证逻辑已实现。需要含曲率值的轨迹数据或单元测试。

---

## 五、A1-08 参考线航向角跳变时的异常检测

### 5.1 验证机制

`validate_heading_jump()` 检测相邻点航向角差 > 5°（换算为弧度）。

### 5.2 测试方法

```python
import math

# 构造含航向跳变的轨迹点
pts = []
for i in range(50):
    pt = TrajPoint(x=i, y=0, heading=math.radians(90), ...)  # 全部朝北
    pts.append(pt)

# 在点 25 处插入 10° 跳变
pts[25].heading = math.radians(100)  # 10° jump

engine.validate_ref_line(pts)

# 期望: 1 条 AnomalySeverity.WARNING, anomaly_type="heading_jump"
```

### 5.3 当前状态

✅ 验证逻辑已实现。需要含航向跳变的轨迹数据或单元测试。

---

## 六、A1-09 参考线起点距车辆过远时的重规划

### 6.1 验证机制

`validate_start_point_distance()` 检查车辆位置到参考线第一个点的距离 > 2m。

### 6.2 当前问题

`validate_start_point_distance` 是一个**独立函数**，需要手动传入车辆坐标和参考线起点坐标。
当前集成链路中**没有自动调用它**——`validate_ref_line()` 只调用了
A1-06/07/08，没有调用 A1-09。

### 6.3 修复方案

在 `A1ValidationEngine.validate_ref_line()` 中增加 A1-09 调用，但需要车辆位置信息。
车辆位置可以从 `_latest_localization` 获取。需要在 PlanningSim 的 `_handle_new_task`
中同时传入车辆位置。

### 6.4 测试方法

```
1. 在全栈仿真中设置车辆初始位置远离轨迹起点（距离 > 2m）
2. 加载任务轨迹
3. PlanningSim 的 2m 邻近校验会拒绝任务
4. 同时 A1-09 应产生 WARN 判定
```

### 6.5 当前状态

⚠️ 需要完成两个修复：
1. `validate_ref_line()` 中增加 A1-09 调用
2. 传入车辆当前位置信息

---

## 七、A1-10 任务数据缺少必要字段时的重下发

### 7.1 验证机制

`validate_required_fields()` 检查：
- `CloudDispatchTask`: task_sn, task_type 非空
- `TaskToPlanning`: task_traj, task_sn 非空

### 7.2 当前问题

`_extract_payload()` 使用 `getattr(msg, "task_sn", "")` 提取字段。
Protobuf 生成的 dataclass 中，未设置的字段会有默认值（0, ""），导致
"缺失字段" 无法被检测——空字符串仍会通过 `if not payload.get(f)` 检查。

### 7.3 修复方案

区分"字段值为空"和"字段不存在"两种情况：

```python
@staticmethod
def _extract_payload(msg: Any, msg_type: str) -> dict:
    try:
        if msg_type == "CloudDispatchTask":
            task_sn = getattr(msg, "task_sn", None)
            task_type = getattr(msg, "task_type", None)
            return {
                "task_sn": task_sn,
                "task_type": task_type,
            }
    except Exception:
        pass
    return {}
```

并在 `validate_required_fields` 中将判定条件改为 `field is None or field == ""`。

### 7.4 测试方法

**方案 A：通过 CloudCommSim 发送不完整任务**

```python
from sim_platform.gateway_sim.cloud_comm_sim import CloudCommSim

cloud = CloudCommSim()
# 发送缺少 task_sn 的 DispatchTask
task = DispatchTask(task_sn="", task_type=1, ...)  # 空 task_sn
cloud.publish_dispatch_task(bus, task)
```

**方案 B：单元测试**

```python
# 直接发布缺少字段的消息到总线
msg = CloudDispatchTask(msg_type="dispatch_task",
    dispatch_task=DispatchTask(task_sn="", task_type=0))  # 空字段

bus.publish(CLOUD_DISPATCH_TASK, msg, "RealCloudClient")
engine.step(0.0)

# 检查 A1-10 判定
a110 = recorder.get_verdicts_by_case("A1-10")
assert any(v.verdict == Verdict.FAIL for v in a110)
```

### 7.5 当前状态

⚠️ 需要修复 `_extract_payload` 使其能区分"空值"和"默认值"。

---

## 八、推荐的实施顺序

| 步骤 | 内容 | 影响用例 | 工作量 |
|------|------|---------|--------|
| **Step 1** | 修复 PlanningResult 增加 `is_over_time` 字段 | A1-05 | 3 行 |
| **Step 2** | 修复 `_extract_payload` 区分空值 | A1-10 | 5 行 |
| **Step 3** | `validate_ref_line()` 增加 A1-09 调用 | A1-09 | 10 行 |
| **Step 4** | 生成测试用异常轨迹（gap/curvature/heading） | A1-06/07/08 | 50 行脚本 |
| **Step 5** | 编写集成测试脚本，一次性验证 A1-05~A1-10 | 全部 | 100 行 |

---

## 九、快速验证矩阵

完成修复后，使用下表逐条验证：

| 用例 | 验证操作 | 期望结果 | 预计耗时 |
|------|---------|---------|---------|
| A1-03 | 运行仿真 ≥ 10s | 5 个 topic 均 PASS | 10s |
| A1-05 | 注入传感器延迟 1s → 观察 | 超时→停车链路 PASS | < 1s |
| A1-06 | 加载含 20m 跳点的轨迹 | 1 条 ERROR 异常 | < 1s |
| A1-07 | 加载含曲率 0→0.15 跳变的轨迹 | 1 条 WARNING 异常 | < 1s |
| A1-08 | 加载含 10° 航向跳变的轨迹 | 1 条 WARNING 异常 | < 1s |
| A1-09 | 车辆远离轨迹起点 > 2m 加载任务 | WARN 判定 | < 1s |
| A1-10 | 发送 task_sn="" 的 DispatchTask | FAIL 判定 | < 1s |
