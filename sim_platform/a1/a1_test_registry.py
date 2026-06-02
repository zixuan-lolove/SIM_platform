"""A1 测试用例注册表 — 10 条用例的结构化定义

每条用例包含:
  - 元数据 (编号、名称、描述、监控 topic、分类标签)
  - 验证规则函数 (由 A1ValidationEngine 调用)
"""

import math
import time
from typing import TYPE_CHECKING

from .a1_types import (
    TestCaseDefinition,
    TestVerdictEntry,
    AnomalyEvent,
    AnomalySeverity,
    PeriodicCheckResult,
    Verdict,
)

if TYPE_CHECKING:
    from .a1_validation_engine import A1ValidationEngine

# ======================== topic 与预期消息类型的映射 (A1-01) ========================

# 每个 topic 上预期的消息 Python 类名集合
TOPIC_EXPECTED_TYPES: dict[str, set[str]] = {
    "CloudDispatchTask": {"CloudDispatchTask"},
    "TaskToPlanning":    {"TaskToPlanning"},
    "MoveAuthority":     {"MoveAuthority"},
    "PlanningResult":    {"PlanningResult"},
    "ControlCmd":        {"ControlCmd"},
    "Localization":      {"Localization"},
    "Chassis":           {"Chassis"},
    "Obstacles":         {"list"},    # obstacles 是 list[Obstacle]
    "CloudDeviceMsg":    {"CloudDeviceMsg"},
}

# 周期性 topic 的期望频率 (A1-03)
TOPIC_EXPECTED_HZ: dict[str, float] = {
    "Localization":   100.0,
    "Chassis":        100.0,
    "PlanningResult": 10.0,
    "ControlCmd":     100.0,
    "Obstacles":      20.0,
}

# 延迟检测阈值 (A1-04)
TOPIC_LATENCY_THRESHOLD_MS: dict[str, float] = {
    "Localization":   50.0,
    "PlanningResult": 200.0,
    "Obstacles":      100.0,
}

# ======================== 10 条用例定义 ========================

A1_TEST_CASES: list[TestCaseDefinition] = [
    TestCaseDefinition(
        case_id="A1-01",
        name="数据分类机制的准确性验证",
        description="验证所有消息路由到正确的 topic，无跨 topic 泄漏或类型错配",
        topics=["*"],
        categories=["routing"],
    ),
    TestCaseDefinition(
        case_id="A1-02",
        name="时间戳记录的精度与完整性验证",
        description="每条消息携带有效、单调递增的时间戳，与仿真时间偏差 < 100ms",
        topics=["*"],
        categories=["timing"],
    ),
    TestCaseDefinition(
        case_id="A1-03",
        name="周期性数据处理逻辑验证",
        description="验证各周期性 topic 按期望频率发布，抖动/丢帧在可接受范围",
        topics=["Localization", "Chassis", "PlanningResult", "ControlCmd", "Obstacles"],
        categories=["timing", "periodic"],
    ),
    TestCaseDefinition(
        case_id="A1-04",
        name="延迟检测计算逻辑与上报完整性验证",
        description="测量端到端延迟，超过阈值时产生告警",
        topics=["*"],
        categories=["timing", "latency"],
    ),
    TestCaseDefinition(
        case_id="A1-05",
        name="故障处理动作执行正确性验证",
        description="验证超时→停车→上报的故障处理链完整性",
        topics=["PlanningResult", "CloudDeviceMsg"],
        categories=["fault"],
    ),
    TestCaseDefinition(
        case_id="A1-06",
        name="参考线航向角跳变时的异常检测",
        description="检测相邻轨迹点航向角跳变 > 10°，产生告警 (v0.3)",
        topics=["*"],
        categories=["reference_line", "anomaly"],
    ),
    TestCaseDefinition(
        case_id="A1-07",
        name="参考线起点距车辆过远时的重规划",
        description="验证车辆到参考线起点距离 > 3m 时触发重规划或拒绝 (v0.3)",
        topics=["TaskToPlanning", "PlanningResult"],
        categories=["reference_line"],
    ),
]


