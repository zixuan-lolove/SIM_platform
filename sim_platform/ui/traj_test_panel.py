"""轨迹测试面板 — 非全栈模式下加载 .traj 文件并验证 A1-06/A1-07

独立于全栈仿真，可随时打开使用。
依赖: TrajParser, ReferenceLineManager, A1ValidationRules, matplotlib
"""

import json
import logging
import math
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QPushButton, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor

logger = logging.getLogger(__name__)

# matplotlib 嵌入 PyQt5 (延迟导入避免 NumPy/PyQt5 版本冲突)
_HAS_MPL = False
FigureCanvas = None
Figure = None

def _try_import_mpl() -> bool:
    """延迟加载 matplotlib，避免启动时的 NumPy 版本冲突"""
    global _HAS_MPL, FigureCanvas, Figure
    if _HAS_MPL:
        return True
    try:
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as _FC
        from matplotlib.figure import Figure as _Fig
        FigureCanvas = _FC
        Figure = _Fig
        _HAS_MPL = True
        return True
    except Exception:
        logger.warning("matplotlib 不可用，图表功能禁用")
        return False

from ..gateway_sim.traj_parser import TrajParser
from ..gateway_sim.reference_line_mgr import ReferenceLineManager
from ..a1.a1_test_registry import A1ValidationRules
from ..a1.a1_types import Verdict, verdict_color, verdict_icon
from ..models.sim_messages import TrajPoint, TaskTraj
from ..planning_sim.b_spline_smoother import BSplineSmoother


