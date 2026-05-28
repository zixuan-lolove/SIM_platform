"""主窗口 — 整合所有 UI 组件和仿真引擎"""

import math
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QAction, QToolBar, QStatusBar, QLabel, QMessageBox,
    QFileDialog, QSplitter, QFrame, QSizePolicy, QTabWidget,
    QScrollArea, QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

from ..models.vehicle_params import VehicleParams
from ..models.ins_data import InsData
from ..models.trajectory import Trajectory
from ..core.vehicle_state import VehicleState
from ..core.sim_engine import SimEngine, ControlMode
from ..core.controller import LatLonController
from ..core.full_stack_engine import FullStackEngine
from ..config.control_config_loader import ControlConfig
from .control_panel import ControlPanel
from .map_view import MapView
from .status_panel import StatusPanel
from .ins_panel import InsPanel
from .plot_window import PlotWindow
from .full_stack_panel import FullStackPanel
from .obstacle_panel import ObstaclePanel


class MainWindow(QMainWindow):
    """仿真平台主窗口"""

    MODE_BASIC = "basic"
    MODE_FULL_STACK = "full_stack"

    def __init__(self, params: VehicleParams | None = None):
        super().__init__()

        self._params = params or VehicleParams()
        self._sim_mode: str = self.MODE_BASIC
        self._sim_engine: SimEngine = SimEngine(self._params)
        self._sim_engine.set_state_callback(self._on_sim_state_updated)
        self._control_config = ControlConfig.load()

        # 全栈模块引用（延迟创建）
        self._full_stack_engine: FullStackEngine | None = None
        self._full_stack_panel: FullStackPanel | None = None
        self._obstacle_panel: ObstaclePanel | None = None

        # 数据曲线图窗（延迟创建）
        self._plot_window: PlotWindow | None = None

        # 定时器驱动渲染
        self._render_timer = QTimer(self)
        self._render_timer.setTimerType(Qt.PreciseTimer)
        self._render_timer.timeout.connect(self._sim_step)

        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()

        # 初始状态：已停止，等待用户手动启动
        self._update_toolbar_state()
        # 初始化状态面板显示
        self._refresh_status_display()

    # ========== UI 构建 ==========

    def _setup_ui(self):
        self.setWindowTitle("电动宽体矿卡 — 仿真测试平台 v1.0")
        self.resize(1600, 950)
        self.setMinimumSize(1100, 650)

        # 中央部件
        central = QWidget(self)
        self.setCentralWidget(central)

        # 主布局
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # --- 左侧：模式面板栈 + 惯导面板 ---
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # QStackedWidget 管理不同模式的操作面板
        self._mode_stack = QStackedWidget(self)
        self._mode_stack.setFixedWidth(350)
        self._mode_stack.setStyleSheet(
            "QStackedWidget { background: #1a1a2e; }"
            "QStackedWidget > QWidget { background: #1a1a2e; }"
        )

        self.control_panel = ControlPanel(self)
        self.control_panel.setFixedWidth(350)
        self.control_panel.set_min_turn_radius(self._params.min_turn_radius)
        self.control_panel.emergency_stop_triggered.connect(self._on_emergency_stop)
        self.control_panel.mode_changed.connect(self._on_mode_changed)
        self.control_panel.trajectory_load_requested.connect(self._on_trajectory_load)
        self.control_panel.trajectory_generate_requested.connect(self._on_trajectory_generate)
        self.control_panel.trajectory_clear_requested.connect(self._on_trajectory_clear)
        self._mode_stack.addWidget(self.control_panel)  # index 0: 基础模式

        self._full_stack_panel = FullStackPanel(self)
        self._full_stack_panel.setFixedWidth(350)
        self._mode_stack.addWidget(self._full_stack_panel)  # index 1: 全栈模式

        left_layout.addWidget(self._mode_stack)

        self.ins_panel = InsPanel(self)
        self.ins_panel.setFixedWidth(350)
        self.ins_panel.ins_data_applied.connect(self._on_ins_applied)
        self.ins_panel.ins_data_reset.connect(self._on_ins_reset)
        left_layout.addWidget(self.ins_panel)

        left_widget = QWidget(self)
        left_widget.setLayout(left_layout)
        left_widget.setFixedWidth(350)
        self._left_widget = left_widget  # 保存引用，用于强制布局重算

        left_scroll = QScrollArea(self)
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(False)
        left_scroll.setFixedWidth(366)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: #1a1a2e; }")

        # --- 中间：2D 地图视图 ---
        self.map_view = MapView(self._params, self)
        self.map_view.setMinimumWidth(500)

        # --- 右侧：状态面板 + 障碍物面板 ---
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.status_panel = StatusPanel(self)
        self.status_panel.setFixedWidth(350)
        right_layout.addWidget(self.status_panel)

        self._obstacle_panel = ObstaclePanel(self)
        self._obstacle_panel.setFixedWidth(350)
        self._obstacle_panel.obstacle_add_requested.connect(self._on_obstacle_add)
        self._obstacle_panel.obstacle_remove_requested.connect(self._on_obstacle_remove)
        self._obstacle_panel.obstacle_clear_all_requested.connect(self._on_obstacle_clear)
        self._obstacle_panel.preset_load_requested.connect(self._on_obstacle_preset)
        self._obstacle_panel.hide()
        right_layout.addWidget(self._obstacle_panel)

        right_widget = QWidget(self)
        right_widget.setLayout(right_layout)
        right_widget.setFixedWidth(350)
        self._right_widget = right_widget  # 保存引用，用于强制布局重算

        right_scroll = QScrollArea(self)
        right_scroll.setWidget(right_widget)
        right_scroll.setWidgetResizable(False)
        right_scroll.setFixedWidth(306)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setStyleSheet("QScrollArea { border: none; background: #1a1a2e; }")

        # 不使用 QSplitter（避免潜在崩溃），使用固定布局
        main_layout.addWidget(left_scroll)
        main_layout.addWidget(self.map_view, 1)  # stretch=1
        main_layout.addWidget(right_scroll)

        # 整体深色样式
        self.setStyleSheet("""
            QMainWindow {
                background: #1a1a2e;
            }
            QWidget {
                background: #1a1a2e;
            }
            QToolBar {
                background: #16213e;
                border-bottom: 1px solid #2a3a5c;
                spacing: 4px;
                padding: 4px 6px;
            }
            QToolBar QToolButton {
                color: #e0e8f0;
                font-size: 13px;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 3px;
            }
            QToolBar QToolButton:hover {
                background: #2a3a5c;
            }
            QToolBar QToolButton:pressed {
                background: #1a2a44;
            }
            QToolBar QToolButton:disabled {
                color: #555566;
            }
            QComboBox {
                background: #16213e;
                color: #e0e8f0;
                border: 1px solid #2a3a5c;
                border-radius: 2px;
                padding: 2px 6px;
            }
            QComboBox QAbstractItemView {
                background: #16213e;
                color: #e0e8f0;
                selection-background-color: #2a3a5c;
                border: 1px solid #2a3a5c;
            }
            QComboBox::drop-down {
                background: #1a2a44;
                border: none;
            }
            QMenu {
                background: #16213e;
                color: #e0e8f0;
                border: 1px solid #2a3a5c;
            }
            QMenu::item:selected {
                background: #2a3a5c;
            }
        """)

    def _setup_toolbar(self):
        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # 启动按钮
        self._action_start = QAction("▶ 启动", self)
        self._action_start.setShortcut("F5")
        self._action_start.triggered.connect(self._on_start)
        toolbar.addAction(self._action_start)

        # 暂停/继续按钮
        self._action_pause = QAction("⏯ 暂停", self)
        self._action_pause.setShortcut("Space")
        self._action_pause.triggered.connect(self._on_toggle_pause)
        toolbar.addAction(self._action_pause)

        # 停止按钮
        self._action_stop = QAction("⏹ 停止", self)
        self._action_stop.setShortcut("Esc")
        self._action_stop.triggered.connect(self._on_stop)
        toolbar.addAction(self._action_stop)

        # 重置按钮
        action_reset = QAction("↺ 重置", self)
        action_reset.setShortcut("Ctrl+R")
        action_reset.triggered.connect(self._on_reset)
        toolbar.addAction(action_reset)

        toolbar.addSeparator()

        # 缩放按钮
        action_zoom_in = QAction("🔍+ 放大", self)
        action_zoom_in.triggered.connect(lambda: self.map_view.zoom_in())
        toolbar.addAction(action_zoom_in)

        action_zoom_out = QAction("🔍- 缩小", self)
        action_zoom_out.triggered.connect(lambda: self.map_view.zoom_out())
        toolbar.addAction(action_zoom_out)

        action_fit = QAction("⊞ 适应", self)
        action_fit.setShortcut("F")
        action_fit.triggered.connect(self.map_view.fit_view)
        toolbar.addAction(action_fit)

        toolbar.addSeparator()

        # 参数加载按钮（预留）
        action_load_param = QAction("📂 加载参数", self)
        action_load_param.triggered.connect(self._on_load_params)
        toolbar.addAction(action_load_param)

        # 重载控制配置按钮
        action_reload_config = QAction("📝 重载控制配置", self)
        action_reload_config.triggered.connect(self._on_reload_control_config)
        toolbar.addAction(action_reload_config)

        # 数据曲线按钮
        action_plot = QAction("📈 数据曲线", self)
        action_plot.triggered.connect(self._on_show_plot_window)
        toolbar.addAction(action_plot)

        # 关于
        action_about = QAction("ℹ 关于", self)
        action_about.triggered.connect(self._on_about)
        toolbar.addAction(action_about)

        toolbar.addSeparator()

        # 全栈模式切换
        self._action_full_stack = QAction("车端全栈", self)
        self._action_full_stack.setCheckable(True)
        self._action_full_stack.triggered.connect(self._on_toggle_full_stack)
        toolbar.addAction(self._action_full_stack)

    def _setup_statusbar(self):
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self._status_sim_time = QLabel("T: 0.00s", self)
        self._status_rtf = QLabel("RTF: —", self)
        self._status_mode = QLabel("● 已停止", self)

        # 设置醒目的字体颜色
        style = "color: #00ff88; font-size: 13px; font-weight: bold; padding: 0 8px;"
        self._status_sim_time.setStyleSheet(style)
        self._status_rtf.setStyleSheet("color: #ffcc00; font-size: 13px; font-weight: bold; padding: 0 8px;")
        self._status_mode.setStyleSheet("color: #ff6666; font-size: 13px; font-weight: bold; padding: 0 8px;")

        self.status_bar.addWidget(self._status_sim_time)
        self.status_bar.addWidget(self._status_rtf)
        self.status_bar.addPermanentWidget(self._status_mode)

        # 状态栏整体背景色
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background: #0d1117;
                border-top: 2px solid #30363d;
                padding: 2px 4px;
            }
        """)

    def _refresh_status_display(self):
        """刷新状态面板和地图视图为当前仿真引擎状态"""
        state = self._sim_engine.state
        trail_x, trail_y = self._sim_engine.get_trail_points()
        self.map_view.update_state(state, trail_x, trail_y)
        self.status_panel.update_state(
            state,
            self._sim_engine.dt,
            self._sim_engine.sim_time,
            self._sim_engine.real_time_factor,
            self.control_panel.get_steer_sw_deg(),
            self._params.wheelbase,
        )
        self._status_sim_time.setText(f"T: {self._sim_engine.sim_time:.2f}s")
        self._status_rtf.setText("RTF: —")

        # 全栈模式: 同步云端状态
        if self._sim_mode == self.MODE_FULL_STACK and self._full_stack_engine is not None:
            self._refresh_cloud_display()

    # ========== 仿真控制 ==========

    def _update_toolbar_state(self):
        """根据仿真状态更新工具栏按钮和状态栏"""
        if not self._sim_engine.running:
            # 已停止
            self._action_start.setEnabled(True)
            self._action_start.setText("▶ 启动")
            self._action_pause.setEnabled(False)
            self._action_pause.setText("⏯ 暂停")
            self._action_stop.setEnabled(False)
            self._status_mode.setText("● 已停止")
            self._status_mode.setStyleSheet(
                "color: #ff6666; font-size: 13px; font-weight: bold; padding: 0 8px;"
            )
            self._status_rtf.setText("RTF: —")
            self.ins_panel.set_editable(True)
        elif self._sim_engine.paused:
            # 已暂停
            self._action_start.setEnabled(False)
            self._action_start.setText("▶ 启动")
            self._action_pause.setEnabled(True)
            self._action_pause.setText("▶ 继续")
            self._action_stop.setEnabled(True)
            self._status_mode.setText("⏸ 已暂停")
            self._status_mode.setStyleSheet(
                "color: #ffcc00; font-size: 13px; font-weight: bold; padding: 0 8px;"
            )
            self.ins_panel.set_editable(True)
        else:
            # 运行中
            self._action_start.setEnabled(False)
            self._action_start.setText("▶ 启动")
            self._action_pause.setEnabled(True)
            self._action_pause.setText("⏯ 暂停")
            self._action_stop.setEnabled(True)
            self._status_mode.setText("▶ 运行中")
            self._status_mode.setStyleSheet(
                "color: #00ff88; font-size: 13px; font-weight: bold; padding: 0 8px;"
            )
            self.ins_panel.set_editable(False)

    def _start_render(self):
        """启动渲染定时器"""
        interval_ms = int(1000 / 60)  # 60 FPS
        self._render_timer.start(interval_ms)

    def _stop_render(self):
        """停止渲染定时器"""
        self._render_timer.stop()

    def _sim_step(self):
        """每帧更新（定时器回调）"""
        if not self._sim_engine.running:
            return

        if self._sim_mode == self.MODE_FULL_STACK:
            # 全栈模式：FullStackEngine.step() 内部处理一切
            self._sim_engine.step()
            return

        if self._sim_engine.control_mode == ControlMode.MANUAL:
            # 手动模式：从控制面板读取控制输入
            self._sim_engine.target_velocity_kmh = self.control_panel.get_velocity_kmh()
            self._sim_engine.target_steer_sw_deg = self.control_panel.get_steer_sw_deg()
            self._sim_engine.target_gear = self.control_panel.get_gear()
            self._sim_engine.target_brake_pressure = self.control_panel.get_brake_pressure()
        # 自动模式：控制输入在 sim_engine.step() 内部由控制器生成

        # 执行仿真步
        self._sim_engine.step()

    def _on_sim_state_updated(self, state: VehicleState):
        """仿真状态更新回调"""
        if self._sim_mode == self.MODE_FULL_STACK and self._full_stack_engine:
            self._on_full_stack_state_updated(state)
            return

        # 更新 2D 视图
        trail_x, trail_y = self._sim_engine.get_trail_points()
        self.map_view.update_state(state, trail_x, trail_y)

        # 自动模式：更新预瞄点（使用控制器的实际预瞄参数）
        if self._sim_engine.control_mode == ControlMode.AUTO and self._sim_engine.last_cmd:
            cmd = self._sim_engine.last_cmd
            traj = self._sim_engine.trajectory
            if traj and self._sim_engine.controller:
                lat_ctrl = self._sim_engine.controller.lat_controller
                lookahead = lat_ctrl.lookahead_distance + abs(state.v) * lat_ctrl.lookahead_speed_gain
                lookahead_pt = traj.get_lookahead_point(state.x, state.y, lookahead)
                if lookahead_pt:
                    self.map_view.set_lookahead_point(lookahead_pt.x, lookahead_pt.y)

            # 更新跟踪误差
            self.status_panel.update_tracking_errors(
                cmd.cross_track_error,
                cmd.heading_error,
                cmd.speed_error,
            )
        else:
            self.map_view.clear_lookahead()
            self.status_panel.update_tracking_errors(None, None, None)

        # 更新状态面板
        steer_sw = self.control_panel.get_steer_sw_deg()
        if self._sim_engine.control_mode == ControlMode.AUTO and self._sim_engine.last_cmd:
            steer_sw = self._sim_engine.last_cmd.steer_angle * self._sim_engine.params.steer_ratio
        self.status_panel.update_state(
            state,
            self._sim_engine.dt,
            self._sim_engine.sim_time,
            self._sim_engine.real_time_factor,
            steer_sw,
            self._params.wheelbase,
        )

        # 更新状态栏
        self._status_sim_time.setText(f"T: {self._sim_engine.sim_time:.2f}s")
        self._status_rtf.setText(f"RTF: {self._sim_engine.real_time_factor:.2f}x")

    # ========== 事件槽 ==========

    def _on_start(self):
        """启动仿真（保持当前位姿，仅清除轨迹和时间）"""
        if self._sim_engine.running:
            return

        # 新日志会话
        from sim_platform.main import new_log_session
        new_log_session()

        # 全栈模式: 启动时连接云端 (对应 C++ InitMqtt → InitAuthentication)
        if self._sim_mode == self.MODE_FULL_STACK and self._full_stack_engine is not None:
            self._full_stack_engine.connect_cloud()

        self._sim_engine.clear_history()
        self._sim_engine.start()
        self._start_render()
        self._update_toolbar_state()
        self._refresh_status_display()
        self.status_bar.showMessage("仿真已启动 — 云端连接中...", 2000)

    def _on_stop(self):
        """停止仿真"""
        self._sim_engine.stop()
        self._stop_render()
        self._update_toolbar_state()

        # 全栈模式: 停止时断开云端
        if self._sim_mode == self.MODE_FULL_STACK and self._full_stack_engine is not None:
            self._full_stack_engine.disconnect_cloud()

        self.status_bar.showMessage("仿真已停止", 2000)

    def _on_toggle_pause(self):
        """切换暂停/继续"""
        if not self._sim_engine.running:
            return
        self._sim_engine.toggle_pause()
        self._update_toolbar_state()
        if self._sim_engine.paused:
            self.status_bar.showMessage("仿真已暂停 — 按空格键继续", 3000)
        else:
            self.status_bar.showMessage("仿真已继续", 2000)

    def _on_reset(self):
        """重置仿真到初始状态（含清除轨迹和切回手动模式）"""
        was_running = self._sim_engine.running
        self._sim_engine.stop()
        self._sim_engine.reset()
        # 清除自动模式轨迹
        self._sim_engine.set_trajectory(Trajectory())
        self.map_view.clear_reference_trajectory()
        self.map_view.clear_lookahead()
        if self._sim_engine.control_mode == ControlMode.AUTO:
            self._sim_engine.set_control_mode(ControlMode.MANUAL)
            self.control_panel.set_mode("manual")
        self.control_panel.set_velocity_kmh(0.0)
        self.control_panel.set_steer_sw_deg(0.0)
        self.control_panel.set_gear(2)   # 默认 N 档
        self.control_panel.set_brake_pressure(0.0)
        # 如果之前在运行，重置后自动重新启动
        if was_running:
            self._sim_engine.start()
            self._start_render()
        else:
            self._stop_render()
        self._refresh_status_display()
        self.map_view.center_on(0.0, 0.0)
        self._update_toolbar_state()
        self.status_bar.showMessage("仿真已重置", 2000)

    def _on_ins_applied(self, data: InsData):
        """惯导数据应用：将 INS 位姿（WGS84 经纬度+地理航向）转换为局部 ENU 坐标后写入车辆初始状态"""
        # 仅允许在停止或暂停状态下应用
        if self._sim_engine.running and not self._sim_engine.paused:
            self.status_bar.showMessage("⚠ 运行中无法应用惯导数据，请先暂停或停止", 3000)
            return

        # ── 坐标转换: WGS84 经纬度 → 局部 ENU ──
        # INS 数据设定局部坐标系参考原点，车辆位置作为原点 ENU(0,0)
        # 后续加载的轨迹 WGS84 坐标均基于此原点转换
        if self._sim_mode == self.MODE_FULL_STACK and self._full_stack_engine is not None:
            if data.latitude != 0.0 or data.longitude != 0.0:
                self._full_stack_engine._converter.set_reference(data.latitude, data.longitude)
                self._full_stack_engine._ref_lat = data.latitude
                self._full_stack_engine._ref_lon = data.longitude
            data.local_x = 0.0
            data.local_y = 0.0
            # 地理航向 (0=北, CW, deg) → 数学角度 (0=东, CCW, deg)
            theta_deg = (90.0 - data.heading_geo) % 360.0
            if theta_deg > 180.0:
                theta_deg -= 360.0
            data.yaw = theta_deg

        was_running = self._sim_engine.running
        self._sim_engine.stop()
        self._sim_engine.reset(data.to_vehicle_state(), clear_trail=False)
        # 同步重置控制面板
        self.control_panel.set_velocity_kmh(0.0)
        self.control_panel.set_steer_sw_deg(0.0)
        self.control_panel.set_gear(2)
        self.control_panel.set_brake_pressure(0.0)
        # 更新视图并跳转到车辆位置
        self._refresh_status_display()
        self.map_view.center_on(data.local_x, data.local_y)
        self._update_toolbar_state()
        self._stop_render()

        x, y = data.local_x, data.local_y
        self.status_bar.showMessage(
            f"惯导数据已应用: Lat={data.latitude:.6f}°, Lon={data.longitude:.6f}°, "
            f"Heading={data.heading_geo:.1f}° → ENU({x:.2f}, {y:.2f}) — 按 F5 启动仿真", 5000
        )

    def _on_ins_reset(self):
        """惯导数据重置：恢复默认原点状态"""
        if self._sim_engine.running and not self._sim_engine.paused:
            self.status_bar.showMessage("⚠ 运行中无法重置惯导数据，请先暂停或停止", 3000)
            return

        self._sim_engine.stop()
        self._sim_engine.reset()
        self.control_panel.set_velocity_kmh(0.0)
        self.control_panel.set_steer_sw_deg(0.0)
        self.control_panel.set_gear(2)
        self.control_panel.set_brake_pressure(0.0)
        self._refresh_status_display()
        self.map_view.center_on(0.0, 0.0)
        self._update_toolbar_state()
        self._stop_render()
        self.status_bar.showMessage("惯导数据已重置为原点", 2000)

    def _on_mode_changed(self, mode: str):
        """控制模式切换"""
        if self._sim_engine.running and not self._sim_engine.paused:
            self.status_bar.showMessage("⚠ 运行中无法切换模式，请先暂停或停止", 3000)
            self.control_panel.set_mode("manual" if self._sim_engine.control_mode == ControlMode.MANUAL else "auto")
            return

        if mode == "auto":
            if not self._sim_engine.trajectory:
                self.status_bar.showMessage("⚠ 请先加载或生成参考轨迹", 3000)
                self.control_panel.set_mode("manual")
                return
            if not self._sim_engine.controller:
                controller = LatLonController(self._params, config=self._control_config)
                self._sim_engine.set_controller(controller)
            self._sim_engine.set_control_mode(ControlMode.AUTO)
            self.status_bar.showMessage("已切换到自动模式 — 轨迹跟踪", 3000)
        else:
            self._sim_engine.set_control_mode(ControlMode.MANUAL)
            self.map_view.clear_lookahead()
            self.status_bar.showMessage("已切换到手动模式", 2000)

    def _on_trajectory_load(self):
        """加载轨迹文件"""
        if self._sim_engine.running and not self._sim_engine.paused:
            self.status_bar.showMessage("⚠ 请先暂停或停止仿真", 3000)
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "加载轨迹文件", "",
            "轨迹文件 (*.csv *.json);;CSV 文件 (*.csv);;JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return

        try:
            if path.endswith(".json"):
                traj = Trajectory.from_json(path)
            else:
                traj = Trajectory.from_csv(path)

            if not traj:
                QMessageBox.warning(self, "加载失败", "轨迹文件为空或格式不正确")
                return

            self._sim_engine.set_trajectory(traj)
            self._update_map_trajectory(traj)
            self.status_bar.showMessage(
                f"已加载轨迹: {path} ({len(traj)} 个路径点, 总长 {traj.length:.1f}m)", 5000)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"轨迹文件解析失败:\n{e}")

    def _on_trajectory_generate(self, traj_type: str):
        """生成测试轨迹 — 车辆不动，轨迹按偏差偏移生成"""
        if self._sim_engine.running and not self._sim_engine.paused:
            self.status_bar.showMessage("⚠ 请先暂停或停止仿真", 3000)
            return

        # 读取用户设定的偏差
        cte = self.control_panel.get_trajectory_cte()
        heading_err_deg = self.control_panel.get_trajectory_heading_error()
        heading_err_rad = math.radians(heading_err_deg)

        # 车辆位置不动，计算轨迹偏移原点
        # CTE > 0: 轨迹在车辆左侧 → controller cross_track_error > 0
        # HE > 0: 轨迹航向 > 车辆航向 → controller heading_error > 0
        state = self._sim_engine.state
        vx, vy, vh = state.x, state.y, state.theta

        tx = vx - cte * math.sin(vh)
        ty = vy + cte * math.cos(vh)
        th = vh + heading_err_rad

        length = self.control_panel.get_trajectory_length()
        radius = self.control_panel.get_trajectory_radius()
        velocity = self.control_panel.get_trajectory_velocity()

        if traj_type == "straight":
            traj = Trajectory.generate_straight(
                length=length, velocity=velocity, heading=0.0,
                origin_x=tx, origin_y=ty, origin_heading=th)
            desc = f"直线 {length:.0f}m"
        elif traj_type == "circle":
            traj = Trajectory.generate_circle(
                radius=radius, velocity=velocity,
                origin_x=tx, origin_y=ty, origin_heading=th)
            desc = f"圆形 R={radius:.0f}m"
        elif traj_type == "lane_change":
            traj = Trajectory.generate_lane_change(
                length=length, lateral_offset=3.5, velocity=velocity,
                origin_x=tx, origin_y=ty, origin_heading=th)
            desc = f"变道 {length:.0f}m"
        else:
            return

        self._sim_engine.set_trajectory(traj)
        self._update_map_trajectory(traj)

        dev_desc = ""
        if abs(cte) > 1e-4 or abs(heading_err_rad) > 1e-4:
            dev_desc = f" CTE={cte:+.1f}m HE={heading_err_deg:+.1f}°"

        self.map_view.center_on(vx, vy)
        self._refresh_status_display()
        self.status_bar.showMessage(
            f"已生成 {desc} 轨迹 ({len(traj)} 个路径点, 总长 {traj.length:.1f}m){dev_desc}", 5000)

    def _on_trajectory_clear(self):
        """清除轨迹"""
        self._sim_engine.set_trajectory(Trajectory())
        self.map_view.clear_reference_trajectory()
        # 如果在自动模式，切回手动
        if self._sim_engine.control_mode == ControlMode.AUTO:
            self._sim_engine.set_control_mode(ControlMode.MANUAL)
            self.control_panel.set_mode("manual")
        self.status_bar.showMessage("参考轨迹已清除", 2000)

    def _update_map_trajectory(self, traj: Trajectory):
        """将轨迹数据同步到地图视图"""
        xs = [p.x for p in traj.points]
        ys = [p.y for p in traj.points]
        self.map_view.set_reference_trajectory(xs, ys)

    def _on_emergency_stop(self):
        """急停处理：仅停车，仿真继续运行"""
        self._sim_engine.emergency_stop()
        # 同步控制面板显示
        self.control_panel.set_velocity_kmh(0.0)
        self.control_panel.set_brake_pressure(self._params.max_brake_pressure)
        # 不暂停仿真，让用户看到车辆已停止
        self.status_bar.showMessage("⚠ 急停已触发！速度归零，最大制动", 5000)

    def _on_load_params(self):
        """加载车辆参数文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "加载车辆参数", "",
            "YAML 文件 (*.yaml *.yml);;所有文件 (*)"
        )
        if path:
            try:
                new_params = VehicleParams.from_yaml(path)
                self._params = new_params
                self.control_panel.set_min_turn_radius(new_params.min_turn_radius)
                # 停止旧引擎
                self._sim_engine.stop()
                self._stop_render()
                # 创建新引擎
                self._sim_engine = SimEngine(new_params)
                self._sim_engine.set_state_callback(self._on_sim_state_updated)
                # 新 params 可能改变了 wheelbase 等，重新加载 control config 并重建控制器
                self._control_config = ControlConfig.load()
                controller = LatLonController(new_params, config=self._control_config)
                self._sim_engine.set_controller(controller)
                # 如果图窗已打开，切换到新引擎的 logger
                if self._plot_window is not None:
                    self._plot_window.set_logger(self._sim_engine.data_logger)
                # 重置到初始状态
                self._on_reset()
                self.status_bar.showMessage(f"已加载参数: {path}", 3000)
            except Exception as e:
                QMessageBox.warning(self, "加载失败", f"参数文件加载失败:\n{e}")

    def _on_reload_control_config(self):
        """重新加载 control_config.ini 并重建控制器"""
        try:
            self._control_config = ControlConfig.load()
            # 重建控制器（使用新的配置参数）
            controller = LatLonController(self._params, config=self._control_config)
            self._sim_engine.set_controller(controller)
            self.status_bar.showMessage(
                "控制配置已重载: "
                f"wheelbase={self._control_config.wheel_base}m, "
                f"lookahead={self._control_config.lookahead_distance}m, "
                f"max_steer={self._control_config.max_steer_angle}°",
                4000,
            )
        except Exception as e:
            QMessageBox.warning(self, "重载失败", f"控制配置文件加载失败:\n{e}")

    def _on_show_plot_window(self):
        """打开/激活数据曲线图窗"""
        if self._plot_window is None:
            self._plot_window = PlotWindow(self._sim_engine.data_logger, self)
        self._plot_window.show()
        self._plot_window.raise_()
        self._plot_window.activateWindow()

    def _on_about(self):
        QMessageBox.about(
            self,
            "关于",
            "电动宽体矿卡无人驾驶仿真测试平台 v1.0\n\n"
            "基于阿克曼转向运动学模型\n"
            "提供自主仿真与车辆状态可视化\n\n"
            "© 2026 Simulation Platform",
        )

    # ========== 全栈模式 ==========

    def _on_toggle_full_stack(self, checked: bool):
        """切换全栈仿真模式"""
        if self._sim_engine.running:
            self._sim_engine.stop()
            self._stop_render()

        if checked:
            self._enter_full_stack_mode()
        else:
            self._exit_full_stack_mode()

        self._refresh_status_display()
        self._update_toolbar_state()

    def _enter_full_stack_mode(self):
        """进入全栈仿真模式"""
        self._sim_mode = self.MODE_FULL_STACK

        controller = LatLonController(self._params, config=self._control_config)
        self._full_stack_engine = FullStackEngine(
            self._params, controller=controller
        )
        self._full_stack_engine.set_state_callback(self._on_sim_state_updated)
        self._sim_engine = self._full_stack_engine

        # QStackedWidget 切换：0=control_panel → 1=_full_stack_panel
        self._mode_stack.setCurrentIndex(1)
        self._relayout_left_panels()

        # 右侧：显示障碍物面板
        self._obstacle_panel.show()
        self._relayout_side_panels()

        self._action_full_stack.setText("车端全栈 ✓")
        self.setWindowTitle("电动宽体矿卡 — 仿真测试平台 v1.0 [全栈模式]")
        self.status_bar.showMessage("已切换到全栈仿真模式 — 按 F5 启动仿真并连接云端", 5000)

    def _exit_full_stack_mode(self):
        """退出全栈仿真模式"""
        self._sim_mode = self.MODE_BASIC

        self._sim_engine = SimEngine(self._params)
        self._sim_engine.set_state_callback(self._on_sim_state_updated)

        controller = LatLonController(self._params, config=self._control_config)
        self._sim_engine.set_controller(controller)

        if self._full_stack_engine:
            self._full_stack_engine.disconnect_cloud()
        self._full_stack_engine = None

        # QStackedWidget 切换：1=_full_stack_panel → 0=control_panel
        self._mode_stack.setCurrentIndex(0)
        self._relayout_left_panels()

        # 右侧：隐藏障碍物面板
        self._obstacle_panel.hide()
        self._relayout_side_panels()

        self.map_view.clear_reference_trajectory()
        self.map_view.clear_obstacles()
        self.map_view.clear_lookahead()

        self._action_full_stack.setText("车端全栈")
        self._action_full_stack.setChecked(False)
        self.setWindowTitle("电动宽体矿卡 — 仿真测试平台 v1.0")
        self.status_bar.showMessage("已切换到基础仿真模式", 3000)

    def _relayout_side_panels(self):
        """更新右侧 widget 尺寸以适配障碍物面板的 show/hide"""
        w = self._right_widget
        if w:
            w.layout().invalidate()
            w.layout().activate()
            hint = w.sizeHint()
            w.setFixedSize(350, hint.height())
            w.update()

    def _relayout_left_panels(self):
        """更新左侧 mode_stack 及其父布局以消除页面切换残留"""
        stack = self._mode_stack
        stack.updateGeometry()
        stack.repaint()
        w = self._left_widget
        if w:
            w.layout().invalidate()
            w.layout().activate()
            hint = w.sizeHint()
            w.setFixedSize(350, hint.height())
            w.update()

    def _on_full_stack_state_updated(self, state: VehicleState):
        """全栈模式下的状态更新回调"""
        engine = self._full_stack_engine
        if engine is None:
            return

        trail_x, trail_y = engine.get_trail_points()
        self.map_view.update_state(state, trail_x, trail_y)

        # 始终显示完整参考线 (ref_mgr 持久保留所有点，不随车辆移动改变)
        all_pts = engine.ref_mgr.get_all_points()
        if all_pts:
            xs = [p.x for p in all_pts]
            ys = [p.y for p in all_pts]
            self.map_view.set_reference_trajectory(xs, ys)

        obstacles = engine.perception.get_all_obstacles()
        self.map_view.set_obstacles(obstacles)
        self._obstacle_panel.update_obstacle_list(obstacles)

        cmd = engine.latest_control_cmd
        if cmd:
            self.status_panel.update_tracking_errors(
                cmd.cross_track_error, cmd.heading_error, cmd.speed_error
            )

        self.status_panel.update_state(
            state,
            engine.dt,
            engine.sim_time,
            engine.real_time_factor,
            engine.target_steer_sw_deg,
            self._params.wheelbase,
        )

        task_sn = engine.gateway.current_task_sn
        task_type = {1: "装载", 2: "卸载", 10: "靠边停车"}.get(
            engine.gateway.current_task_type, str(engine.gateway.current_task_type)
        )
        task_status = {0: "空闲", 1: "执行中", 2: "完成"}.get(
            engine.gateway.task_status, "未知"
        )
        self._full_stack_panel.set_task_info(task_sn, task_type, task_status)

        if engine.planning_traj and len(engine.planning_traj) > 1:
            idx = engine.planning_traj.find_closest_index(state.x, state.y)
            progress = (idx / (len(engine.planning_traj) - 1)) * 100.0
            self._full_stack_panel.set_progress(progress)

        gw_status = {0: "空闲", 1: "执行中", 2: "完成"}.get(engine.gateway.task_status, "—")
        gw_color = "#00ff88" if engine.gateway.task_status == 1 else "#b0c0d0"
        self._full_stack_panel.set_module_status("Gateway", gw_status, gw_color)

        plan_status = "有任务" if engine.planning.has_task else "无任务"
        plan_color = "#00ff88" if engine.planning.has_task else "#b0c0d0"
        self._full_stack_panel.set_module_status("Planning", plan_status, plan_color)

        perc_status = f"{engine.perception.obstacle_count} 障碍物" if engine.perception.obstacle_count > 0 else "无数据"
        perc_color = "#00ff88" if engine.perception.obstacle_count > 0 else "#b0c0d0"
        self._full_stack_panel.set_module_status("Perception", perc_status, perc_color)

        self._refresh_cloud_display()

        # 路权信息
        self._full_stack_panel.set_move_authority(engine.latest_move_authority)

        # 驾驶状态 (StatusType 上行字段)
        cloud_stats = engine.cloud.get_stats()
        self._full_stack_panel.set_vehicle_status({
            "driving_mode": 1,
            "acc_state": 1,
            "gps_state": 3,
            "gear": state.gear,
            "brake": 1 if state.brake_pressure > 0 else 0,
            "lock": 0,
            "emergency_brake": 0,
            "load_state": cloud_stats.get("load_state", 3),
        })

        ctrl_status = "活跃" if engine.latest_control_cmd is not None else "空闲"
        ctrl_color = "#00ff88" if engine.latest_control_cmd is not None else "#b0c0d0"
        self._full_stack_panel.set_module_status("Control", ctrl_status, ctrl_color)

        self._status_sim_time.setText(f"T: {engine.sim_time:.2f}s")
        self._status_rtf.setText(f"RTF: {engine.real_time_factor:.2f}x")
        self._status_mode.setText("▶ 全栈运行中")
        self._status_mode.setStyleSheet(
            "color: #00ff88; font-size: 13px; font-weight: bold; padding: 0 8px;"
        )

    def _refresh_cloud_display(self):
        """刷新云端状态全流程显示（鉴权→参数→地图→任务→消息）

        仅在仿真运行时显示云端通信状态，停止时显示 "—"。
        """
        engine = self._full_stack_engine
        if engine is None:
            return

        if not engine.running:
            # 仿真未启动，不显示云端连接状态
            self._full_stack_panel.set_module_status("Cloud", "—", "#555566")
            self._full_stack_panel.set_cloud_info({"state": "disconnected"})
            self._full_stack_panel.set_downlink_params({})
            self._full_stack_panel.set_uplink_fields({})
            self._full_stack_panel.set_move_authority(None)
            return

        cloud_stats = engine.cloud.get_stats()
        cloud_state = cloud_stats.get("state", "disconnected")

        # Cloud 模块状态文字
        cloud_status_labels = {
            "disconnected": ("断开", "#ff4444"),
            "connecting": ("连接中", "#ffcc00"),
            "connected": ("已连接", "#ffcc00"),
            "authenticating": ("鉴权中", "#ffcc00"),
            "authenticated": ("已鉴权", "#00ff88"),
            "running": ("运行中", "#00ff88"),
        }
        label, color = cloud_status_labels.get(cloud_state, ("未知", "#ff4444"))
        self._full_stack_panel.set_module_status("Cloud", label, color)

        # 云端状态全流程详情
        self._full_stack_panel.set_cloud_info(cloud_stats)
        # 下行参数 (云端下发的服务器参数)
        self._full_stack_panel.set_downlink_params(cloud_stats)
        # 上行发送字段 (停车原因等)
        uplink_stats = engine.gateway.get_uplink_stats()
        self._full_stack_panel.set_uplink_fields(uplink_stats)

    def _on_obstacle_add(self, x, y, length, width, heading, speed, obs_type):
        if self._full_stack_engine:
            obs_id = self._full_stack_engine.perception.add_obstacle(
                x, y, length, width, heading, speed, obs_type
            )
            self.status_bar.showMessage(f"障碍物已添加 ID={obs_id}", 2000)

    def _on_obstacle_remove(self, obs_id):
        if self._full_stack_engine:
            self._full_stack_engine.perception.remove_obstacle(obs_id)

    def _on_obstacle_clear(self):
        if self._full_stack_engine:
            self._full_stack_engine.perception.clear_all()

    def _on_obstacle_preset(self, preset_name: str):
        if self._full_stack_engine:
            self._full_stack_engine.perception.load_preset(preset_name)
            self.status_bar.showMessage(f"障碍物场景已加载: {preset_name}", 2000)

    # ========== 窗口关闭 ==========

    def closeEvent(self, event):
        self._render_timer.stop()
        self._sim_engine.stop()
        if self._full_stack_engine:
            self._full_stack_engine.disconnect_cloud()
        super().closeEvent(event)
