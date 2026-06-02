"""A1 测试模块数据类型定义

定义 A1 验证层使用的所有枚举、dataclass 和类型别名。
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


# ======================== 枚举 ========================

class Verdict(Enum):
    """测试判定结果"""
    PASS = auto()       # 通过 (绿色)
    FAIL = auto()       # 失败 (红色)
    WARN = auto()       # 警告 (黄色)
    PENDING = auto()    # 待判定 (灰色)
    SKIPPED = auto()    # 跳过 (深灰, 条件不满足)


class AnomalySeverity(Enum):
    """异常严重程度"""
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


# ======================== 测试用例定义 ========================

@dataclass
class TestCaseDefinition:
    """单条 A1 测试用例的元数据"""
    case_id: str                      # 用例编号, 如 "A1-01"
    name: str                         # 用例名称
    description: str                  # 详细描述
    topics: list[str]                 # 监控的 topic 列表, ["*"] 表示全部
    categories: list[str] = field(default_factory=list)  # 分类标签


# ======================== 测试事件数据 ========================

@dataclass
class TestVerdictEntry:
    """单条验证判定结果"""
    case_id: str                      # 关联的用例编号
    verdict: Verdict                  # 判定结果
    timestamp: float                  # sim_time
    message: str                      # 人类可读的描述
    details: dict = field(default_factory=dict)  # 结构化上下文 (如期望值/实际值)


@dataclass
class MessageFlowEvent:
    """单条消息流过事件记录"""
    sequence_id: int                  # per-topic 单调递增序号
    topic: str                        # 消息 topic
    publisher: str                    # 发布模块名
    msg_type: str                     # Python 消息类名
    timestamp: float                  # 消息体中的 sim_time
    wall_time: float                  # time.perf_counter() 观测时间
    size_bytes: int = 0               # 估算消息体字节数
    extra: dict = field(default_factory=dict)  # 扩展字段


@dataclass
class AnomalyEvent:
    """检测到的异常事件"""
    case_id: str                      # 关联的用例编号
    severity: AnomalySeverity         # 严重程度
    timestamp: float                  # sim_time
    anomaly_type: str                 # 异常类型: "delay", "missing_field", "curvature_jump" 等
    topic: str = ""                   # 关联的 topic
    message: str = ""                 # 人类可读描述
    details: dict = field(default_factory=dict)  # 结构化上下文


@dataclass
class PeriodicCheckResult:
    """周期性数据处理检查结果 (A1-03)"""
    case_id: str
    topic: str
    expected_hz: float                # 期望频率
    actual_hz: float                  # 实际频率
    jitter_max_ms: float              # 最大抖动 (ms)
    drop_count: int                   # 丢帧数 (基于序号间隔)
    verdict: Verdict


# ======================== 类型别名 ========================

# 验证规则函数签名: (engine, sim_time) -> [verdicts]
ValidationRule = Callable[["A1ValidationEngine", float], list[TestVerdictEntry]]

# 参考线验证回调: (points) -> [anomalies]
RefLineValidator = Callable[[list], list[AnomalyEvent]]


# ======================== 辅助函数 ========================

def verdict_color(v: Verdict) -> str:
    """将 Verdict 映射到 UI 颜色 hex 值"""
    _map = {
        Verdict.PASS:    "#00ff88",
        Verdict.FAIL:    "#ff4444",
        Verdict.WARN:    "#ffcc00",
        Verdict.PENDING: "#667788",
        Verdict.SKIPPED: "#444455",
    }
    return _map.get(v, "#667788")


def verdict_icon(v: Verdict) -> str:
    """将 Verdict 映射到 UI 图标字符"""
    _map = {
        Verdict.PASS:    "✓",   # ✓
        Verdict.FAIL:    "✗",   # ✗
        Verdict.WARN:    "⚠",   # ⚠
        Verdict.PENDING: "—",   # —
        Verdict.SKIPPED: "⦸",   # ⦸
    }
    return _map.get(v, "—")


def severity_color(s: AnomalySeverity) -> str:
    """将 AnomalySeverity 映射到 UI 颜色 hex 值"""
    _map = {
        AnomalySeverity.INFO:     "#8899aa",
        AnomalySeverity.WARNING:  "#ffcc00",
        AnomalySeverity.ERROR:    "#ff6644",
        AnomalySeverity.CRITICAL: "#ff2222",
    }
    return _map.get(s, "#8899aa")
