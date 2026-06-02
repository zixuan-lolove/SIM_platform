"""A1 测试数据记录器 — 结构化事件存储、查询与 JSON 导出

采用与 DataLogger 一致的 deque(maxlen) 模式，O(1) 追加，自动裁剪。
提供 JSON 导出/导入用于离线回放分析。
"""

import json
import logging
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Optional

from .a1_types import (
    AnomalyEvent,
    AnomalySeverity,
    MessageFlowEvent,
    PeriodicCheckResult,
    TestVerdictEntry,
    Verdict,
)

logger = logging.getLogger(__name__)


class A1TestRecorder:
    """A1 测试数据记录器

    记录三类事件到定长双端队列:
      - MessageFlowEvent:  消息流过事件
      - TestVerdictEntry:   验证判定
      - AnomalyEvent:       检测到的异常

    支持按条件查询和 JSON 序列化导出。
    """

    def __init__(self, max_flow_events: int = 20000,
                 max_verdicts: int = 5000,
                 max_anomalies: int = 2000):
        self._flow_events: deque[MessageFlowEvent] = deque(maxlen=max_flow_events)
        self._verdicts: deque[TestVerdictEntry] = deque(maxlen=max_verdicts)
        self._anomalies: deque[AnomalyEvent] = deque(maxlen=max_anomalies)
        self._periodic_results: deque[PeriodicCheckResult] = deque(maxlen=500)
        self._bookmarks: list[dict] = []

        # 运行元数据
        self._run_id: str = str(uuid.uuid4())[:8]
        self._run_start_wall: float = 0.0
        self._run_start_sim: float = 0.0

    # ======================== 记录接口 ========================

    def start_run(self) -> None:
        """标记测试运行开始"""
        self._run_id = str(uuid.uuid4())[:8]
        self._run_start_wall = time.perf_counter()
        self._bookmarks.clear()
        logger.info(f"[A1Recorder] 测试运行开始 run_id={self._run_id}")

    def record_flow(self, event: MessageFlowEvent) -> None:
        """记录一条消息流过事件"""
        self._flow_events.append(event)

    def record_verdict(self, entry: TestVerdictEntry) -> None:
        """记录一条验证判定"""
        self._verdicts.append(entry)

    def record_anomaly(self, event: AnomalyEvent) -> None:
        """记录一条异常事件"""
        self._anomalies.append(event)
        # 超过 WARNING 级别的异常打印日志
        if event.severity in (AnomalySeverity.ERROR, AnomalySeverity.CRITICAL):
            logger.warning(
                f"[A1] [{event.severity.name}] {event.case_id}: {event.message}"
            )

    def record_periodic(self, result: PeriodicCheckResult) -> None:
        """记录周期性检查结果"""
        self._periodic_results.append(result)

    def add_bookmark(self, label: str, sim_time: float) -> None:
        """添加用户标记点 (用于回放分析定位)"""
        self._bookmarks.append({
            "label": label,
            "sim_time": sim_time,
            "wall_time": time.perf_counter(),
        })

    # ======================== 查询接口 ========================

    def get_flow_by_topic(self, topic: str, n: int = 200) -> list[MessageFlowEvent]:
        """按 topic 查询最近的流过事件"""
        result = []
        for e in reversed(self._flow_events):
            if e.topic == topic:
                result.append(e)
                if len(result) >= n:
                    break
        result.reverse()
        return result

    def get_flow_events(self, n: int = 500) -> list[MessageFlowEvent]:
        """获取最近的 N 条流过事件"""
        items = list(self._flow_events)
        return items[-n:] if len(items) > n else items

    def get_verdicts_by_case(self, case_id: str) -> list[TestVerdictEntry]:
        """按用例编号查询判定"""
        return [v for v in self._verdicts if v.case_id == case_id]

    def get_verdicts(self) -> list[TestVerdictEntry]:
        """获取全部判定"""
        return list(self._verdicts)

    def get_anomalies_by_severity(self, severity: AnomalySeverity,
                                  n: int = 100) -> list[AnomalyEvent]:
        """按严重程度查询异常"""
        result = []
        for e in reversed(self._anomalies):
            if e.severity == severity:
                result.append(e)
                if len(result) >= n:
                    break
        result.reverse()
        return result

    def get_anomalies(self, n: int = 500) -> list[AnomalyEvent]:
        """获取最近的 N 条异常"""
        items = list(self._anomalies)
        return items[-n:] if len(items) > n else items

    def get_periodic_results(self) -> list[PeriodicCheckResult]:
        """获取全部周期性检查结果"""
        return list(self._periodic_results)

    # ======================== 汇总统计 ========================

    def get_summary(self) -> dict:
        """生成测试汇总统计

        Returns:
            {
                "run_id": str,
                "by_case": {case_id: {"pass": N, "fail": N, "warn": N, "pending": N, "skipped": N}},
                "total_verdicts": int,
                "total_anomalies": int,
                "total_flow_events": int,
                "last_case_verdict": {case_id: Verdict.name},  # 每条用例的最新判定
            }
        """
        by_case: dict[str, dict[str, int]] = {}
        last_verdict: dict[str, str] = {}

        for v in self._verdicts:
            cid = v.case_id
            if cid not in by_case:
                by_case[cid] = {"pass": 0, "fail": 0, "warn": 0, "pending": 0, "skipped": 0}
            key = v.verdict.name.lower()
            by_case[cid][key] = by_case[cid].get(key, 0) + 1
            last_verdict[cid] = v.verdict.name

        return {
            "run_id": self._run_id,
            "by_case": by_case,
            "last_case_verdict": last_verdict,
            "total_verdicts": len(self._verdicts),
            "total_anomalies": len(self._anomalies),
            "total_flow_events": len(self._flow_events),
        }

    # ======================== 持久化 ========================

    def export_json(self, filepath: str) -> bool:
        """导出全部记录数据到 JSON 文件

        包含: 元数据, 流过事件, 判定, 异常, 周期检查, 书签
        """
        try:
            data = {
                "meta": {
                    "run_id": self._run_id,
                    "run_start_wall": self._run_start_wall,
                    "version": "1.0",
                },
                "verdicts": [
                    {
                        "case_id": v.case_id,
                        "verdict": v.verdict.name,
                        "timestamp": v.timestamp,
                        "message": v.message,
                        "details": v.details,
                    }
                    for v in self._verdicts
                ],
                "anomalies": [
                    {
                        "case_id": a.case_id,
                        "severity": a.severity.name,
                        "timestamp": a.timestamp,
                        "anomaly_type": a.anomaly_type,
                        "topic": a.topic,
                        "message": a.message,
                        "details": {str(k): str(v) for k, v in a.details.items()},
                    }
                    for a in self._anomalies
                ],
                "flow_events_summary": {
                    "total": len(self._flow_events),
                    "by_topic": self._topic_event_counts(),
                },
                "bookmarks": self._bookmarks,
            }

            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"[A1Recorder] 测试数据已导出到 {filepath}")
            return True
        except Exception:
            logger.exception(f"[A1Recorder] 导出失败: {filepath}")
            return False

    def import_json(self, filepath: str) -> bool:
        """从 JSON 文件加载历史记录 (会清空当前数据)

        仅加载 verdicts 和 anomalies 用于离线回放分析。
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.clear()
            meta = data.get("meta", {})
            self._run_id = meta.get("run_id", "imported")

            for v in data.get("verdicts", []):
                self._verdicts.append(TestVerdictEntry(
                    case_id=v["case_id"],
                    verdict=Verdict[v["verdict"]],
                    timestamp=v["timestamp"],
                    message=v["message"],
                    details=v.get("details", {}),
                ))
            for a in data.get("anomalies", []):
                self._anomalies.append(AnomalyEvent(
                    case_id=a["case_id"],
                    severity=AnomalySeverity[a["severity"]],
                    timestamp=a["timestamp"],
                    anomaly_type=a["anomaly_type"],
                    topic=a.get("topic", ""),
                    message=a.get("message", ""),
                    details=a.get("details", {}),
                ))

            logger.info(f"[A1Recorder] 已加载 {len(self._verdicts)} 条判定, "
                        f"{len(self._anomalies)} 条异常 from {filepath}")
            return True
        except Exception:
            logger.exception(f"[A1Recorder] 导入失败: {filepath}")
            return False

    # ======================== 生命周期 ========================

    def clear(self) -> None:
        """清空全部记录数据"""
        self._flow_events.clear()
        self._verdicts.clear()
        self._anomalies.clear()
        self._periodic_results.clear()
        self._bookmarks.clear()

    def __len__(self) -> int:
        return len(self._flow_events)

    def __bool__(self) -> bool:
        return len(self._flow_events) > 0

    # ======================== 内部辅助 ========================

    def _topic_event_counts(self) -> dict[str, int]:
        """统计各 topic 的事件数"""
        counts: dict[str, int] = {}
        for e in self._flow_events:
            counts[e.topic] = counts.get(e.topic, 0) + 1
        return counts