class TrajTestPanel(QWidget):
    """轨迹测试面板 — A1-06 航向跳变 + A1-07 起点距离

    用法:
        panel = TrajTestPanel()
        panel.set_map_view(map_view)       # 注入地图引用
        panel.set_vehicle_pose(x, y)        # 设置车辆位置 (用于 A1-07)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # ── 数据 ──
        self._traj_points: list[TrajPoint] = []
        self._ref_mgr: Optional[ReferenceLineManager] = None
        self._traj_file_path: str = ""
        self._vehicle_x: float = 0.0
        self._vehicle_y: float = 0.0

        # 验证结果缓存
        self._heading_anomalies: list = []
        self._start_dist_verdicts: list = []

        # MapView 引用
        self._map_view = None

        self._setup_ui()

    # ══════════════════════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════════════════════

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── 标题 ──
        title = QLabel("轨迹测试 — A1-06 / A1-07")
        title.setStyleSheet("color: #e0e8f0; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # ── 文件加载区 ──
        file_group = QGroupBox("轨迹文件")
        file_group.setStyleSheet(self._group_style())
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(6, 8, 6, 8)
        file_layout.setSpacing(4)

        btn_layout = QHBoxLayout()
        self._load_btn = QPushButton("📂 加载 .traj")
        self._load_btn.setStyleSheet(self._btn_style())
        self._load_btn.clicked.connect(self._on_load_traj)
        btn_layout.addWidget(self._load_btn)

        self._clear_btn = QPushButton("清除")
        self._clear_btn.setStyleSheet(self._btn_style())
        self._clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self._clear_btn)

        file_layout.addLayout(btn_layout)

        self._file_label = QLabel("未加载文件")
        self._file_label.setStyleSheet("color: #8899aa; font-size: 11px;")
        self._file_label.setWordWrap(True)
        file_layout.addWidget(self._file_label)

        layout.addWidget(file_group)

        # ── A1-06 结果区 ──
        a106_group = QGroupBox("A1-06 航向跳变检测 (>10°)")
        a106_group.setStyleSheet(self._group_style())
        a106_layout = QVBoxLayout(a106_group)
        a106_layout.setContentsMargins(4, 6, 4, 6)
        a106_layout.setSpacing(2)

        self._a106_table = QTableWidget(0, 2)
        self._a106_table.setHorizontalHeaderLabels(["指标", "值"])
        self._a106_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._a106_table.verticalHeader().setVisible(False)
        self._a106_table.setMaximumHeight(120)
        self._a106_table.setStyleSheet(self._table_style())
        a106_layout.addWidget(self._a106_table)

        layout.addWidget(a106_group)

        # ── A1-07 结果区 ──
        a107_group = QGroupBox("A1-07 起点距离 (≤3m)")
        a107_group.setStyleSheet(self._group_style())
        a107_layout = QVBoxLayout(a107_group)
        a107_layout.setContentsMargins(4, 6, 4, 6)
        a107_layout.setSpacing(2)

        self._a107_table = QTableWidget(0, 2)
        self._a107_table.setHorizontalHeaderLabels(["指标", "值"])
        self._a107_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._a107_table.verticalHeader().setVisible(False)
        self._a107_table.setMaximumHeight(100)
        self._a107_table.setStyleSheet(self._table_style())
        a107_layout.addWidget(self._a107_table)

        layout.addWidget(a107_group)

        # ── matplotlib 图表区 ──
        chart_group = QGroupBox("航向角沿轨迹分布")
        chart_group.setStyleSheet(self._group_style())
        chart_layout = QVBoxLayout(chart_group)
        chart_layout.setContentsMargins(2, 4, 2, 2)

        if _try_import_mpl():
            self._figure = Figure(figsize=(5, 3), dpi=90, facecolor='#1a1a2e')
            self._ax = self._figure.add_subplot(111)
            self._ax.set_facecolor('#16213e')
            self._figure.tight_layout(pad=2.0)
            self._canvas = FigureCanvas(self._figure)
            self._canvas.setMinimumHeight(200)
            chart_layout.addWidget(self._canvas)
            self._draw_empty_chart()
        else:
            no_mpl = QLabel("(matplotlib 不可用)")
            no_mpl.setStyleSheet("color: #667788; font-size: 11px;")
            no_mpl.setAlignment(Qt.AlignCenter)
            chart_layout.addWidget(no_mpl)
            self._canvas = None

        layout.addWidget(chart_group)

        # ── 操作按钮 ──
        action_layout = QHBoxLayout()

        self._revalidate_btn = QPushButton("🔄 重新验证")
        self._revalidate_btn.setStyleSheet(self._btn_style())
        self._revalidate_btn.clicked.connect(self._run_validations)
        self._revalidate_btn.setEnabled(False)
        action_layout.addWidget(self._revalidate_btn)

        self._export_btn = QPushButton("📤 导出报告")
        self._export_btn.setStyleSheet(self._btn_style())
        self._export_btn.clicked.connect(self._export_report)
        self._export_btn.setEnabled(False)
        action_layout.addWidget(self._export_btn)

        layout.addLayout(action_layout)

        # ── 状态 ──
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #667788; font-size: 11px;")
        layout.addWidget(self._status_label)

        layout.addStretch()

    # ══════════════════════════════════════════════════════════════
    # 公共接口
    # ══════════════════════════════════════════════════════════════

    def set_map_view(self, map_view):
        """注入地图视图引用"""
        self._map_view = map_view

    def set_vehicle_pose(self, x: float, y: float):
        """更新车辆位置 (由外部仿真循环调用)，触发 A1-07 重新验证"""
        if abs(x - self._vehicle_x) > 0.01 or abs(y - self._vehicle_y) > 0.01:
            self._vehicle_x = x
            self._vehicle_y = y
            if self._traj_points:
                self._validate_a107()

    # ══════════════════════════════════════════════════════════════
    # 核心逻辑
    # ══════════════════════════════════════════════════════════════

    def _on_load_traj(self):
        """打开 .traj 文件选择对话框"""
        logger.info("[TrajTestPanel] _on_load_traj called")

        start_dir = str(Path(__file__).resolve().parent.parent.parent)
        if self._traj_file_path:
            p = Path(self._traj_file_path)
            if p.parent.exists():
                start_dir = str(p.parent)
        if not Path(start_dir).exists():
            start_dir = str(Path.home())

        # 扫描 start_dir 及其直接子目录下的 .traj 文件
        candidates = []
        base = Path(start_dir)
        try:
            for f in sorted(base.glob("*.traj")):
                candidates.append(str(f))
            # 也扫描一层子目录 (如 task_file/*/)
            for sub in sorted(base.iterdir()):
                if sub.is_dir():
                    for f in sorted(sub.glob("*.traj")):
                        candidates.append(str(f))
        except PermissionError:
            pass

        # 显示内置文件列表对话框
        from PyQt5.QtWidgets import QDialog, QListWidget, QDialogButtonBox, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("选择轨迹文件 (.traj)")
        dlg.resize(600, 400)
        dlg_layout = QVBoxLayout(dlg)

        list_widget = QListWidget()
        if candidates:
            for c in candidates:
                list_widget.addItem(str(Path(c).relative_to(base)))
            list_widget.setCurrentRow(0)
        else:
            list_widget.addItem("(未找到 .traj 文件，请使用下方路径输入)")
        dlg_layout.addWidget(QLabel(f"目录: {start_dir}"))
        dlg_layout.addWidget(list_widget)

        # 手动路径输入
        dlg_layout.addWidget(QLabel("或输入文件路径:"))
        path_input = QLineEdit()
        path_input.setPlaceholderText("/home/zy/SIM/test_a1_heading_jump.traj")
        dlg_layout.addWidget(path_input)

        # 也提供原生浏览按钮 (兜底)
        browse_btn = QPushButton("浏览...")
        def _browse():
            p, _ = QFileDialog.getOpenFileName(
                dlg, "选择轨迹文件", start_dir,
                "所有文件 (*)",
                options=QFileDialog.DontUseNativeDialog,
            )
            if p:
                path_input.setText(p)
        browse_btn.clicked.connect(_browse)
        dlg_layout.addWidget(browse_btn)

        # 确定/取消
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btn_box)

        # 双击列表项直接加载
        def _on_double_click(item):
            rel = item.text()
            full = str(base / rel)
            if Path(full).exists():
                dlg.accept()
        list_widget.itemDoubleClicked.connect(_on_double_click)

        if dlg.exec_() != QDialog.Accepted:
            logger.info("[TrajTestPanel] Dialog cancelled")
            return

        # 优先使用列表选择，其次使用手动输入
        path = ""
        if list_widget.currentItem() and candidates:
            idx = list_widget.currentRow()
            if 0 <= idx < len(candidates):
                path = candidates[idx]
        if not path and path_input.text().strip():
            path = path_input.text().strip()
        if not path:
            return

        logger.info(f"[TrajTestPanel] Selected: {path}")
        self._load_traj_file(path)

    def _load_traj_file(self, path: str):
        """解析并验证 .traj 文件 (可从对话框或直接路径调用)"""
        # 校验扩展名
        if not path.lower().endswith(".traj"):
            QMessageBox.warning(
                self, "文件类型错误",
                f"请选择 .traj 格式的轨迹文件。\n当前文件: {Path(path).name}"
            )
            return

        logger.info(f"[TrajTestPanel] Parsing: {path}")
        try:
            parser = TrajParser()
            task_traj = parser.parse_file(path)
            if not task_traj.points:
                raise ValueError("轨迹文件无有效数据点")

            self._traj_points = task_traj.points
            self._traj_file_path = path
            self._file_label.setText(
                f"📄 {Path(path).name}\n{len(self._traj_points)} 个轨迹点"
            )

            # 用 ReferenceLineManager 分段
            self._ref_mgr = ReferenceLineManager()
            self._ref_mgr.update_from_task(task_traj)

            # 地图: 绘制参考线
            self._update_map_overlay()

            # 运行验证
            self._run_validations()

            self._status_label.setText(
                f"✓ 已加载: {Path(path).name} ({len(self._traj_points)} 点)"
            )
            self._status_label.setStyleSheet("color: #00ff88; font-size: 11px;")
            logger.info(
                f"[TrajTestPanel] Loaded {len(self._traj_points)} points, "
                f"A1-06 anomalies={len(self._heading_anomalies)}"
            )

        except Exception as e:
            logger.exception("[TrajTestPanel] Failed to load .traj")
            QMessageBox.warning(self, "加载失败", f"无法解析轨迹文件:\n{e}")
            self._status_label.setText(f"✗ 加载失败: {e}")
            self._status_label.setStyleSheet("color: #ff4444; font-size: 11px;")

    def _on_clear(self):
        """清除当前轨迹"""
        self._traj_points = []
        self._ref_mgr = None
        self._traj_file_path = ""
        self._heading_anomalies = []
        self._start_dist_verdicts = []
        self._file_label.setText("未加载文件")
        self._a106_table.setRowCount(0)
        self._a107_table.setRowCount(0)
        self._revalidate_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._status_label.setText("就绪")
        self._status_label.setStyleSheet("color: #667788; font-size: 11px;")

        if self._map_view:
            self._map_view.clear_reference_trajectory()

        if self._canvas:
            self._draw_empty_chart()

    def _run_validations(self):
        """执行 A1-06 + A1-07 验证"""
        if not self._traj_points:
            return

        self._validate_a106()
        self._validate_a107()
        self._update_chart()

        self._revalidate_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

    def _validate_a106(self):
        """A1-06: 航向角跳变检测"""
        self._heading_anomalies = A1ValidationRules.validate_heading_jump(
            self._traj_points
        )

        # 计算最大跳变
        max_delta = 0.0
        jump_positions = []
        for a in self._heading_anomalies:
            d = a.details.get("delta_deg", 0.0)
            if d > max_delta:
                max_delta = d
            jump_positions.append(str(a.details.get("point_index", "?")))

        # 刷新表格
        rows = [
            ("异常点数", str(len(self._heading_anomalies))),
            ("最大跳变", f"{max_delta:.1f}°"),
            ("跳变位置", ", ".join(jump_positions) if jump_positions else "—"),
            ("判定", self._a106_verdict()),
        ]
        self._populate_table(self._a106_table, rows)

    def _a106_verdict(self) -> str:
        """A1-06 综合判定文字"""
        if not self._heading_anomalies:
            return "✅ PASS — 未检测到航向跳变"
        return f"⚠ WARNING — {len(self._heading_anomalies)} 处航向跳变 > 10°"

    def _validate_a107(self):
        """A1-07: 起点距离检查"""
        if not self._traj_points:
            return

        first_pt = self._traj_points[0]
        rx, ry = first_pt.x, first_pt.y
        dist = math.hypot(rx - self._vehicle_x, ry - self._vehicle_y)

        verdicts = A1ValidationRules.validate_start_point_distance(
            self._vehicle_x, self._vehicle_y, rx, ry, 0.0
        )
        self._start_dist_verdicts = verdicts

        v = verdicts[0]
        verdict_text = f"{verdict_icon(v.verdict)} {v.verdict.name}"

        rows = [
            ("车辆位置", f"({self._vehicle_x:.1f}, {self._vehicle_y:.1f})"),
            ("参考线起点", f"({rx:.1f}, {ry:.1f})"),
            ("距离", f"{dist:.1f}m (阈值: 3m)"),
            ("判定", verdict_text),
        ]
        self._populate_table(self._a107_table, rows)

        # 更新地图上的起点标记和距离线
        if self._map_view:
            self._map_view.set_ref_start_marker(rx, ry)
            self._map_view.set_distance_line(
                self._vehicle_x, self._vehicle_y, rx, ry
            )

    # ══════════════════════════════════════════════════════════════
    # 地图集成
    # ══════════════════════════════════════════════════════════════

    def _update_map_overlay(self):
        """将原始+平滑参考线绘制到 MapView，含航向箭头"""
        if not self._map_view or not self._traj_points:
            return

        # 原始轨迹 (亮绿线+黑色箭头)
        xs = [p.x for p in self._traj_points]
        ys = [p.y for p in self._traj_points]
        hdgs = [p.theta for p in self._traj_points]
        self._map_view.set_reference_trajectory(xs, ys, headings=hdgs)

        # Clamped B 样条平滑 (锁端点)
        try:
            task_traj = TaskTraj(task_id="smooth")
            task_traj.points = list(self._traj_points)
            smoother = BSplineSmoother(ctrl_step=4)
            smoothed = smoother.smooth(task_traj)

            sx = [p.x for p in smoothed.points]
            sy = [p.y for p in smoothed.points]
            sh = [p.theta for p in smoothed.points]
            self._map_view.set_smoothed_trajectory(sx, sy, sh)
            logger.info(f"[TrajTestPanel] Smoothed: {len(smoothed.points)} pts")
        except Exception as e:
            logger.warning(f"[TrajTestPanel] Smoothing failed: {e}")

        # A1-06 异常标记
        anomaly_markers = []
        for a in self._heading_anomalies:
            idx = a.details.get("point_index", -1)
            if 0 <= idx < len(self._traj_points):
                p = self._traj_points[idx]
                anomaly_markers.append((p.x, p.y))
        self._map_view.set_anomaly_markers(anomaly_markers)

        # 标记起点
        if self._traj_points:
            first = self._traj_points[0]
            self._map_view.set_ref_start_marker(first.x, first.y)

    # ══════════════════════════════════════════════════════════════
    # matplotlib 图表
    # ══════════════════════════════════════════════════════════════

    def _draw_empty_chart(self):
        """绘制空白占位图"""
        if not self._canvas:
            return
        self._ax.clear()
        self._ax.set_facecolor('#16213e')
        self._ax.set_title("请加载 .traj 文件", color='#8899aa', fontsize=11)
        self._ax.set_xlabel("轨迹点序号", color='#667788')
        self._ax.set_ylabel("航向角 (°)", color='#667788')
        self._ax.tick_params(colors='#667788', labelsize=8)
        self._ax.grid(True, alpha=0.15, color='#ffffff')
        self._figure.tight_layout(pad=2.0)
        self._canvas.draw()

    def _update_chart(self):
        """绘制航向角沿轨迹分布图"""
        if not self._canvas or not self._traj_points:
            return

        self._ax.clear()
        self._ax.set_facecolor('#16213e')

        n = len(self._traj_points)
        indices = list(range(n))

        # 航向角 (度)
        headings_deg = []
        for pt in self._traj_points:
            if hasattr(pt, 'theta'):
                headings_deg.append(math.degrees(pt.theta))
            else:
                headings_deg.append(pt.heading if hasattr(pt, 'heading') else 0.0)

        self._ax.plot(indices, headings_deg, '-', color='#00d4ff', linewidth=1.2,
                      alpha=0.9, label='航向角')

        # 标注跳变点
        jump_indices = []
        jump_values = []
        for a in self._heading_anomalies:
            idx = a.details.get("point_index", -1)
            if 0 <= idx < n:
                jump_indices.append(idx)
                jump_values.append(headings_deg[idx])

        if jump_indices:
            self._ax.scatter(jump_indices, jump_values, c='#ff4444', s=40,
                             marker='*', zorder=5, label=f'跳变点 ({len(jump_indices)}处)')

        # 阈值参考线 (水平虚线表示 ±10° 跳变概念，这里显示航向范围)
        if headings_deg:
            mean_h = sum(headings_deg) / len(headings_deg)
            self._ax.axhline(y=mean_h + 10, color='#ff6644', linestyle='--',
                             linewidth=0.8, alpha=0.6, label='+10° 阈值偏移')
            self._ax.axhline(y=mean_h - 10, color='#ff6644', linestyle='--',
                             linewidth=0.8, alpha=0.6, label='-10° 阈值偏移')

        self._ax.set_title(f"航向角沿轨迹分布 ({n} 点)", color='#e0e8f0', fontsize=11)
        self._ax.set_xlabel("轨迹点序号", color='#667788')
        self._ax.set_ylabel("航向角 (°)", color='#667788')
        self._ax.tick_params(colors='#667788', labelsize=8)
        self._ax.grid(True, alpha=0.15, color='#ffffff')
        self._ax.legend(loc='upper right', fontsize=7,
                        facecolor='#1a1a2e', edgecolor='#333355',
                        labelcolor='#cccccc')

        self._figure.tight_layout(pad=2.0)
        self._canvas.draw()

    # ══════════════════════════════════════════════════════════════
    # 报告导出
    # ══════════════════════════════════════════════════════════════

    def _export_report(self):
        """导出 JSON 测试报告"""
        if not self._traj_points:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出测试报告", "traj_test_report.json",
            "JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            report = self._build_report()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            self._status_label.setText(f"✓ 报告已导出: {Path(path).name}")
            self._status_label.setStyleSheet("color: #00ff88; font-size: 11px;")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _build_report(self) -> dict:
        """构建测试报告数据结构"""
        n = len(self._traj_points)

        # 航向数据
        headings_deg = []
        for pt in self._traj_points:
            if hasattr(pt, 'theta') and abs(pt.theta) > 1e-9:
                headings_deg.append(round(math.degrees(pt.theta), 2))
            else:
                headings_deg.append(round(pt.heading, 2) if hasattr(pt, 'heading') else 0.0)

        first = self._traj_points[0]
        dist = math.hypot(first.x - self._vehicle_x, first.y - self._vehicle_y)

        a107_v = self._start_dist_verdicts[0] if self._start_dist_verdicts else None

        return {
            "meta": {
                "test_suite": "T-A1-06 & T-A1-07",
                "document_version": "v0.3",
                "traj_file": self._traj_file_path,
                "total_points": n,
                "vehicle_position": (round(self._vehicle_x, 2), round(self._vehicle_y, 2)),
            },
            "A1-06_heading_jump": {
                "threshold_deg": 10.0,
                "anomaly_count": len(self._heading_anomalies),
                "max_delta_deg": max(
                    (a.details.get("delta_deg", 0.0) for a in self._heading_anomalies),
                    default=0.0
                ),
                "anomalies": [
                    {
                        "point_index": a.details.get("point_index"),
                        "delta_deg": a.details.get("delta_deg"),
                        "prev_deg": a.details.get("prev_deg"),
                        "curr_deg": a.details.get("curr_deg"),
                    }
                    for a in self._heading_anomalies
                ],
            },
            "A1-07_start_distance": {
                "threshold_m": 3.0,
                "distance_m": round(dist, 2),
                "verdict": a107_v.verdict.name if a107_v else "N/A",
                "ref_start": (round(first.x, 2), round(first.y, 2)),
            },
            "heading_profile": [
                {"index": i, "heading_deg": h} for i, h in enumerate(headings_deg)
            ],
        }

    # ══════════════════════════════════════════════════════════════
    # UI 辅助
    # ══════════════════════════════════════════════════════════════

    def _populate_table(self, table: QTableWidget, rows: list[tuple[str, str]]):
        """填充结果表格"""
        table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            key_item = QTableWidgetItem(key)
            key_item.setForeground(QColor("#8899aa"))
            key_item.setFlags(Qt.ItemIsEnabled)
            val_item = QTableWidgetItem(value)
            val_item.setForeground(QColor("#e0e8f0"))
            val_item.setFlags(Qt.ItemIsEnabled)
            table.setItem(i, 0, key_item)
            table.setItem(i, 1, val_item)

    @staticmethod
    def _group_style() -> str:
        return """
            QGroupBox {
                color: #c0d0e0;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #30363d;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """

    @staticmethod
    def _btn_style() -> str:
        return """
            QPushButton {
                background: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #30363d;
                border-color: #58a6ff;
            }
            QPushButton:disabled {
                color: #555;
                background: #1a1a1a;
            }
        """

    @staticmethod
    def _table_style() -> str:
        return """
            QTableWidget {
                background: #0d1117;
                color: #e0e8f0;
                border: 1px solid #30363d;
                gridline-color: #21262d;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 2px 6px;
            }
            QHeaderView::section {
                background: #161b22;
                color: #8899aa;
                border: none;
                padding: 4px;
                font-size: 10px;
            }
        """