# ======================== 验证规则函数 ========================

class A1ValidationRules:
    """A1 验证规则静态方法集合

    每个方法签名为:
        (engine: A1ValidationEngine, sim_time: float, **context) -> list[TestVerdictEntry]
    """

    # ── A1-01: 数据路由验证 ──

    @staticmethod
    def validate_routing(topic: str, msg_type: str) -> list[TestVerdictEntry]:
        """校验消息类型是否匹配 topic"""
        verdicts = []
        expected = TOPIC_EXPECTED_TYPES.get(topic)
        if expected is None:
            verdicts.append(TestVerdictEntry(
                case_id="A1-01",
                verdict=Verdict.WARN,
                timestamp=time.time(),
                message=f"未知 topic: {topic}",
                details={"topic": topic, "msg_type": msg_type},
            ))
        elif msg_type not in expected and "list" not in expected:
            verdicts.append(TestVerdictEntry(
                case_id="A1-01",
                verdict=Verdict.FAIL,
                timestamp=time.time(),
                message=f"topic={topic} 上收到非预期类型: {msg_type}, 期望: {expected}",
                details={"topic": topic, "msg_type": msg_type, "expected": list(expected)},
            ))
        else:
            verdicts.append(TestVerdictEntry(
                case_id="A1-01",
                verdict=Verdict.PASS,
                timestamp=time.time(),
                message=f"topic={topic} 消息类型正确: {msg_type}",
                details={"topic": topic, "msg_type": msg_type},
            ))
        return verdicts

    # ── A1-02: 时间戳验证 ──

    @staticmethod
    def validate_timestamp(topic: str, msg_timestamp: float,
                           sim_time: float, last_ts: float) -> list[TestVerdictEntry]:
        """校验消息时间戳的有效性和单调性"""
        verdicts = []

        # 检查时间戳是否有效
        if msg_timestamp <= 0.0:
            verdicts.append(TestVerdictEntry(
                case_id="A1-02",
                verdict=Verdict.FAIL,
                timestamp=sim_time,
                message=f"topic={topic} 消息时间戳无效: {msg_timestamp}",
                details={"topic": topic, "timestamp": msg_timestamp},
            ))
            return verdicts

        # 检查与仿真时间的偏差
        deviation = abs(msg_timestamp - sim_time)
        if deviation > 0.5:  # 500ms 偏差阈值
            verdicts.append(TestVerdictEntry(
                case_id="A1-02",
                verdict=Verdict.WARN,
                timestamp=sim_time,
                message=f"topic={topic} 时间戳偏差过大: {deviation*1000:.1f}ms",
                details={"topic": topic, "deviation_ms": deviation * 1000},
            ))
        else:
            verdicts.append(TestVerdictEntry(
                case_id="A1-02",
                verdict=Verdict.PASS,
                timestamp=sim_time,
                message=f"topic={topic} 时间戳有效, 偏差 {deviation*1000:.1f}ms",
                details={"topic": topic, "deviation_ms": deviation * 1000},
            ))

        # 检查单调性
        if last_ts > 0 and msg_timestamp < last_ts:
            verdicts.append(TestVerdictEntry(
                case_id="A1-02",
                verdict=Verdict.FAIL,
                timestamp=sim_time,
                message=f"topic={topic} 时间戳非单调: {msg_timestamp} < {last_ts}",
                details={"topic": topic, "current": msg_timestamp, "previous": last_ts},
            ))

        return verdicts

    # ── A1-03: 周期性处理验证 ──

    @staticmethod
    def validate_periodic(engine: "A1ValidationEngine",
                          sim_time: float) -> list[TestVerdictEntry]:
        """验证周期性 topic 的发布频率"""
        verdicts = []
        for topic, expected_hz in TOPIC_EXPECTED_HZ.items():
            iat = engine.get_inter_arrival_stats(topic)
            if iat is None or iat["count"] < 3:
                continue

            actual_hz = 1.0 / iat["mean"] if iat["mean"] > 0 else 0.0
            jitter_ms = iat["std"] * 1000
            drop_count = iat.get("drop_count", 0)

            # 频率偏差 > 20% → WARN
            if abs(actual_hz - expected_hz) / expected_hz > 0.20:
                verdicts.append(TestVerdictEntry(
                    case_id="A1-03",
                    verdict=Verdict.WARN,
                    timestamp=sim_time,
                    message=f"topic={topic} 频率偏差: 实际 {actual_hz:.1f}Hz, 期望 {expected_hz:.1f}Hz",
                    details={"topic": topic, "actual_hz": round(actual_hz, 1),
                             "expected_hz": expected_hz, "jitter_ms": round(jitter_ms, 1),
                             "drop_count": drop_count},
                ))
            elif drop_count > 0:
                verdicts.append(TestVerdictEntry(
                    case_id="A1-03",
                    verdict=Verdict.WARN,
                    timestamp=sim_time,
                    message=f"topic={topic} 检测到 {drop_count} 次丢帧",
                    details={"topic": topic, "actual_hz": round(actual_hz, 1),
                             "drop_count": drop_count},
                ))
            else:
                verdicts.append(TestVerdictEntry(
                    case_id="A1-03",
                    verdict=Verdict.PASS,
                    timestamp=sim_time,
                    message=f"topic={topic} 频率正常: {actual_hz:.1f}Hz, 抖动 {jitter_ms:.1f}ms",
                    details={"topic": topic, "actual_hz": round(actual_hz, 1),
                             "expected_hz": expected_hz, "jitter_ms": round(jitter_ms, 1)},
                ))

        return verdicts

    # ── A1-04: 延迟检测 ──

    @staticmethod
    def validate_latency(topic: str, inter_arrival_ms: float,
                         expected_period_ms: float) -> list[TestVerdictEntry]:
        """通过到达间隔测量处理延迟

        Args:
            topic: 消息 topic
            inter_arrival_ms: 本次与上次发布之间的实际间隔 (ms)
            expected_period_ms: 期望的发布周期 (ms), 如 100Hz → 10ms
        """
        verdicts = []
        # 延迟 = 实际间隔 - 期望间隔, 正值表示处理滞后
        excess = inter_arrival_ms - expected_period_ms
        threshold = max(expected_period_ms * 3, 50.0)  # 3倍周期或最小50ms

        if inter_arrival_ms > threshold:
            verdicts.append(TestVerdictEntry(
                case_id="A1-04",
                verdict=Verdict.WARN,
                timestamp=0.0,
                message=f"topic={topic} 处理延迟: {inter_arrival_ms:.1f}ms > {threshold:.0f}ms 阈值 "
                        f"(期望 {expected_period_ms:.0f}ms, 超出 {excess:.1f}ms)",
                details={"topic": topic, "inter_arrival_ms": round(inter_arrival_ms, 1),
                         "expected_ms": round(expected_period_ms, 0),
                         "excess_ms": round(excess, 1)},
            ))
        else:
            verdicts.append(TestVerdictEntry(
                case_id="A1-04",
                verdict=Verdict.PASS,
                timestamp=0.0,
                message=f"topic={topic} 延迟正常: {inter_arrival_ms:.1f}ms (期望 {expected_period_ms:.0f}ms)",
                details={"topic": topic, "inter_arrival_ms": round(inter_arrival_ms, 1)},
            ))

        return verdicts

    # ── A1-05: 故障处理验证 ──

    @staticmethod
    def validate_fault_handling(engine: "A1ValidationEngine",
                                sim_time: float) -> list[TestVerdictEntry]:
        """验证故障处理链: 超时 → 停车 → 上报"""
        verdicts = []
        fh = engine._fault_handling_state

        # 如果之前检测到超时，检查后续是否触发了停车
        if fh.get("is_over_time"):
            if fh.get("stop_triggered"):
                verdicts.append(TestVerdictEntry(
                    case_id="A1-05",
                    verdict=Verdict.PASS,
                    timestamp=sim_time,
                    message="故障处理链完整: 超时→停车 已执行",
                    details={"overtime_ts": fh.get("overtime_ts", 0),
                             "stop_ts": fh.get("stop_ts", 0)},
                ))
                engine._fault_handling_state = {}  # 重置
            elif sim_time - fh.get("overtime_ts", 0) > 1.0:
                # 超时后 1s 仍未停车 → FAIL
                verdicts.append(TestVerdictEntry(
                    case_id="A1-05",
                    verdict=Verdict.FAIL,
                    timestamp=sim_time,
                    message="故障处理链断裂: 超时后 1s 未触发停车",
                    details={"overtime_ts": fh.get("overtime_ts", 0)},
                ))

        return verdicts

    # ── A1-06: 参考线中断检测 ──

    @staticmethod
    def validate_ref_line_continuity(points: list) -> list[AnomalyEvent]:
        """检测参考线相邻点间距 > 5m 的中断"""
        anomalies = []
        if len(points) < 2:
            return anomalies

        for i in range(1, len(points)):
            prev, curr = points[i - 1], points[i]
            # 尝试获取 x, y 属性
            try:
                px, py = (prev.x, prev.y) if hasattr(prev, 'x') else (prev[0], prev[1])
                cx, cy = (curr.x, curr.y) if hasattr(curr, 'x') else (curr[0], curr[1])
                dist = math.hypot(cx - px, cy - py)
            except (TypeError, IndexError, AttributeError):
                continue

            if dist > 5.0:
                anomalies.append(AnomalyEvent(
                    case_id="A1-06",
                    severity=AnomalySeverity.ERROR,
                    timestamp=time.time(),
                    anomaly_type="reference_line_gap",
                    message=f"参考线中断: 点[{i-1}]→点[{i}] 间距 {dist:.1f}m > 5m",
                    details={"point_index": i, "distance": round(dist, 2),
                             "prev": (round(px, 2), round(py, 2)),
                             "curr": (round(cx, 2), round(cy, 2))},
                ))

        return anomalies

    # ── A1-07: 曲率跳变过滤 ──

    @staticmethod
    def validate_curvature_filter(points: list) -> list[AnomalyEvent]:
        """检测相邻轨迹点曲率跳变 > 0.1 (1/m)"""
        anomalies = []
        if len(points) < 2:
            return anomalies

        for i in range(1, len(points)):
            try:
                prev_k = points[i - 1].curvature if hasattr(points[i - 1], 'curvature') else 0.0
                curr_k = points[i].curvature if hasattr(points[i], 'curvature') else 0.0
            except (TypeError, AttributeError):
                continue

            # 跳过未设置曲率值的点
            if abs(prev_k) < 1e-9 and abs(curr_k) < 1e-9:
                continue

            delta = abs(curr_k - prev_k)
            if delta > 0.1:
                anomalies.append(AnomalyEvent(
                    case_id="A1-07",
                    severity=AnomalySeverity.WARNING,
                    timestamp=time.time(),
                    anomaly_type="curvature_jump",
                    message=f"曲率跳变: 点[{i-1}]→点[{i}] Δκ={delta:.3f} > 0.1",
                    details={"point_index": i, "delta": round(delta, 4),
                             "prev_k": round(prev_k, 4), "curr_k": round(curr_k, 4)},
                ))

        return anomalies

    # ── A1-08: 航向跳变检测 ──

    @staticmethod
    def validate_heading_jump(points: list) -> list[AnomalyEvent]:
        """检测相邻轨迹点航向角跳变 > 10° (v0.3)

        TrajPoint.theta 为弧度，TrajPoint.heading 为度。
        优先使用 theta（弧度）。theta=0 是合法值（正东方向），不需要额外守卫。
        """
        anomalies = []
        if len(points) < 2:
            return anomalies

        for i in range(1, len(points)):
            try:
                # 优先用 theta (弧度)，避免度/弧度单位混淆
                prev_h = points[i - 1].theta if hasattr(points[i - 1], 'theta') \
                    else math.radians(points[i - 1].heading if hasattr(points[i - 1], 'heading') else 0.0)
                curr_h = points[i].theta if hasattr(points[i], 'theta') \
                    else math.radians(points[i].heading if hasattr(points[i], 'heading') else 0.0)
            except (TypeError, AttributeError):
                continue

            # 角度归一化到 [-π, π]
            def normalize_angle(a: float) -> float:
                while a > math.pi:
                    a -= 2 * math.pi
                while a < -math.pi:
                    a += 2 * math.pi
                return a

            delta = abs(normalize_angle(curr_h - prev_h))
            delta_deg = math.degrees(delta)

            if delta_deg > 10.0:
                anomalies.append(AnomalyEvent(
                    case_id="A1-06",
                    severity=AnomalySeverity.WARNING,
                    timestamp=time.time(),
                    anomaly_type="heading_jump",
                    message=f"航向跳变: 点[{i-1}]→点[{i}] Δθ={delta_deg:.1f}° > 10°",
                    details={"point_index": i, "delta_deg": round(delta_deg, 1),
                             "prev_deg": round(math.degrees(prev_h), 1),
                             "curr_deg": round(math.degrees(curr_h), 1)},
                ))

        return anomalies

    # ── A1-09: 起点距离检查 ──

    @staticmethod
    def validate_start_point_distance(vehicle_x: float, vehicle_y: float,
                                      ref_start_x: float, ref_start_y: float,
                                      sim_time: float) -> list[TestVerdictEntry]:
        """检查车辆到参考线起点的距离 (v0.3: ≤3m PASS, >3m WARN)"""
        dist = math.hypot(ref_start_x - vehicle_x, ref_start_y - vehicle_y)

        if dist > 3.0:
            return [TestVerdictEntry(
                case_id="A1-07",
                verdict=Verdict.WARN,
                timestamp=sim_time,
                message=f"参考线起点距离过远: {dist:.1f}m > 3m, 需重规划",
                details={"distance": round(dist, 2), "vehicle": (round(vehicle_x, 2), round(vehicle_y, 2)),
                         "ref_start": (round(ref_start_x, 2), round(ref_start_y, 2))},
            )]
        else:
            return [TestVerdictEntry(
                case_id="A1-07",
                verdict=Verdict.PASS,
                timestamp=sim_time,
                message=f"参考线起点距离正常: {dist:.1f}m",
                details={"distance": round(dist, 2)},
            )]

    # ── A1-10: 必填字段验证 ──

    @staticmethod
    def validate_required_fields(msg_type: str, payload: dict,
                                 sim_time: float) -> list[TestVerdictEntry]:
        """校验 DispatchTask / TaskToPlanning 消息的必填字段"""
        verdicts = []

        if msg_type == "CloudDispatchTask":
            required = ["task_sn", "task_type"]
            missing = [f for f in required if not payload.get(f)]
            if missing:
                verdicts.append(TestVerdictEntry(
                    case_id="A1-10",
                    verdict=Verdict.FAIL,
                    timestamp=sim_time,
                    message=f"DispatchTask 缺少必填字段: {missing}",
                    details={"missing_fields": missing},
                ))
            else:
                verdicts.append(TestVerdictEntry(
                    case_id="A1-10",
                    verdict=Verdict.PASS,
                    timestamp=sim_time,
                    message=f"DispatchTask 字段完整: task_sn={payload.get('task_sn')}",
                    details={"task_sn": payload.get("task_sn", "")},
                ))

        elif msg_type == "TaskToPlanning":
            if not payload.get("task_traj") or not payload.get("task_sn"):
                verdicts.append(TestVerdictEntry(
                    case_id="A1-10",
                    verdict=Verdict.FAIL,
                    timestamp=sim_time,
                    message=f"TaskToPlanning 缺少必填字段: task_traj 或 task_sn 为空",
                    details={"has_traj": bool(payload.get("task_traj")),
                             "has_sn": bool(payload.get("task_sn"))},
                ))
            else:
                verdicts.append(TestVerdictEntry(
                    case_id="A1-10",
                    verdict=Verdict.PASS,
                    timestamp=sim_time,
                    message=f"TaskToPlanning 字段完整",
                    details={"task_sn": str(payload.get("task_sn", ""))},
                ))

        return verdicts
