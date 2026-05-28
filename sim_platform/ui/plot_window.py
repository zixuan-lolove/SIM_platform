"""数据曲线图窗 — 每个信号独立图窗，实时绘制时间序列"""

import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel,
    QCheckBox, QToolBar, QAction, QApplication,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QKeySequence

from ..core.data_logger import DataLogger

# 信号目录：类别 → [(key, 显示名, 单位)]
SIGNAL_CATALOG = {
    "车辆状态": [
        ("vehicle.speed", "车速", "km/h"),
        ("vehicle.accel", "加速度", "m/s²"),
        ("vehicle.yaw_rate", "横摆角速度", "deg/s"),
        ("vehicle.steer", "前轮转角", "deg"),
        ("vehicle.brake_pressure", "制动压力", "MPa"),
    ],
    "位置姿态": [
        ("position.x", "X 坐标", "m"),
        ("position.y", "Y 坐标", "m"),
        ("position.heading", "航向角", "deg"),
    ],
    "控制指令": [
        ("control.target_speed", "目标车速", "km/h"),
        ("control.steer_sw", "方向盘转角", "deg"),
        ("control.throttle", "油门", "%"),
        ("control.brake", "制动", "%"),
    ],
    "跟踪误差": [
        ("error.cross_track", "横向偏差", "m"),
        ("error.heading", "航向偏差", "deg"),
        ("error.speed", "速度偏差", "km/h"),
    ],
}

CURVE_COLORS = [
    (0, 255, 100), (255, 180, 0), (0, 200, 255),
    (255, 80, 80), (200, 140, 255), (255, 255, 80),
    (80, 200, 255), (255, 120, 180), (100, 255, 180),
    (255, 200, 100),
]

# key → (display_name, color_index)
_SIG_META: dict[str, tuple[str, int]] = {}
_color_idx = 0
for _cat, _sigs in SIGNAL_CATALOG.items():
    for _key, _name, _unit in _sigs:
        _SIG_META[_key] = (f"{_name} ({_unit})", _color_idx)
        _color_idx += 1


