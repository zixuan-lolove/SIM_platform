"""A1 验证引擎 — 核心观察者，订阅全部 SimMessageBus topic，输出测量数据到 DataLogger

设计原则:
  - 数据优先: 每一类测量值作为时间序列信号写入 DataLogger，用户通过 PlotWindow 观察趋势
  - 判定为辅: PASS/FAIL/WARN 判定仅作为数据异常的辅助标记
  - 被动观察者: 只读不修改消息，不阻塞正常仿真流程
  - 订阅者异常隔离: 验证逻辑异常不影响其他订阅者

用法:
    engine = A1ValidationEngine(bus, recorder, data_logger=data_logger)
    for case in A1_TEST_CASES:
        engine.register_test_case(case)
    # 每仿真步调用
    engine.step(sim_time)
"""

import logging
import math
import sys
import time
from collections import defaultdict, deque
from typing import Any, Callable, Optional

from ..core.sim_message_bus import SimMessageBus, ALL_TOPICS
from ..core.data_logger import DataLogger
from .a1_types import (
    AnomalyEvent,
    AnomalySeverity,
    MessageFlowEvent,
    PeriodicCheckResult,
    TestCaseDefinition,
    TestVerdictEntry,
    Verdict,
)
from .a1_test_recorder import A1TestRecorder
from .a1_test_registry import A1ValidationRules, TOPIC_EXPECTED_HZ

logger = logging.getLogger(__name__)

# ── 发布者身份预期 (A1-01) ──
_EXPECTED_PUBLISHERS: dict[str, set[str]] = {
    "Localization":     {"Kinematics"},
    "Chassis":          {"Kinematics"},
    "PlanningResult":   {"PlanningSim"},
    "ControlCmd":       {"Controller"},
    "Obstacles":        {"PerceptionSim"},
    "TaskToPlanning":   {"GatewaySim"},
    "MoveAuthority":    {"GatewaySim"},
    "CloudDispatchTask": {"RealCloudClient"},
    "CloudDeviceMsg":   {"GatewaySim"},
}

# 来自外部时钟源的消息发布者 (A1-02 MQTT 漂移检测)
_EXTERNAL_PUBLISHERS: set[str] = {"RealCloudClient"}

# A1-03 周期 topic 的期望频率
_EXPECTED_HZ: dict[str, float] = TOPIC_EXPECTED_HZ


