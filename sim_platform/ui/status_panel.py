"""状态面板 — 显示车辆实时状态信息"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGridLayout, QGroupBox, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ..core.vehicle_state import VehicleState


class StatusPanel(QWidget):
    """车辆状态显示面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._value_labels: dict[str, QLabel] = {}
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # === 位姿信息 ===
        pose_group = QGroupBox("位姿 Pose", self)
        pose_grid = QGridLayout(pose_group)
        pose_grid.setSpacing(4)

        pose_fields = [
            ("X 坐标", "x", "m"),
            ("Y 坐标", "y", "m"),
            ("航向角 θ", "theta", "°"),
        ]
        for row, (name, key, unit) in enumerate(pose_fields):
            lbl = QLabel(name, self)
            val = QLabel("0.00", self)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_lbl = QLabel(unit, self)
            pose_grid.addWidget(lbl, row, 0)
            pose_grid.addWidget(val, row, 1)
            pose_grid.addWidget(unit_lbl, row, 2)
            self._value_labels[key] = val

        layout.addWidget(pose_group)

        # === 运动信息 ===
        motion_group = QGroupBox("运动 Motion", self)
        motion_grid = QGridLayout(motion_group)
        motion_grid.setSpacing(4)

        motion_fields = [
            ("车速", "v", "km/h"),
            ("纵向加速度", "acc", "m/s²"),
            ("横摆角速度", "yaw_rate", "°/s"),
            ("转弯半径", "turn_radius", "m"),
            ("路径曲率", "curvature", "1/m"),
        ]
        for row, (name, key, unit) in enumerate(motion_fields):
            lbl = QLabel(name, self)
            val = QLabel("0.00", self)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_lbl = QLabel(unit, self)
            motion_grid.addWidget(lbl, row, 0)
            motion_grid.addWidget(val, row, 1)
            motion_grid.addWidget(unit_lbl, row, 2)
            self._value_labels[key] = val

        layout.addWidget(motion_group)

        # === 控制信息 ===
        ctrl_group = QGroupBox("控制 Control", self)
        ctrl_grid = QGridLayout(ctrl_group)
        ctrl_grid.setSpacing(4)

        ctrl_fields = [
            ("方向盘转角", "steer_sw", "°"),
            ("前轮转角", "steer", "°"),
            ("档位", "gear", ""),
            ("制动压力", "brake", "MPa"),
        ]
        for row, (name, key, unit) in enumerate(ctrl_fields):
            lbl = QLabel(name, self)
            val = QLabel("0.00", self)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_lbl = QLabel(unit, self)
            ctrl_grid.addWidget(lbl, row, 0)
            ctrl_grid.addWidget(val, row, 1)
            ctrl_grid.addWidget(unit_lbl, row, 2)
            self._value_labels[key] = val

        layout.addWidget(ctrl_group)

        # === 仿真信息 ===
        sim_group = QGroupBox("仿真 Sim", self)
        sim_grid = QGridLayout(sim_group)
        sim_grid.setSpacing(4)

        sim_fields = [
            ("仿真时间", "sim_time", "s"),
            ("实时因子", "rtf", "x"),
            ("仿真步长", "dt", "ms"),
        ]
        for row, (name, key, unit) in enumerate(sim_fields):
            lbl = QLabel(name, self)
            val = QLabel("0.00", self)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_lbl = QLabel(unit, self)
            sim_grid.addWidget(lbl, row, 0)
            sim_grid.addWidget(val, row, 1)
            sim_grid.addWidget(unit_lbl, row, 2)
            self._value_labels[key] = val

        layout.addWidget(sim_group)

        # === 跟踪误差 ===
        track_group = QGroupBox("跟踪误差 Tracking", self)
        track_grid = QGridLayout(track_group)
        track_grid.setSpacing(4)

        track_fields = [
            ("横向偏差", "cte", "m"),
            ("航向偏差", "heading_err", "°"),
            ("速度偏差", "speed_err", "km/h"),
        ]
        for row, (name, key, unit) in enumerate(track_fields):
            lbl = QLabel(name, self)
            val = QLabel("—", self)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_lbl = QLabel(unit, self)
            track_grid.addWidget(lbl, row, 0)
            track_grid.addWidget(val, row, 1)
            track_grid.addWidget(unit_lbl, row, 2)
            self._value_labels[key] = val

        layout.addWidget(track_group)

        # === 档位状态大字体显示 ===
        self.gear_big_label = QLabel("N", self)
        self.gear_big_label.setAlignment(Qt.AlignCenter)
        self.gear_big_label.setFixedHeight(50)
        self.gear_big_label.setFont(QFont("Arial", 28, QFont.Bold))
        layout.addWidget(self.gear_big_label)

        layout.addStretch()

    def _apply_style(self):
        self.setStyleSheet("""
            QGroupBox {
                color: #b0b8d0;
                font-size: 13px;
                font-weight: bold;
                border: 1px solid #2a3a5c;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 3px;
            }
            QLabel {
                color: #c8d0e0;
                font-size: 13px;
            }
        """)
        self.gear_big_label.setStyleSheet("""
            QLabel {
                color: #00ff88;
                background: #1e2d44;
                border: 2px solid #2a3a5c;
                border-radius: 6px;
                font-size: 28px;
            }
        """)

    def update_state(self, state: VehicleState, sim_dt: float,
                     sim_time: float, rtf: float,
                     steer_sw_deg: float, wheelbase: float = 4.2):
        """更新所有状态显示"""
        import math

        # 位姿
        self._set("x", f"{state.x:.2f}")
        self._set("y", f"{state.y:.2f}")
        self._set("theta", f"{state.theta_deg:.2f}")

        # 运动
        self._set("v", f"{state.v_kmh:.2f}")
        self._set("acc", f"{state.acceleration:.3f}")
        self._set("yaw_rate", f"{math.degrees(state.yaw_rate):.2f}")

        # 转弯半径
        if abs(state.steer_angle) > 1e-4 and abs(state.v) > 1e-3:
            tr = state.turn_radius_with_wheelbase(wheelbase)
            if tr > 9999:
                self._set("turn_radius", "∞")
            else:
                self._set("turn_radius", f"{tr:.1f}")
        else:
            self._set("turn_radius", "∞")

        self._set("curvature", f"{state.curvature:.4f}")

        # 控制
        self._set("steer_sw", f"{steer_sw_deg:.1f}")
        self._set("steer", f"{state.steer_angle_deg:.2f}")
        self._set("gear", state.gear_name)
        self._set("brake", f"{state.brake_pressure:.1f}")

        # 仿真
        self._set("sim_time", f"{sim_time:.2f}")
        self._set("rtf", f"{rtf:.2f}")
        self._set("dt", f"{sim_dt * 1000:.1f}")

        # 档位大字体 - 颜色随档位变化
        gear_colors = {"P": "#ff4444", "R": "#ffaa00", "N": "#888888", "D": "#00ff88"}
        color = gear_colors.get(state.gear_name, "#888888")
        self.gear_big_label.setText(state.gear_name)
        self.gear_big_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background: #1e2d44;
                border: 2px solid {color};
                border-radius: 6px;
                font-size: 28px;
            }}
        """)

    def update_tracking_errors(self, cte: float | None, heading_err: float | None,
                                speed_err: float | None):
        """更新跟踪误差显示（自动模式下调用）"""
        if cte is not None:
            self._set("cte", f"{cte:.3f}")
            # 颜色提示：>0.5m 变红
            self._colorize("cte", abs(cte) > 0.5)
        else:
            self._set("cte", "—")
            self._reset_color("cte")

        if heading_err is not None:
            self._set("heading_err", f"{heading_err:.2f}")
            self._colorize("heading_err", abs(heading_err) > 10.0)
        else:
            self._set("heading_err", "—")
            self._reset_color("heading_err")

        if speed_err is not None:
            self._set("speed_err", f"{speed_err:.2f}")
            self._colorize("speed_err", abs(speed_err) > 3.0)
        else:
            self._set("speed_err", "—")
            self._reset_color("speed_err")

    def _colorize(self, key: str, warn: bool):
        if key in self._value_labels:
            if warn:
                self._value_labels[key].setStyleSheet(
                    "color: #ff6644; font-size: 13px; font-weight: bold;")
            else:
                self._value_labels[key].setStyleSheet(
                    "color: #00ff88; font-size: 13px;")

    def _reset_color(self, key: str):
        if key in self._value_labels:
            self._value_labels[key].setStyleSheet(
                "color: #c8d0e0; font-size: 13px;")

    def _set(self, key: str, value: str):
        if key in self._value_labels:
            self._value_labels[key].setText(value)
