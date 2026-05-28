"""障碍物面板 — 增删改查 + 预设场景 (F-16)"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QDoubleSpinBox, QComboBox, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal


class ObstaclePanel(QWidget):
    """障碍物管理面板

    信号:
      - obstacle_add_requested(x, y, length, width, heading, speed, obs_type)
      - obstacle_remove_requested(obs_id)
      - obstacle_clear_all_requested()
      - preset_load_requested(preset_name)
    """

    obstacle_add_requested = pyqtSignal(float, float, float, float, float, float, int)
    obstacle_remove_requested = pyqtSignal(int)
    obstacle_clear_all_requested = pyqtSignal()
    preset_load_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_obs_ids: tuple = ()  # 帧间去重，避免选中被清除
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ── 添加障碍物 ──
        add_group = QGroupBox("添加障碍物")
        add_group.setStyleSheet(self._group_style())
        add_layout = QVBoxLayout(add_group)
        add_layout.setSpacing(4)

        # X, Y
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("X:"))
        self._spin_x = QDoubleSpinBox()
        self._spin_x.setRange(-1000, 1000)
        self._spin_x.setValue(30.0)
        self._spin_x.setDecimals(1)
        row1.addWidget(self._spin_x)
        row1.addWidget(QLabel("Y:"))
        self._spin_y = QDoubleSpinBox()
        self._spin_y.setRange(-1000, 1000)
        self._spin_y.setValue(0.0)
        self._spin_y.setDecimals(1)
        row1.addWidget(self._spin_y)
        add_layout.addLayout(row1)

        # 尺寸
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("长:"))
        self._spin_len = QDoubleSpinBox()
        self._spin_len.setRange(0.5, 50.0)
        self._spin_len.setValue(4.0)
        self._spin_len.setDecimals(1)
        row2.addWidget(self._spin_len)
        row2.addWidget(QLabel("宽:"))
        self._spin_wid = QDoubleSpinBox()
        self._spin_wid.setRange(0.5, 20.0)
        self._spin_wid.setValue(2.5)
        self._spin_wid.setDecimals(1)
        row2.addWidget(self._spin_wid)
        add_layout.addLayout(row2)

        # 朝向 + 速度
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("朝向:"))
        self._spin_heading = QDoubleSpinBox()
        self._spin_heading.setRange(-180, 180)
        self._spin_heading.setValue(0)
        self._spin_heading.setDecimals(1)
        self._spin_heading.setSuffix("°")
        row3.addWidget(self._spin_heading)
        row3.addWidget(QLabel("速度:"))
        self._spin_speed = QDoubleSpinBox()
        self._spin_speed.setRange(0, 30)
        self._spin_speed.setValue(0)
        self._spin_speed.setDecimals(1)
        self._spin_speed.setSuffix("m/s")
        row3.addWidget(self._spin_speed)
        add_layout.addLayout(row3)

        # 类型 + 按钮
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("类型:"))
        self._combo_type = QComboBox()
        self._combo_type.addItems(["静态", "动态"])
        row4.addWidget(self._combo_type)
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._on_add)
        btn_add.setStyleSheet(self._btn_style())
        row4.addWidget(btn_add)
        add_layout.addLayout(row4)

        layout.addWidget(add_group)

        # ── 障碍物列表 ──
        list_group = QGroupBox("障碍物列表")
        list_group.setStyleSheet(self._group_style())
        list_layout = QVBoxLayout(list_group)
        list_layout.setSpacing(4)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["ID", "位置", "尺寸", "类型"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setStyleSheet(
            "QTableWidget { background: #0d1117; color: #c0d0e0; gridline-color: #2a3a5c; }"
            "QHeaderView::section { background: #1a2a44; color: #c0d0e0; border: 1px solid #2a3a5c; }"
        )
        list_layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_remove = QPushButton("删除选中")
        btn_remove.clicked.connect(self._on_remove)
        btn_remove.setStyleSheet(self._btn_style())
        btn_row.addWidget(btn_remove)

        btn_clear = QPushButton("清除全部")
        btn_clear.clicked.connect(self._on_clear)
        btn_clear.setStyleSheet(self._btn_style_danger())
        btn_row.addWidget(btn_clear)
        list_layout.addLayout(btn_row)

        layout.addWidget(list_group)

        # ── 预设场景 ──
        preset_group = QGroupBox("预设场景")
        preset_group.setStyleSheet(self._group_style())
        preset_layout = QVBoxLayout(preset_group)
        preset_layout.setSpacing(4)

        for name, label in [
            ("single_block", "单个障碍物 (前方 30m)"),
            ("narrow_pass", "窄道会车 (对向动态)"),
            ("scattered", "多障碍物散落"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, n=name: self.preset_load_requested.emit(n))
            btn.setStyleSheet(self._btn_style())
            preset_layout.addWidget(btn)

        layout.addWidget(preset_group)
        layout.addStretch()

    # ========== 公共接口 ==========

    def update_obstacle_list(self, obstacles: list) -> None:
        """刷新障碍物表格（仅列表变化时才重建，保留用户选中状态）"""
        # 帧间去重：障碍物 ID 序列未变化则跳过
        new_ids = tuple(obs.id for obs in obstacles)
        if new_ids == self._last_obs_ids:
            return
        self._last_obs_ids = new_ids

        self._table.setRowCount(0)
        for obs in obstacles:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(obs.id)))
            self._table.setItem(row, 1, QTableWidgetItem(f"({obs.center_x:.1f}, {obs.center_y:.1f})"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{obs.length:.1f}x{obs.width:.1f}"))
            type_str = "动态" if obs.obstacle_type == 1 else "静态"
            self._table.setItem(row, 3, QTableWidgetItem(type_str))

    def get_selected_id(self) -> int:
        """获取当前选中行的障碍物 ID"""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return -1
        item = self._table.item(rows[0].row(), 0)
        return int(item.text()) if item else -1

    # ========== 槽 ==========

    def _on_add(self):
        import math
        heading_rad = math.radians(self._spin_heading.value())
        self.obstacle_add_requested.emit(
            self._spin_x.value(),
            self._spin_y.value(),
            self._spin_len.value(),
            self._spin_wid.value(),
            heading_rad,
            self._spin_speed.value(),
            0 if self._combo_type.currentIndex() == 0 else 1,
        )

    def _on_remove(self):
        obs_id = self.get_selected_id()
        if obs_id >= 0:
            self.obstacle_remove_requested.emit(obs_id)

    def _on_clear(self):
        self.obstacle_clear_all_requested.emit()

    # ========== 样式 ==========

    @staticmethod
    def _group_style() -> str:
        return """
            QGroupBox {
                color: #c0d0e0;
                font-weight: bold;
                border: 1px solid #2a3a5c;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """

    @staticmethod
    def _btn_style() -> str:
        return """
            QPushButton {
                color: #e0e8f0;
                background: #2a3a5c;
                border: 1px solid #3a4a6c;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover { background: #3a5a8c; }
            QPushButton:pressed { background: #1a2a44; }
        """

    @staticmethod
    def _btn_style_danger() -> str:
        return """
            QPushButton {
                color: #ff8888;
                background: #3a1a1a;
                border: 1px solid #5a2a2a;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover { background: #5a2a2a; }
        """
