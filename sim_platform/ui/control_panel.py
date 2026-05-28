"""控制面板 — 手动设定车辆行驶参数"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider, QDoubleSpinBox, QPushButton, QButtonGroup,
    QGridLayout, QGroupBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class ControlPanel(QWidget):
    """仿真控制面板
    提供：车速、方向盘转角、档位、制动压力的手动输入。
    """

    # 急停信号
    emergency_stop_triggered = pyqtSignal()

    # 控制模式信号
    mode_changed = pyqtSignal(str)  # "manual" | "auto"
    trajectory_load_requested = pyqtSignal()
    trajectory_generate_requested = pyqtSignal(str)  # "straight" | "circle" | "lane_change"
    trajectory_clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 8, 8, 8)

        # === 车速控制 ===
        speed_group = QGroupBox("车速控制", self)
        speed_layout = QHBoxLayout(speed_group)

        self.speed_slider = QSlider(Qt.Horizontal, self)
        self.speed_slider.setRange(0, 300)  # 0~30.0 km/h (×10)
        self.speed_slider.setValue(0)
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(50)
        self.speed_slider.setSingleStep(1)

        self.speed_spin = QDoubleSpinBox(self)
        self.speed_spin.setRange(0.0, 30.0)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setSuffix(" km/h")
        self.speed_spin.setValue(0.0)
        self.speed_spin.setSingleStep(0.5)

        # 双向绑定
        self.speed_slider.valueChanged.connect(
            lambda v: self.speed_spin.setValue(v / 10.0)
        )
        self.speed_spin.valueChanged.connect(
            lambda v: self.speed_slider.blockSignals(True) or
            self.speed_slider.setValue(int(v * 10)) or
            self.speed_slider.blockSignals(False)
        )

        speed_layout.addWidget(self.speed_slider)
        speed_layout.addWidget(self.speed_spin)
        layout.addWidget(speed_group)

        # === 方向盘转角控制 ===
        steer_group = QGroupBox("方向盘转角", self)
        steer_layout = QHBoxLayout(steer_group)

        self.steer_slider = QSlider(Qt.Horizontal, self)
        self.steer_slider.setRange(-720, 720)  # ±720°
        self.steer_slider.setValue(0)
        self.steer_slider.setTickPosition(QSlider.TicksBelow)
        self.steer_slider.setTickInterval(180)
        self.steer_slider.setSingleStep(5)

        self.steer_spin = QDoubleSpinBox(self)
        self.steer_spin.setRange(-720.0, 720.0)
        self.steer_spin.setDecimals(1)
        self.steer_spin.setSuffix(" °")
        self.steer_spin.setValue(0.0)
        self.steer_spin.setSingleStep(5.0)

        self.steer_slider.valueChanged.connect(
            lambda v: self.steer_spin.setValue(float(v))
        )
        self.steer_spin.valueChanged.connect(
            lambda v: self.steer_slider.blockSignals(True) or
            self.steer_slider.setValue(int(v)) or
            self.steer_slider.blockSignals(False)
        )

        steer_layout.addWidget(self.steer_slider)
        steer_layout.addWidget(self.steer_spin)
        layout.addWidget(steer_group)

        # === 档位选择 ===
        gear_group = QGroupBox("档位", self)
        gear_layout = QHBoxLayout(gear_group)

        self.gear_buttons: dict[int, QPushButton] = {}
        self.gear_group = QButtonGroup(self)
        self.gear_group.setExclusive(True)

        gear_labels = [(0, "P"), (1, "R"), (2, "N"), (3, "D")]
        for gid, gname in gear_labels:
            btn = QPushButton(gname, self)
            btn.setCheckable(True)
            btn.setFixedSize(50, 40)
            btn.setFont(QFont("Arial", 14, QFont.Bold))
            self.gear_group.addButton(btn, gid)
            self.gear_buttons[gid] = btn
            gear_layout.addWidget(btn)

        # 默认 N 档
        self.gear_buttons[2].setChecked(True)

        # P 档自动施加 2 MPa 制动压力
        self.gear_group.buttonClicked.connect(self._on_gear_changed)

        layout.addWidget(gear_group)

        # === 制动压力控制 ===
        brake_group = QGroupBox("制动压力", self)
        brake_layout = QHBoxLayout(brake_group)

        self.brake_slider = QSlider(Qt.Horizontal, self)
        self.brake_slider.setRange(0, 100)  # 0~10.0 MPa (×10)
        self.brake_slider.setValue(0)
        self.brake_slider.setTickPosition(QSlider.TicksBelow)
        self.brake_slider.setTickInterval(20)
        self.brake_slider.setSingleStep(1)

        self.brake_spin = QDoubleSpinBox(self)
        self.brake_spin.setRange(0.0, 10.0)
        self.brake_spin.setDecimals(1)
        self.brake_spin.setSuffix(" MPa")
        self.brake_spin.setValue(0.0)
        self.brake_spin.setSingleStep(0.5)

        self.brake_slider.valueChanged.connect(
            lambda v: self.brake_spin.setValue(v / 10.0)
        )
        self.brake_spin.valueChanged.connect(
            lambda v: self.brake_slider.blockSignals(True) or
            self.brake_slider.setValue(int(v * 10)) or
            self.brake_slider.blockSignals(False)
        )

        brake_layout.addWidget(self.brake_slider)
        brake_layout.addWidget(self.brake_spin)
        layout.addWidget(brake_group)

        # === 急停按钮 ===
        self.estop_btn = QPushButton("⚠ 急 停", self)
        self.estop_btn.setFixedHeight(45)
        self.estop_btn.setFont(QFont("Arial", 13, QFont.Bold))
        self.estop_btn.clicked.connect(self._on_estop)
        layout.addWidget(self.estop_btn)

        # === 控制模式切换 ===
        mode_group = QGroupBox("控制模式", self)
        mode_layout = QHBoxLayout(mode_group)

        self._mode_manual_btn = QPushButton("手动", self)
        self._mode_manual_btn.setCheckable(True)
        self._mode_manual_btn.setChecked(True)
        self._mode_manual_btn.setFixedHeight(32)
        self._mode_manual_btn.clicked.connect(lambda: self._on_mode_changed("manual"))

        self._mode_auto_btn = QPushButton("自动", self)
        self._mode_auto_btn.setCheckable(True)
        self._mode_auto_btn.setFixedHeight(32)
        self._mode_auto_btn.clicked.connect(lambda: self._on_mode_changed("auto"))

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._mode_manual_btn, 0)
        self._mode_group.addButton(self._mode_auto_btn, 1)

        mode_layout.addWidget(self._mode_manual_btn)
        mode_layout.addWidget(self._mode_auto_btn)
        layout.addWidget(mode_group)

        # === 轨迹控制 ===
        traj_group = QGroupBox("参考轨迹", self)
        traj_layout = QVBoxLayout(traj_group)
        traj_layout.setSpacing(5)

        self._traj_load_btn = QPushButton("📂 加载轨迹文件", self)
        self._traj_load_btn.setFixedHeight(30)
        self._traj_load_btn.clicked.connect(self.trajectory_load_requested.emit)
        traj_layout.addWidget(self._traj_load_btn)

        # 轨迹参数输入
        param_layout = QHBoxLayout()
        param_layout.setSpacing(4)

        self._traj_len_label = QLabel("长度", self)
        self._traj_len_spin = QDoubleSpinBox(self)
        self._traj_len_spin.setRange(10.0, 5000.0)
        self._traj_len_spin.setDecimals(0)
        self._traj_len_spin.setSuffix(" m")
        self._traj_len_spin.setValue(100.0)
        self._traj_len_spin.setSingleStep(10.0)

        self._traj_radius_label = QLabel("半径", self)
        self._traj_radius_spin = QDoubleSpinBox(self)
        self._traj_radius_spin.setRange(5.0, 500.0)
        self._traj_radius_spin.setDecimals(1)
        self._traj_radius_spin.setSuffix(" m")
        self._traj_radius_spin.setValue(25.0)
        self._traj_radius_spin.setSingleStep(5.0)

        param_layout.addWidget(self._traj_len_label)
        param_layout.addWidget(self._traj_len_spin)
        param_layout.addWidget(self._traj_radius_label)
        param_layout.addWidget(self._traj_radius_spin)
        traj_layout.addLayout(param_layout)

        # 目标车速
        speed_layout = QHBoxLayout()
        speed_layout.setSpacing(4)
        self._traj_speed_label = QLabel("目标车速", self)
        self._traj_speed_spin = QDoubleSpinBox(self)
        self._traj_speed_spin.setRange(1.0, 30.0)
        self._traj_speed_spin.setDecimals(1)
        self._traj_speed_spin.setSuffix(" m/s")
        self._traj_speed_spin.setValue(5.0)
        self._traj_speed_spin.setSingleStep(1.0)
        speed_layout.addWidget(self._traj_speed_label)
        speed_layout.addWidget(self._traj_speed_spin)
        speed_layout.addStretch()
        traj_layout.addLayout(speed_layout)

        # 初始偏差输入
        error_layout = QHBoxLayout()
        error_layout.setSpacing(4)

        self._traj_cte_label = QLabel("横向偏差", self)
        self._traj_cte_spin = QDoubleSpinBox(self)
        self._traj_cte_spin.setRange(-50.0, 50.0)
        self._traj_cte_spin.setDecimals(1)
        self._traj_cte_spin.setSuffix(" m")
        self._traj_cte_spin.setValue(0.0)
        self._traj_cte_spin.setSingleStep(0.5)
        self._traj_cte_spin.setToolTip("正值=车辆在轨迹右侧（与控制器CTE同号）")

        self._traj_he_label = QLabel("航向偏差", self)
        self._traj_he_spin = QDoubleSpinBox(self)
        self._traj_he_spin.setRange(-180.0, 180.0)
        self._traj_he_spin.setDecimals(1)
        self._traj_he_spin.setSuffix(" °")
        self._traj_he_spin.setValue(0.0)
        self._traj_he_spin.setSingleStep(5.0)
        self._traj_he_spin.setToolTip("正值=车辆偏右（CW，与控制器heading_error同号）")

        error_layout.addWidget(self._traj_cte_label)
        error_layout.addWidget(self._traj_cte_spin)
        error_layout.addWidget(self._traj_he_label)
        error_layout.addWidget(self._traj_he_spin)
        traj_layout.addLayout(error_layout)

        # 轨迹生成按钮组
        gen_layout = QHBoxLayout()
        gen_layout.setSpacing(3)

        self._traj_gen_straight = QPushButton("直线", self)
        self._traj_gen_straight.setFixedHeight(28)
        self._traj_gen_straight.clicked.connect(
            lambda: self.trajectory_generate_requested.emit("straight"))

        self._traj_gen_circle = QPushButton("圆形", self)
        self._traj_gen_circle.setFixedHeight(28)
        self._traj_gen_circle.clicked.connect(
            lambda: self.trajectory_generate_requested.emit("circle"))

        self._traj_gen_lc = QPushButton("变道", self)
        self._traj_gen_lc.setFixedHeight(28)
        self._traj_gen_lc.clicked.connect(
            lambda: self.trajectory_generate_requested.emit("lane_change"))

        gen_layout.addWidget(self._traj_gen_straight)
        gen_layout.addWidget(self._traj_gen_circle)
        gen_layout.addWidget(self._traj_gen_lc)
        traj_layout.addLayout(gen_layout)

        self._traj_clear_btn = QPushButton("清除轨迹", self)
        self._traj_clear_btn.setFixedHeight(28)
        self._traj_clear_btn.clicked.connect(self.trajectory_clear_requested.emit)
        traj_layout.addWidget(self._traj_clear_btn)

        layout.addWidget(traj_group)

        layout.addStretch()

    def _on_estop(self):
        """急停：重置所有控制到安全状态"""
        self.speed_slider.setValue(0)
        self.brake_slider.setValue(100)  # 最大制动
        self.emergency_stop_triggered.emit()

    def _on_gear_changed(self, btn):
        """档位切换回调：P 档自动施加 2 MPa 制动"""
        gear_id = self.gear_group.id(btn)
        if gear_id == 0:  # P 档
            self.brake_spin.setValue(2.0)

    def _on_mode_changed(self, mode: str):
        """控制模式切换"""
        self._mode_manual_btn.setChecked(mode == "manual")
        self._mode_auto_btn.setChecked(mode == "auto")
        self.mode_changed.emit(mode)

    def _apply_style(self):
        self.setStyleSheet("""
            QGroupBox {
                color: #b0b8d0;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #2a3a5c;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QLabel {
                color: #c8d0e0;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #1e2d44;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -5px 0;
                background: #00ff88;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #33ffaa;
            }
            QSlider::sub-page:horizontal {
                background: #2a5a44;
                border-radius: 3px;
            }
            QDoubleSpinBox {
                background: #1e2d44;
                color: #e0e0e0;
                border: 1px solid #2a3a5c;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 12px;
                min-width: 80px;
            }
            QPushButton {
                background: #1e2d44;
                color: #c8d0e0;
                border: 1px solid #2a3a5c;
                border-radius: 4px;
                padding: 6px;
            }
            QPushButton:hover {
                background: #2a3a5c;
            }
            QPushButton:checked {
                background: #00ff88;
                color: #1a1a2e;
                border-color: #00ff88;
            }
        """)
        # 急停按钮特殊样式
        self.estop_btn.setStyleSheet("""
            QPushButton {
                background: #cc2222;
                color: white;
                border: 2px solid #ff4444;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #ee3333;
            }
            QPushButton:pressed {
                background: #aa1111;
            }
        """)
        # 模式切换按钮样式
        mode_btn_style = """
            QPushButton {
                background: #1e2d44;
                color: #c8d0e0;
                border: 1px solid #2a3a5c;
                border-radius: 3px;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: #2a3a5c;
            }
            QPushButton:checked {
                background: #00aa55;
                color: white;
                border-color: #00cc66;
            }
        """
        self._mode_manual_btn.setStyleSheet(mode_btn_style)
        self._mode_auto_btn.setStyleSheet(mode_btn_style)
        # 轨迹按钮样式
        traj_btn_style = """
            QPushButton {
                background: #1a2d3a;
                color: #a0b8d0;
                border: 1px solid #2a4a5c;
                border-radius: 3px;
                font-size: 11px;
                padding: 4px 6px;
            }
            QPushButton:hover {
                background: #2a4a5c;
                color: #d0e0f0;
            }
            QPushButton:pressed {
                background: #1a3a4a;
            }
        """
        self._traj_load_btn.setStyleSheet(traj_btn_style)
        self._traj_clear_btn.setStyleSheet(traj_btn_style)
        gen_btn_style = """
            QPushButton {
                background: #1a2d3a;
                color: #88a8c0;
                border: 1px solid #2a4a5c;
                border-radius: 3px;
                font-size: 10px;
                padding: 3px 4px;
            }
            QPushButton:hover {
                background: #2a4a5c;
                color: #c0d8f0;
            }
        """
        self._traj_gen_straight.setStyleSheet(gen_btn_style)
        self._traj_gen_circle.setStyleSheet(gen_btn_style)
        self._traj_gen_lc.setStyleSheet(gen_btn_style)

    # --- 对外接口 ---

    def get_velocity_kmh(self) -> float:
        return self.speed_spin.value()

    def get_steer_sw_deg(self) -> float:
        return self.steer_spin.value()

    def get_gear(self) -> int:
        return self.gear_group.checkedId()

    def get_brake_pressure(self) -> float:
        return self.brake_spin.value()

    def set_velocity_kmh(self, v: float):
        self.speed_spin.setValue(v)

    def set_steer_sw_deg(self, s: float):
        self.steer_spin.setValue(s)

    def set_gear(self, g: int):
        if g in self.gear_buttons:
            self.gear_buttons[g].setChecked(True)
            # P 档自动施加 2 MPa 制动
            if g == 0:
                self.brake_spin.setValue(2.0)

    def set_brake_pressure(self, p: float):
        self.brake_spin.setValue(p)

    def get_mode(self) -> str:
        """获取当前控制模式"""
        return "auto" if self._mode_auto_btn.isChecked() else "manual"

    def set_mode(self, mode: str):
        """设置控制模式"""
        self._on_mode_changed(mode)

    def set_min_turn_radius(self, r: float):
        """设置轨迹半径的最小值（受车辆最小转弯半径约束）"""
        self._traj_radius_spin.setMinimum(r)
        if self._traj_radius_spin.value() < r:
            self._traj_radius_spin.setValue(r)

    def get_trajectory_length(self) -> float:
        return self._traj_len_spin.value()

    def get_trajectory_radius(self) -> float:
        return self._traj_radius_spin.value()

    def get_trajectory_cte(self) -> float:
        return self._traj_cte_spin.value()

    def get_trajectory_heading_error(self) -> float:
        return self._traj_he_spin.value()

    def get_trajectory_velocity(self) -> float:
        return self._traj_speed_spin.value()