class SignalPlotWindow(QMainWindow):
    """单个信号的独立图窗"""

    def __init__(self, key: str, logger: DataLogger, parent=None):
        super().__init__(parent)
        self._key = key
        self._logger = logger
        self._refresh_hz = 20

        display, color_idx = _SIG_META.get(key, (key, 0))
        self._display = display
        self._color = CURVE_COLORS[color_idx % len(CURVE_COLORS)]

        self.setWindowTitle(display)
        self.resize(800, 450)
        self.setMinimumSize(400, 250)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- 工具栏 ---
        toolbar = QToolBar("缩放")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._action_x_out = QAction("X−", self)
        self._action_x_out.triggered.connect(lambda: self._zoom_x(2.0))
        toolbar.addAction(self._action_x_out)

        self._action_x_in = QAction("X+", self)
        self._action_x_in.triggered.connect(lambda: self._zoom_x(0.5))
        toolbar.addAction(self._action_x_in)

        toolbar.addSeparator()

        self._action_y_out = QAction("Y−", self)
        self._action_y_out.triggered.connect(lambda: self._zoom_y(2.0))
        toolbar.addAction(self._action_y_out)

        self._action_y_in = QAction("Y+", self)
        self._action_y_in.triggered.connect(lambda: self._zoom_y(0.5))
        toolbar.addAction(self._action_y_in)

        toolbar.addSeparator()

        action_reset = QAction("↺ 重置", self)
        action_reset.setShortcut(QKeySequence(Qt.Key_Space))
        action_reset.triggered.connect(self._reset_view)
        toolbar.addAction(action_reset)

        # 提示标签
        hint = QLabel("  空格=重置视图  滚轮=缩放  右键拖拽=平移  ")
        hint.setStyleSheet("color: #667788; font-size: 11px;")
        toolbar.addWidget(hint)

        # 暂停滚动
        self._pause_cb = QCheckBox("暂停滚动")
        self._pause_cb.setStyleSheet("color: #c0c8d0; margin-left: 12px;")
        toolbar.addWidget(self._pause_cb)

        # --- 绘图区 ---
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#0d0d1f")
        self._plot.getAxis("bottom").setPen(pg.mkPen(color="#556688", width=1))
        self._plot.getAxis("left").setPen(pg.mkPen(color="#556688", width=1))
        self._plot.getAxis("bottom").setTextPen(pg.mkPen(color="#8899aa"))
        self._plot.getAxis("left").setTextPen(pg.mkPen(color="#8899aa"))
        self._plot.setLabel("bottom", "仿真时间", units="s")
        self._plot.setLabel("left", self._display)
        self._plot.showGrid(x=True, y=True, alpha=0.2)

        self._curve = self._plot.plot(
            [], [],
            pen=pg.mkPen(color=self._color, width=2.0),
            name=self._display,
        )
        layout.addWidget(self._plot)

        # 样式
        self.setStyleSheet("""
            QMainWindow { background: #0d0d1f; }
            QToolBar {
                background: #16213e; border-bottom: 1px solid #2a3a5c;
                spacing: 2px; padding: 2px 4px;
            }
            QToolBar QToolButton {
                color: #e0e8f0; font-size: 13px; font-weight: bold;
                padding: 2px 8px; border: 1px solid #2a3a5c; border-radius: 3px;
                background: #1a2a44;
            }
            QToolBar QToolButton:hover { background: #2a3a5c; }
            QToolBar QToolButton:pressed { background: #1a2a44; }
        """)

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(int(1000 / self._refresh_hz))

    def _refresh(self):
        if not self._logger:
            return
        times, values = self._logger.get_signal(self._key)
        if times:
            self._curve.setData(times, values)
        if not self._pause_cb.isChecked() and times:
            self._plot.setXRange(max(0, times[-1] - 15), times[-1] + 0.5, padding=0)

    def _zoom_x(self, factor: float):
        """factor < 1 = 放大, > 1 = 缩小"""
        self._plot.getViewBox().scaleBy((factor, 1))

    def _zoom_y(self, factor: float):
        self._plot.getViewBox().scaleBy((1, factor))

    def _reset_view(self):
        self._plot.getViewBox().autoRange()

    def set_logger(self, logger: DataLogger):
        self._logger = logger

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class PlotWindow(QMainWindow):
    """信号选择器 — 勾选信号后弹出独立图窗"""

    def __init__(self, data_logger: DataLogger, parent=None):
        super().__init__(parent)
        self._logger = data_logger
        self._windows: dict[str, SignalPlotWindow] = {}

        self.setWindowTitle("信号选择")
        self.resize(280, 500)
        self.setMinimumSize(240, 300)

        self._setup_ui()

    def _setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("数据信号")
        title.setStyleSheet("color: #e0e8f0; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet("""
            QTreeWidget { background: #12122a; color: #c0c8d0; border: 1px solid #2a3a5c; }
            QTreeWidget::item { padding: 2px 0; }
            QTreeWidget::item:hover { background: #1a2a44; }
        """)
        self._tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._tree, 1)

        self._populate_tree()

        btn_select_all = QPushButton("全选")
        btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        layout.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("取消全选")
        btn_deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        layout.addWidget(btn_deselect_all)

        self.setStyleSheet("""
            QMainWindow { background: #0d0d1f; }
            QPushButton {
                background: #1a2a44; color: #c0c8d0; border: 1px solid #2a3a5c;
                padding: 4px 8px; font-size: 12px;
            }
            QPushButton:hover { background: #2a3a5c; }
        """)

    def _populate_tree(self):
        self._tree.blockSignals(True)
        for category, signals in SIGNAL_CATALOG.items():
            cat_item = QTreeWidgetItem([category])
            cat_item.setFlags(cat_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            cat_item.setCheckState(0, Qt.Unchecked)
            font = QFont()
            font.setBold(True)
            cat_item.setFont(0, font)
            self._tree.addTopLevelItem(cat_item)

            for key, name, unit in signals:
                sig_item = QTreeWidgetItem([f"{name}  ({unit})"])
                sig_item.setFlags(sig_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                sig_item.setCheckState(0, Qt.Unchecked)
                sig_item.setData(0, Qt.UserRole, key)
                cat_item.addChild(sig_item)

            cat_item.setExpanded(True)
        self._tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if item.childCount() > 0:
            self._tree.blockSignals(True)
            state = item.checkState(0)
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, state)
            self._tree.blockSignals(False)
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        if item.checkState(0) == Qt.Checked:
            self._open_window(key)
        else:
            self._close_window(key)

        self._tree.blockSignals(True)
        parent = item.parent()
        if parent:
            all_checked = all(parent.child(i).checkState(0) == Qt.Checked for i in range(parent.childCount()))
            any_checked = any(parent.child(i).checkState(0) == Qt.Checked for i in range(parent.childCount()))
            if all_checked:
                parent.setCheckState(0, Qt.Checked)
            elif any_checked:
                parent.setCheckState(0, Qt.PartiallyChecked)
            else:
                parent.setCheckState(0, Qt.Unchecked)
        self._tree.blockSignals(False)

    def _open_window(self, key: str):
        if key in self._windows:
            w = self._windows[key]
            w.show()
            w.raise_()
            w.activateWindow()
            return
        w = SignalPlotWindow(key, self._logger)
        w.setAttribute(Qt.WA_DeleteOnClose, True)
        w.destroyed.connect(lambda _=None, k=key: self._on_window_closed(k))
        self._windows[key] = w
        w.show()

    def _close_window(self, key: str):
        w = self._windows.pop(key, None)
        if w is not None:
            w._timer.stop()
            w.close()

    def _on_window_closed(self, key: str):
        self._windows.pop(key, None)
        # 如果选择器本身正在关闭，跳过树节点更新
        try:
            tree = self._tree
            if tree is None or not tree.isVisible():
                return
        except RuntimeError:
            return
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            cat = self._tree.topLevelItem(i)
            for j in range(cat.childCount()):
                child = cat.child(j)
                if child.data(0, Qt.UserRole) == key:
                    child.setCheckState(0, Qt.Unchecked)
        self._tree.blockSignals(False)

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            cat = self._tree.topLevelItem(i)
            cat.setCheckState(0, state)
            for j in range(cat.childCount()):
                cat.child(j).setCheckState(0, state)
        self._tree.blockSignals(False)

    def set_logger(self, logger: DataLogger):
        self._logger = logger
        for w in self._windows.values():
            w.set_logger(logger)

    def closeEvent(self, event):
        # 先断开子窗口的 destroyed 信号，避免回调访问已删除的控件
        for w in list(self._windows.values()):
            w._timer.stop()
            try:
                w.destroyed.disconnect()
            except (TypeError, RuntimeError):
                pass
            w.close()
        self._windows.clear()
        super().closeEvent(event)
