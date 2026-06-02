"""A1 消息流监视面板 — 9 个 topic 实时统计 + 异常事件日志

独立浮窗，显示 SimMessageBus 上各 topic 的消息流量和延迟。
"""

from collections import deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QTextEdit, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer

from ..a1.a1_types import (
    AnomalyEvent, AnomalySeverity, MessageFlowEvent,
    severity_color,
)


# topic 显示名称
TOPIC_DISPLAY_NAMES = {
    "CloudDispatchTask": "CloudDispatch",
    "TaskToPlanning":    "Task→Plan",
    "MoveAuthority":     "MoveAuth",
    "PlanningResult":    "PlanResult",
    "ControlCmd":        "ControlCmd",
    "Localization":      "Localization",
    "Chassis":           "Chassis",
    "Obstacles":         "Obstacles",
    "CloudDeviceMsg":    "CloudDevMsg",
}


class A1MessageFlowPanel(QWidget):
    """A1 消息流实时监视面板 — 独立浮窗

    显示:
      - 9 个 topic 的实时消息计数 + 频率
      - 最近 N 条异常事件 (可滚动)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("A1 消息流监视器")
        self.resize(420, 600)
        self.setMinimumSize(320, 400)

        # 统计缓存
        self._topic_stats: dict[str, dict] = {}
        self._anomaly_lines: deque[str] = deque(maxlen=200)

        self._setup_ui()

        # 定时刷新 (2Hz, 降低 UI 负担)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh)
        self._refresh_timer.start(500)

        # 待刷新的标记
        self._dirty: bool = False

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── Topic 流量统计 ──
        flow_group = QGroupBox("Topic 流量")
        flow_group.setStyleSheet(self._group_style())
        flow_layout = QVBoxLayout(flow_group)
        flow_layout.setContentsMargins(4, 4, 4, 4)
        flow_layout.setSpacing(1)

        self._topic_labels: dict[str, QLabel] = {}

        for topic in TOPIC_DISPLAY_NAMES:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            row_layout.setSpacing(4)

            # topic 名
            name_label = QLabel(TOPIC_DISPLAY_NAMES.get(topic, topic))
            name_label.setFixedWidth(80)
            name_label.setStyleSheet(
                "color: #8899bb; font-size: 11px; font-weight: bold;"
            )

            # 状态指示点
            dot = QLabel("●")
            dot.setFixedWidth(14)
            dot.setStyleSheet("color: #444455; font-size: 10px;")

            # 统计数字
            stats_label = QLabel("—")
            stats_label.setStyleSheet("color: #667788; font-size: 11px;")

            row_layout.addWidget(name_label, 0)
            row_layout.addWidget(dot, 0)
            row_layout.addWidget(stats_label, 1)

            self._topic_labels[topic] = stats_label
            flow_layout.addWidget(row)

        layout.addWidget(flow_group)

        # ── 异常事件日志 ──
        anomaly_group = QGroupBox("异常事件")
        anomaly_group.setStyleSheet(self._group_style())
        anomaly_layout = QVBoxLayout(anomaly_group)
        anomaly_layout.setContentsMargins(4, 4, 4, 4)

        self._anomaly_text = QTextEdit()
        self._anomaly_text.setReadOnly(True)
        self._anomaly_text.setStyleSheet("""
            QTextEdit {
                background: #0d0d1f;
                color: #8899aa;
                border: 1px solid #2a3a5c;
                font-size: 11px;
                font-family: "Consolas", "Courier New", monospace;
            }
        """)
        self._anomaly_text.setMinimumHeight(200)
        anomaly_layout.addWidget(self._anomaly_text)

        layout.addWidget(anomaly_group, 1)

        # 样式
        self.setStyleSheet("""
            QWidget { background: #16213e; }
        """)

    # ======================== 公共接口 ========================

    def update_flow(self, event: MessageFlowEvent) -> None:
        """更新消息流量统计"""
        topic = event.topic
        if topic not in self._topic_stats:
            self._topic_stats[topic] = {"count": 0, "last_latency_ms": 0.0}
        self._topic_stats[topic]["count"] = self._topic_stats[topic].get("count", 0) + 1

        # 计算延迟 (wall_time - msg_timestamp)
        if event.timestamp > 0:
            latency_ms = (event.wall_time - event.timestamp) * 1000
            self._topic_stats[topic]["last_latency_ms"] = max(0.0, latency_ms)

        self._dirty = True

    def update_anomaly(self, event: AnomalyEvent) -> None:
        """添加一条异常事件"""
        color = severity_color(event.severity)
        sev_name = event.severity.name[:4]  # INFO, WARN, ERRO, CRIT
        line = (
            f'<span style="color:#556688;">[{event.timestamp:.1f}]</span> '
            f'<span style="color:{color};">[{sev_name}]</span> '
            f'{event.case_id}: {event.message}'
        )
        self._anomaly_lines.append(line)
        self._dirty = True

    def update_from_recorder(self, recorder) -> None:
        """从 A1TestRecorder 批量加载统计 (打开面板时调用)"""
        summary = recorder.get_summary()
        # 从 flow events 更新 topic 统计
        for topic in TOPIC_DISPLAY_NAMES:
            events = recorder.get_flow_by_topic(topic, n=1)
            if events:
                count = summary.get("total_flow_events", 0)
                self._topic_stats[topic] = {
                    "count": recorder._topic_event_counts().get(topic, 0),
                    "last_latency_ms": 0.0,
                }
        self._dirty = True
        self._on_refresh()

    def reset(self) -> None:
        """重置所有统计"""
        self._topic_stats.clear()
        self._anomaly_lines.clear()
        self._anomaly_text.clear()
        self._dirty = True
        self._on_refresh()

    # ======================== 内部方法 ========================

    def _on_refresh(self) -> None:
        """定时刷新 UI"""
        if not self._dirty:
            return
        self._dirty = False

        # 刷新 topic 统计
        for topic, label in self._topic_labels.items():
            stats = self._topic_stats.get(topic, {})
            count = stats.get("count", 0)
            latency = stats.get("last_latency_ms", 0.0)

            if count == 0:
                label.setText("—")
                label.setStyleSheet("color: #667788; font-size: 11px;")
            else:
                status_color = "#00ff88" if latency < 100 else ("#ffcc00" if latency < 500 else "#ff4444")
                label.setText(f"{count}条  {latency:.0f}ms")
                label.setStyleSheet(f"color: {status_color}; font-size: 11px;")

        # 刷新异常日志
        if self._anomaly_lines:
            html = "<br>".join(self._anomaly_lines)
            self._anomaly_text.setHtml(html)
            # 滚动到底部
            scrollbar = self._anomaly_text.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())

    # ======================== 样式 ========================

    @staticmethod
    def _group_style() -> str:
        return """
            QGroupBox {
                color: #c0d0e0;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #2a3a5c;
                border-radius: 3px;
                margin-top: 6px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 3px;
            }
        """