class A1ValidationEngine:
    """A1 测试验证引擎 — 以数据为中心的测量+判定"""

    def __init__(self, bus: SimMessageBus, recorder: A1TestRecorder,
                 data_logger: Optional[DataLogger] = None):
        self._bus = bus
        self._recorder = recorder
        self._data_logger = data_logger  # 新增: 时间序列数据写入

        # 注册的测试用例
        self._test_cases: dict[str, TestCaseDefinition] = {}

        # 活跃的 topic 集合
        self._topics_with_rules: set[str] = set()

        # ── per-topic 追踪状态 ──
        self._inter_arrival: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=200)
        )
        self._last_publish_wall: dict[str, float] = {}
        self._last_seq: dict[str, int] = {}
        self._last_msg_timestamp: dict[str, float] = {}

        # ── 仿真步长抖动测量 (A1-04) ──
        self._last_step_wall: float = 0.0

        # ── 端到端延迟追踪 (A1-04): Localization→ControlCmd ──
        self._loc_publish_wall: float = 0.0  # 最近一次 Localization 发布的 wall_time

        # ── A1-05 故障处理状态 ──
        self._fault_handling_state: dict[str, Any] = {}

        # ── 回调 ──
        self._on_verdict: Optional[Callable[[TestVerdictEntry], None]] = None
        self._on_anomaly: Optional[Callable[[AnomalyEvent], None]] = None

        # ── 统计 ──
        self._started: bool = False
        self._current_sim_time: float = 0.0
        self._total_messages_observed: int = 0

        # 订阅全部 topic
        for topic in ALL_TOPICS:
            self._bus.subscribe(topic, self._on_message)

        logger.info(f"[A1Engine] 已订阅 {len(ALL_TOPICS)} 个 topic"
                    f"{', DataLogger=' + ('yes' if data_logger else 'no')}")

    # ======================== 注册接口 ========================

    def register_test_case(self, case: TestCaseDefinition) -> None:
        self._test_cases[case.case_id] = case
        if case.topics == ["*"]:
            self._topics_with_rules.update(ALL_TOPICS)
        else:
            self._topics_with_rules.update(case.topics)

    def register_all_cases(self, cases: list[TestCaseDefinition]) -> None:
        for case in cases:
            self.register_test_case(case)

    # ======================== 回调设置 ========================

    def set_verdict_callback(self, cb: Callable[[TestVerdictEntry], None]) -> None:
        self._on_verdict = cb

    def set_anomaly_callback(self, cb: Callable[[AnomalyEvent], None]) -> None:
        self._on_anomaly = cb

    # ======================== 核心观察者 ========================

    def _on_message(self, topic: str, msg: Any) -> None:
        """通用消息观察者 — 测量 → DataLogger + 判定 → Recorder"""
        if not self._started:
            return

        wall_time = time.perf_counter()
        msg_timestamp = getattr(msg, "timestamp", 0.0)
        msg_type = type(msg).__name__

        # 从总线日志中读取发布者身份 (publish() 在调用回调前已写入日志)
        publisher = self._read_last_publisher()

        # 从总线获取当前序列号
        seq = self._bus.get_seq_counter(topic)

        self._total_messages_observed += 1

        # ── 记录流过事件 ──
        flow_event = MessageFlowEvent(
            sequence_id=seq,
            topic=topic,
            publisher=publisher,
            msg_type=msg_type,
            timestamp=msg_timestamp,
            wall_time=wall_time,
            extra={},
        )
        self._recorder.record_flow(flow_event)

        # ── 更新 per-topic 统计 ──
        self._update_topic_stats(topic, seq, wall_time)

        # ═══════════════════════════════════════════════════════
        # 测量数据写入 DataLogger (主要产出)
        # ═══════════════════════════════════════════════════════

        if self._data_logger is not None:
            sim_t = self._current_sim_time

            # ── A1-01: 路由拓扑 hash (per-topic, 稳定=路由未变) ──
            route_key = f"{publisher}|{msg_type}"
            route_hash_val = float(hash(route_key) & 0x7FFFFFFF)
            hash_signal = f"a1.routing.hash_{topic}"
            self._data_logger.record(sim_t, **{hash_signal: route_hash_val})

            # 发布者身份校验：不符预期 → 异常事件（不额外写信号，异常事件已足够）
            expected_pubs = _EXPECTED_PUBLISHERS.get(topic)
            if expected_pubs and publisher and publisher not in expected_pubs:
                self._emit_anomaly(AnomalyEvent(
                    case_id="A1-01",
                    severity=AnomalySeverity.ERROR,
                    timestamp=sim_t,
                    anomaly_type="publisher_mismatch",
                    topic=topic,
                    message=f"发布者身份异常: topic={topic} publisher={publisher}, 期望 {expected_pubs}",
                    details={"topic": topic, "publisher": publisher,
                             "expected": list(expected_pubs)},
                ))

            try:
                msg_size = sys.getsizeof(msg)
            except Exception:
                msg_size = 0
            self._data_logger.record(sim_t, **{
                "a1.routing.msg_size_bytes": float(msg_size),
            })

            # ── A1-02: 时间戳偏差测量 ──
            if msg_timestamp > 0:
                dev_ms = abs(msg_timestamp - sim_t) * 1000.0
                self._data_logger.record(sim_t, **{
                    "a1.timing.sim_deviation_ms": dev_ms,
                })
                # MQTT 消息: 额外记录时钟漂移
                if publisher in _EXTERNAL_PUBLISHERS:
                    self._data_logger.record(sim_t, **{
                        "a1.timing.mqtt_drift_ms": dev_ms,
                    })

            # ── A1-04: 规划耗时 (从 PlanningResult 中提取) ──
            if topic == "PlanningResult":
                pt = getattr(msg, "planning_time_ms", 0.0)
                if pt >= 0:
                    self._data_logger.record(sim_t, **{
                        "a1.latency.plan_time_ms": pt,
                    })

            # ── A1-04: 端到端延迟 (Localization→ControlCmd) ──
            if topic == "Localization":
                self._loc_publish_wall = wall_time
            if topic == "ControlCmd" and self._loc_publish_wall > 0:
                e2e_ms = (wall_time - self._loc_publish_wall) * 1000.0
                self._data_logger.record(sim_t, **{
                    "a1.latency.e2e_loc_to_cmd_ms": e2e_ms,
                })

        # ═══════════════════════════════════════════════════════
        # 判定/异常事件 (辅助产出 — 仅数据异常时触发)
        # ═══════════════════════════════════════════════════════

        # ── A1-01: 路由验证 ──
        if "A1-01" in self._test_cases:
            for v in A1ValidationRules.validate_routing(topic, msg_type):
                self._emit_verdict(v)

        # ── A1-02: 时间戳验证 (仅对 MQTT 消息做有意义的偏差检查) ──
        if "A1-02" in self._test_cases:
            last_ts = self._last_msg_timestamp.get(topic, -1.0)
            for v in A1ValidationRules.validate_timestamp(
                topic, msg_timestamp, self._current_sim_time, last_ts
            ):
                self._emit_verdict(v)
            self._last_msg_timestamp[topic] = msg_timestamp

        # ── A1-04: 延迟检测 (基于到达间隔 + 规划耗时尖峰) ──
        if "A1-04" in self._test_cases:
            iat_deq = self._inter_arrival.get(topic)
            if iat_deq and len(iat_deq) > 0:
                iat_ms = iat_deq[-1] * 1000
                expected_hz = _EXPECTED_HZ.get(topic, 10.0)
                expected_ms = (1.0 / expected_hz) * 1000
                for v in A1ValidationRules.validate_latency(topic, iat_ms, expected_ms):
                    self._emit_verdict(v)

        # ── A1-10: 必填字段验证 ──
        if "A1-10" in self._test_cases and msg_type in (
            "CloudDispatchTask", "TaskToPlanning"
        ):
            payload = A1ValidationEngine._extract_payload(msg, msg_type)
            for v in A1ValidationRules.validate_required_fields(
                msg_type, payload, self._current_sim_time
            ):
                self._emit_verdict(v)

        # ── A1-05: 故障处理状态跟踪 ──
        if topic == "PlanningResult":
            self._track_fault_state(msg, self._current_sim_time)

    # ======================== 时间同步与周期性检查 ========================

    def sync_time(self, sim_time: float) -> None:
        """同步仿真时间 — 在 FullStackEngine 发布消息前调用

        确保 _on_message 中 msg_timestamp 与 sim_time 的对比使用当帧时间。
        也负责首次启动标记（_started=True），保证第一帧的消息不会被跳过。
        由 FullStackEngine.step() 在阶段 1 之前调用。
        """
        self._current_sim_time = sim_time
        if not self._started:
            self._started = True
            self._recorder.start_run()

    def step(self, sim_time: float) -> None:
        """每仿真步调用，执行周期性测量+验证

        由 FullStackEngine.step() 在每个仿真步末尾调用。
        sync_time() 必须先调用以确保 _started=True 和 _current_sim_time 同步。
        """
        self._current_sim_time = sim_time

        # ── 仿真步长抖动测量 (A1-04) ──
        wall_now = time.perf_counter()
        if self._last_step_wall > 0 and self._data_logger is not None:
            jitter_ms = (wall_now - self._last_step_wall) * 1000.0
            self._data_logger.record(sim_time, **{
                "a1.latency.step_jitter_ms": jitter_ms,
            })
        self._last_step_wall = wall_now

        # ── A1-03: 周期处理验证 (每 1s 检查一次) ──
        if "A1-03" in self._test_cases:
            elapsed = sim_time - getattr(self, "_last_a103_check", -1.0)
            if elapsed >= 1.0:
                self._last_a103_check = sim_time  # type: ignore[attr-defined]

                # 将频率测量数据写入 DataLogger
                if self._data_logger is not None:
                    for topic, expected_hz in _EXPECTED_HZ.items():
                        iat_stats = self.get_inter_arrival_stats(topic)
                        if iat_stats and iat_stats["count"] >= 3:
                            actual_hz = 1.0 / iat_stats["mean"] if iat_stats["mean"] > 0 else 0.0
                            signal_map = {
                                "Localization": "a1.flow.localization_hz",
                                "Chassis":      "a1.flow.chassis_hz",
                                "PlanningResult": "a1.flow.planning_hz",
                                "ControlCmd":   "a1.flow.control_hz",
                                "Obstacles":    "a1.flow.obstacles_hz",
                            }
                            signal_key = signal_map.get(topic)
                            if signal_key:
                                self._data_logger.record(sim_time, **{signal_key: actual_hz})

                        # A1-01: 订阅者总数 (路由覆盖检查)
                        sub_total = sum(
                            self._bus.get_topic_subscribers(t)
                            for t in ALL_TOPICS
                        )
                        self._data_logger.record(sim_time, **{
                            "a1.routing.sub_count": float(sub_total),
                        })

                # 现有判定逻辑
                for v in A1ValidationRules.validate_periodic(self, sim_time):
                    self._emit_verdict(v)

        # ── A1-05: 故障处理验证 ──
        if "A1-05" in self._test_cases:
            for v in A1ValidationRules.validate_fault_handling(self, sim_time):
                self._emit_verdict(v)

    # ======================== 参考线验证 ========================

    def validate_ref_line(self, points: list) -> None:
        """参考线加载时调用，执行参考线相关的验证 (A1-06 航向跳变)"""
        if not points:
            return

        # A1-06: 航向角跳变检测 (>10° v0.3)
        if "A1-06" in self._test_cases:
            for anomaly in A1ValidationRules.validate_heading_jump(points):
                self._recorder.record_anomaly(anomaly)
                self._emit_anomaly(anomaly)

    # ======================== 统计查询 ========================

    def get_inter_arrival_stats(self, topic: str) -> Optional[dict]:
        deq = self._inter_arrival.get(topic)
        if not deq or len(deq) < 2:
            return None

        values = list(deq)
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance)

        drop_count = 0
        for v in values:
            if v > mean * 2.5:
                drop_count += 1

        return {
            "mean": mean, "std": std, "min": min(values),
            "max": max(values), "count": n, "drop_count": drop_count,
        }

    def get_topic_stats(self, topic: str) -> dict:
        deq = self._inter_arrival.get(topic)
        seq = self._bus.get_seq_counter(topic)
        return {
            "topic": topic, "msg_count": seq,
            "last_wall_time": self._last_publish_wall.get(topic, 0.0),
            "iat_count": len(deq) if deq else 0,
            "expected_hz": _EXPECTED_HZ.get(topic, 0.0),
        }

    @property
    def total_messages_observed(self) -> int:
        return self._total_messages_observed

    @property
    def recorder(self) -> A1TestRecorder:
        return self._recorder

    # ======================== 内部方法 ========================

    def _read_last_publisher(self) -> str:
        """从总线最近一条日志中读取发布者身份"""
        try:
            recent = self._bus.get_recent_log(1)
            if recent:
                return recent[0].publisher
        except Exception:
            pass
        return ""

    def _update_topic_stats(self, topic: str, seq: int, wall_time: float) -> None:
        last_wall = self._last_publish_wall.get(topic)
        if last_wall is not None:
            iat = wall_time - last_wall
            if iat > 0:
                self._inter_arrival[topic].append(iat)
            last_seq = self._last_seq.get(topic, 0)
            if last_seq > 0 and seq > last_seq + 1:
                gap = seq - last_seq - 1
                anomaly = AnomalyEvent(
                    case_id="A1-03", severity=AnomalySeverity.WARNING,
                    timestamp=self._current_sim_time,
                    anomaly_type="message_drop", topic=topic,
                    message=f"topic={topic} 丢帧: seq {last_seq}→{seq}, 丢失 {gap} 条消息",
                    details={"topic": topic, "last_seq": last_seq,
                             "current_seq": seq, "gap": gap},
                )
                self._recorder.record_anomaly(anomaly)
                self._emit_anomaly(anomaly)

        self._last_publish_wall[topic] = wall_time
        self._last_seq[topic] = seq

    def _track_fault_state(self, msg: Any, sim_time: float) -> None:
        try:
            is_stop = getattr(msg, "stop", False)
            is_overtime = getattr(msg, "is_over_time", False)
            if is_overtime and not self._fault_handling_state.get("is_over_time"):
                self._fault_handling_state = {
                    "is_over_time": True, "overtime_ts": sim_time,
                    "stop_triggered": False, "stop_ts": 0.0,
                }
            if is_stop and self._fault_handling_state.get("is_over_time"):
                self._fault_handling_state["stop_triggered"] = True
                self._fault_handling_state["stop_ts"] = sim_time
        except Exception:
            pass

    def _emit_verdict(self, entry: TestVerdictEntry) -> None:
        self._recorder.record_verdict(entry)
        if self._on_verdict:
            self._on_verdict(entry)

    def _emit_anomaly(self, event: AnomalyEvent) -> None:
        """统一异常发射入口: 写入 recorder + 通知 UI"""
        self._recorder.record_anomaly(event)
        if self._on_anomaly:
            self._on_anomaly(event)

    @staticmethod
    def _extract_payload(msg: Any, msg_type: str) -> dict:
        try:
            if msg_type == "CloudDispatchTask":
                return {
                    "task_sn": getattr(msg, "task_sn", ""),
                    "task_type": getattr(msg, "task_type", 0),
                }
            elif msg_type == "TaskToPlanning":
                return {
                    "task_sn": getattr(msg, "task_sn", ""),
                    "task_traj": getattr(msg, "task_traj", None),
                }
        except Exception:
            pass
        return {}

    # ======================== 生命周期 ========================

    def reset(self) -> None:
        self._inter_arrival.clear()
        self._last_publish_wall.clear()
        self._last_seq.clear()
        self._last_msg_timestamp.clear()
        self._fault_handling_state = {}
        self._last_step_wall = 0.0
        self._loc_publish_wall = 0.0
        self._started = False
        self._total_messages_observed = 0
        self._current_sim_time = 0.0

    @property
    def active_cases(self) -> list[str]:
        return sorted(self._test_cases.keys())
