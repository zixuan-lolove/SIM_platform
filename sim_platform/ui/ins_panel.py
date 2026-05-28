"""惯导数据设置面板 — 模拟 DDS 定位数据下发"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QPushButton, QGroupBox, QGridLayout,
    QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..models.ins_data import InsData


class InsPanel(QWidget):
    """惯导数据手动设置面板
    模拟通过 DDS 接收的惯导定位数据，用于设置车辆初始位姿。
    """

    ins_data_applied = pyqtSignal(InsData)
    ins_data_reset = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._ins_data = InsData()
        self._speed_collapsed = True
        self._attitude_collapsed = True
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # === 标题 ===
        title = QLabel("惯导数据 (INS/GNSS)", self)
        title.setFont(QFont("Arial", 11, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # === 位姿输入 ===
        pose_group = QGroupBox("位姿 Position", self)
        pose_grid = QGridLayout(pose_group)
        pose_grid.setSpacing(4)

        pose_fields = [
            ("纬度 Lat", "lat", -90.0, 90.0, 0.0, "°"),
            ("经度 Lon", "lon", -180.0, 180.0, 0.0, "°"),
            ("海拔 Alt", "alt", -500.0, 9000.0, 0.0, "m"),
            ("地理航向 Heading", "heading", 0.0, 360.0, 0.0, "°"),
        ]
        self._pose_inputs: dict[str, QDoubleSpinBox] = {}
        for row, (name, key, vmin, vmax, default, unit) in enumerate(pose_fields):
            lbl = QLabel(name, self)
            spin = QDoubleSpinBox(self)
            spin.setRange(vmin, vmax)
            spin.setValue(default)
            spin.setDecimals(20)
            spin.setSingleStep(1.0 if unit == "m" else 1.0)
            spin.setKeyboardTracking(False)
            unit_lbl = QLabel(unit, self)
            pose_grid.addWidget(lbl, row, 0)
            pose_grid.addWidget(spin, row, 1)
            pose_grid.addWidget(unit_lbl, row, 2)
            self._pose_inputs[key] = spin

        layout.addWidget(pose_group)

        # === 速度输入（可折叠） ===
        self._speed_group = QGroupBox("速度 Velocity  ▼", self)
        self._speed_group.setCheckable(True)
        self._speed_group.setChecked(False)
        self._speed_group.clicked.connect(self._on_speed_toggle)
        speed_grid = QGridLayout(self._speed_group)
        speed_grid.setSpacing(4)

        speed_fields = [
            ("纵向 Vx", "vx", -30.0, 30.0, 0.0, "m/s"),
            ("横向 Vy", "vy", -30.0, 30.0, 0.0, "m/s"),
        ]
        self._speed_inputs: dict[str, QDoubleSpinBox] = {}
        for row, (name, key, vmin, vmax, default, unit) in enumerate(speed_fields):
            lbl = QLabel(name, self)
            spin = QDoubleSpinBox(self)
            spin.setRange(vmin, vmax)
            spin.setValue(default)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            unit_lbl = QLabel(unit, self)
            speed_grid.addWidget(lbl, row, 0)
            speed_grid.addWidget(spin, row, 1)
            speed_grid.addWidget(unit_lbl, row, 2)
            self._speed_inputs[key] = spin

        self._speed_content = QWidget(self)
        self._speed_content.setLayout(speed_grid)
        self._speed_group_layout = QVBoxLayout(self._speed_group)
        self._speed_group_layout.addWidget(self._speed_content)
        self._speed_content.setVisible(False)
        layout.addWidget(self._speed_group)

        # === 姿态输入（可折叠，P2） ===
        self._attitude_group = QGroupBox("姿态 Attitude  ▼", self)
        self._attitude_group.setCheckable(True)
        self._attitude_group.setChecked(False)
        self._attitude_group.clicked.connect(self._on_attitude_toggle)
        attitude_grid = QGridLayout(self._attitude_group)
        attitude_grid.setSpacing(4)

        attitude_fields = [
            ("Roll 横滚", "roll", -90.0, 90.0, 0.0, "°"),
            ("Pitch 俯仰", "pitch", -90.0, 90.0, 0.0, "°"),
        ]
        self._attitude_inputs: dict[str, QDoubleSpinBox] = {}
        for row, (name, key, vmin, vmax, default, unit) in enumerate(attitude_fields):
            lbl = QLabel(name, self)
            spin = QDoubleSpinBox(self)
            spin.setRange(vmin, vmax)
            spin.setValue(default)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            unit_lbl = QLabel(unit, self)
            attitude_grid.addWidget(lbl, row, 0)
            attitude_grid.addWidget(spin, row, 1)
            attitude_grid.addWidget(unit_lbl, row, 2)
            self._attitude_inputs[key] = spin

        self._attitude_content = QWidget(self)
        self._attitude_content.setLayout(attitude_grid)
        self._attitude_group_layout = QVBoxLayout(self._attitude_group)
        self._attitude_group_layout.addWidget(self._attitude_content)
        self._attitude_content.setVisible(False)
        layout.addWidget(self._attitude_group)

        # === GNSS 状态指示 ===
        status_group = QGroupBox("定位状态 GNSS", self)
        status_layout = QHBoxLayout(status_group)
        status_layout.setSpacing(6)

        self._gnss_status_label = QLabel("无效", self)
        self._gnss_status_label.setAlignment(Qt.AlignCenter)
        self._gnss_status_label.setFixedHeight(24)
        status_layout.addWidget(self._gnss_status_label)
        layout.addWidget(status_group)

        # === 操作按钮 ===
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self._apply_btn = QPushButton("应用", self)
        self._apply_btn.setFixedHeight(36)
        self._apply_btn.setFont(QFont("Arial", 11, QFont.Bold))
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setToolTip("将惯导数据写入车辆初始状态，仿真以该位姿为起始点运行")

        self._reset_btn = QPushButton("重置", self)
        self._reset_btn.setFixedHeight(36)
        self._reset_btn.setFont(QFont("Arial", 11, QFont.Bold))
        self._reset_btn.clicked.connect(self._on_reset)
        self._reset_btn.setToolTip("清空所有惯导输入，恢复默认原点状态")

        btn_layout.addWidget(self._apply_btn)
        btn_layout.addWidget(self._reset_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    def _on_speed_toggle(self, checked):
        self._speed_content.setVisible(checked)
        self._speed_group.setTitle("速度 Velocity  ▼" if not checked else "速度 Velocity  ▲")

    def _on_attitude_toggle(self, checked):
        self._attitude_content.setVisible(checked)
        self._attitude_group.setTitle("姿态 Attitude  ▼" if not checked else "姿态 Attitude  ▲")

    def _on_apply(self):
        """收集面板数据，构造 InsData 并发射信号"""
        data = InsData(
            latitude=self._pose_inputs["lat"].value(),
            longitude=self._pose_inputs["lon"].value(),
            heading_geo=self._pose_inputs["heading"].value(),
            local_x=0.0,  # 由 main_window._on_ins_applied 通过坐标转换填充
            local_y=0.0,
            local_z=self._pose_inputs["alt"].value(),
            yaw=0.0,      # 由 main_window._on_ins_applied 通过航向转换填充
            roll=self._attitude_inputs["roll"].value(),
            pitch=self._attitude_inputs["pitch"].value(),
            vel_east=self._speed_inputs["vx"].value(),
            vel_north=self._speed_inputs["vy"].value(),
            vel_up=0.0,
            gnss_status=3,  # 手动设置默认为 RTK Fix
            satellite_count=20,
            hdop=0.8,
            vdop=1.2,
        )
        self._ins_data = data
        self._update_gnss_status()
        self.ins_data_applied.emit(data)

    def _on_reset(self):
        """重置所有输入为默认值"""
        for key in ["lat", "lon", "alt", "heading"]:
            self._pose_inputs[key].setValue(0.0)
        for spin in self._speed_inputs.values():
            spin.setValue(0.0)
        for spin in self._attitude_inputs.values():
            spin.setValue(0.0)
        self._ins_data = InsData()
        self._update_gnss_status()
        self.ins_data_reset.emit()

    def _update_gnss_status(self):
        status = self._ins_data.gnss_status_name
        self._gnss_status_label.setText(f"● {status}")
        colors = {
            "无效": "#ff4444", "单点": "#ffaa00", "差分": "#ffcc00",
            "RTK Fix": "#00ff88", "RTK Float": "#88ccff",
        }
        color = colors.get(status, "#888888")
        self._gnss_status_label.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: bold;"
        )

    def set_ins_data(self, data: InsData):
        """从外部设置 INS 数据（如捕获当前位置）"""
        self._ins_data = data
        self._pose_inputs["lat"].setValue(data.latitude)
        self._pose_inputs["lon"].setValue(data.longitude)
        self._pose_inputs["alt"].setValue(data.local_z)
        self._pose_inputs["heading"].setValue(data.heading_geo)
        self._speed_inputs["vx"].setValue(data.vel_east)
        self._speed_inputs["vy"].setValue(data.vel_north)
        self._attitude_inputs["roll"].setValue(data.roll)
        self._attitude_inputs["pitch"].setValue(data.pitch)
        self._update_gnss_status()

    def get_ins_data(self) -> InsData:
        return self._ins_data.clone()

    def set_editable(self, editable: bool):
        """控制面板是否可编辑（运行中锁定）"""
        for spin in self._pose_inputs.values():
            spin.setEnabled(editable)
        for spin in self._speed_inputs.values():
            spin.setEnabled(editable)
        for spin in self._attitude_inputs.values():
            spin.setEnabled(editable)
        self._apply_btn.setEnabled(editable)
        self._reset_btn.setEnabled(editable)

    def _apply_style(self):
        self.setStyleSheet("""
            QGroupBox {
                color: #b0b8d0;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #2a3a5c;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 3px;
            }
            QGroupBox::indicator {
                width: 12px;
                height: 12px;
            }
            QLabel {
                color: #c8d0e0;
                font-size: 11px;
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
            QDoubleSpinBox:disabled {
                background: #151d2b;
                color: #555566;
            }
        """)
        # 应用按钮 - 绿色强调
        self._apply_btn.setStyleSheet("""
            QPushButton {
                background: #00aa55;
                color: white;
                border: 1px solid #00cc66;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #00cc66;
            }
            QPushButton:pressed {
                background: #008844;
            }
            QPushButton:disabled {
                background: #2a3a2a;
                color: #555;
            }
        """)
        # 重置按钮 - 灰色
        self._reset_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a4a;
                color: #c8d0e0;
                border: 1px solid #4a4a5c;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #4a4a5c;
            }
            QPushButton:pressed {
                background: #2a2a3a;
            }
            QPushButton:disabled {
                background: #1e1e2a;
                color: #555;
            }
        """)
