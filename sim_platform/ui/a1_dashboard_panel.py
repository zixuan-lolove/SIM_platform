"""A1 测试仪表盘面板 — 总体结果 + 逐用例通过/失败 + 会话统计

遵循现有面板模式 (StatusPanel / FullStackPanel):
  - QGroupBox 分组 + 静态样式方法
  - 公共 update_*() 接口供 MainWindow 调用
  - 深色主题配色
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QScrollArea, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ..a1.a1_types import (
    TestVerdictEntry, AnomalyEvent, Verdict,
    verdict_color, verdict_icon, severity_color,
)


class A1DashboardPanel(QWidget):
    """A1 测试用例仪表盘 — 右侧面板

    显示:
      - 总体结果 (PASS/FAIL/WARN 汇总)
      - 10 条用例逐条状态
      - 会话统计
    """

    case_selected = pyqtSignal(str)  # case_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._case_labels: dict[str, QLabel] = {}     # 每条的 verdict 标签
        self._case_names: dict[str, QLabel] = {}       # 每条的用例名称+描述
        self._verdict_counts: dict[str, dict[str, int]] = {}  # {case_id: {pass:n, fail:n, ...}}

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ── 标题 ──
        title = QLabel("A1 数据隔离测试")
        title.setStyleSheet("color: #e0e8f0; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # ── 总体结果 ──
        overall_group = QGroupBox("总体结果")
        overall_group.setStyleSheet(self._group_style())
        overall_layout = QHBoxLayout(overall_group)
        overall_layout.setContentsMargins(8, 12, 8, 12)

        self._overall_label = QLabel("—")
        self._overall_label.setAlignment(Qt.AlignCenter)
        self._overall_label.setStyleSheet(
            "color: #667788; font-size: 32px; font-weight: bold;"
        )
        overall_layout.addWidget(self._overall_label)
        layout.addWidget(overall_group)

        # ── 测试用例列表 (可滚动) ──
        case_group = QGroupBox("测试用例")
        case_group.setStyleSheet(self._group_style())
        case_layout = QVBoxLayout(case_group)
        case_layout.setContentsMargins(4, 4, 4, 4)
        case_layout.setSpacing(1)

        # 用例编号与名称
        A1_CASES = [
            ("A1-01", "数据分类准确性"),
            ("A1-02", "时间戳精度完整性"),
            ("A1-03", "周期性数据处理"),
            ("A1-04", "延迟检测上报"),
            ("A1-05", "故障处理动作"),
            ("A1-06", "参考线中断处理"),
            ("A1-07", "曲率突变过滤"),
            ("A1-08", "航向角跳变检测"),
            ("A1-09", "起点过远重规划"),
            ("A1-10", "缺失字段重下发"),
        ]

        for case_id, name in A1_CASES:
            row = QFrame()
            row.setFrameShape(QFrame.NoFrame)
            row.setStyleSheet(
                "QFrame { background: transparent; border-bottom: 1px solid #1e2d44; }"
                "QFrame:hover { background: #1a2a44; }"
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(4)

            # 状态图标
            icon_label = QLabel("—")
            icon_label.setFixedWidth(20)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setStyleSheet("color: #667788; font-size: 14px; font-weight: bold;")
            self._case_labels[case_id] = icon_label

            # 编号 + 名称
            name_label = QLabel(f"{case_id}  {name}")
            name_label.setStyleSheet("color: #b0c0d0; font-size: 12px;")
            self._case_names[case_id] = name_label

            row_layout.addWidget(icon_label, 0)
            row_layout.addWidget(name_label, 1)

            case_layout.addWidget(row)

        # 包装在 QScrollArea 中
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(case_group)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(scroll, 1)

        # ── 会话统计 ──
        stats_group = QGroupBox("会话统计")
        stats_group.setStyleSheet(self._group_style())
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setContentsMargins(6, 6, 6, 6)
        stats_layout.setSpacing(2)

        self._stats_pass = QLabel("PASS: —")
        self._stats_fail = QLabel("FAIL: —")
        self._stats_warn = QLabel("WARN: —")
        self._stats_total = QLabel("总计: —")
        for lbl in [self._stats_pass, self._stats_fail,
                     self._stats_warn, self._stats_total]:
            lbl.setStyleSheet(self._label_style())
            stats_layout.addWidget(lbl)

        layout.addWidget(stats_group)

    # ======================== 公共接口 ========================

    def update_verdict(self, entry: TestVerdictEntry) -> None:
        """处理一条新的判定结果"""
        case_id = entry.case_id
        if case_id not in self._case_labels:
            return

        # 更新用例状态
        color = verdict_color(entry.verdict)
        icon = verdict_icon(entry.verdict)
        self._case_labels[case_id].setText(icon)
        self._case_labels[case_id].setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: bold;"
        )
        self._case_labels[case_id].setToolTip(entry.message)

        # 更新统计
        if case_id not in self._verdict_counts:
            self._verdict_counts[case_id] = {"pass": 0, "fail": 0, "warn": 0, "pending": 0, "skipped": 0}
        key = entry.verdict.name.lower()
        self._verdict_counts[case_id][key] = self._verdict_counts[case_id].get(key, 0) + 1

        self._refresh_overall()
        self._refresh_stats()

    def update_summary(self, summary: dict) -> None:
        """批量更新 (仿真停止时调用)"""
        by_case = summary.get("by_case", {})
        last_verdict = summary.get("last_case_verdict", {})

        for case_id, counts in by_case.items():
            if case_id not in self._case_labels:
                continue
            self._verdict_counts[case_id] = counts

        for case_id, vname in last_verdict.items():
            if case_id in self._case_labels:
                v = Verdict[vname] if vname in Verdict.__members__ else Verdict.PENDING
                color = verdict_color(v)
                icon = verdict_icon(v)
                self._case_labels[case_id].setText(icon)
                self._case_labels[case_id].setStyleSheet(
                    f"color: {color}; font-size: 14px; font-weight: bold;"
                )

        self._refresh_overall()
        self._refresh_stats()

    def reset(self) -> None:
        """重置所有显示"""
        for case_id in self._case_labels:
            self._case_labels[case_id].setText("—")
            self._case_labels[case_id].setStyleSheet(
                "color: #667788; font-size: 14px; font-weight: bold;"
            )
            self._case_labels[case_id].setToolTip("")

        self._verdict_counts.clear()
        self._overall_label.setText("—")
        self._overall_label.setStyleSheet(
            "color: #667788; font-size: 32px; font-weight: bold;"
        )
        self._stats_pass.setText("PASS: —")
        self._stats_fail.setText("FAIL: —")
        self._stats_warn.setText("WARN: —")
        self._stats_total.setText("总计: —")

    # ======================== 内部方法 ========================

    def _refresh_overall(self) -> None:
        """刷新总体结果"""
        total_pass = 0
        total_fail = 0
        total_warn = 0

        for counts in self._verdict_counts.values():
            total_pass += counts.get("pass", 0)
            total_fail += counts.get("fail", 0)
            total_warn += counts.get("warn", 0)

        if total_fail > 0:
            text = "FAIL"
            color = "#ff4444"
        elif total_warn > 0:
            text = "WARN"
            color = "#ffcc00"
        elif total_pass > 0:
            text = "PASS"
            color = "#00ff88"
        else:
            text = "—"
            color = "#667788"

        self._overall_label.setText(text)
        self._overall_label.setStyleSheet(
            f"color: {color}; font-size: 32px; font-weight: bold;"
        )

    def _refresh_stats(self) -> None:
        """刷新会话统计"""
        total_pass = sum(c.get("pass", 0) for c in self._verdict_counts.values())
        total_fail = sum(c.get("fail", 0) for c in self._verdict_counts.values())
        total_warn = sum(c.get("warn", 0) for c in self._verdict_counts.values())
        total_all = total_pass + total_fail + total_warn

        self._stats_pass.setText(
            f'PASS: <span style="color:#00ff88;">{total_pass}</span>'
        )
        self._stats_fail.setText(
            f'FAIL: <span style="color:#ff4444;">{total_fail}</span>'
        )
        self._stats_warn.setText(
            f'WARN: <span style="color:#ffcc00;">{total_warn}</span>'
        )
        self._stats_total.setText(f"总计: {total_all}")

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

    @staticmethod
    def _label_style() -> str:
        return "color: #b0c0d0; font-size: 12px; background: transparent; padding: 1px 0px;"
