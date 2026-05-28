"""全栈仿真面板 — 任务信息、模块状态、操作按钮 (F-15)"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFileDialog, QProgressBar,
)
from PyQt5.QtCore import Qt, pyqtSignal


class FullStackPanel(QWidget):
    """全栈仿真控制面板

    显示任务信息、各模块状态文字、操作按钮。
    """

    task_load_requested = pyqtSignal(str)  # file_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)

        # ── 任务信息 ──
        task_group = QGroupBox("任务信息")
        task_group.setStyleSheet(self._group_style())
        task_layout = QVBoxLayout(task_group)
        task_layout.setContentsMargins(3, 3, 3, 3)
        task_layout.setSpacing(2)

        self._label_task_sn = QLabel("任务编号: —")
        self._label_task_type = QLabel("任务类型: —")
        self._label_task_status = QLabel("任务状态: —")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("进度: %p%")

        for w in [self._label_task_sn, self._label_task_type, self._label_task_status]:
            w.setStyleSheet(self._label_style())
            w.setWordWrap(True)
            task_layout.addWidget(w)
        self._progress_bar.setStyleSheet(self._label_style())
        task_layout.addWidget(self._progress_bar)

        layout.addWidget(task_group)

        # ── 云端状态 ──
        cloud_group = QGroupBox("云端状态")
        cloud_group.setStyleSheet(self._group_style())
        cloud_layout = QVBoxLayout(cloud_group)
        cloud_layout.setContentsMargins(3, 3, 3, 3)
        cloud_layout.setSpacing(2)

        self._cloud_labels: dict[str, QLabel] = {}
        cloud_fields = [
            ("mqtt",    "MQTT: —"),
            ("auth",    "鉴权: —"),
            ("project", "项目: —"),
            ("params",  "参数查询: —"),
            ("map",     "地图: —"),
            ("task",    "下发任务: —"),
            ("msg",     "消息: —"),
        ]
        for key, text in cloud_fields:
            lbl = QLabel(text)
            lbl.setStyleSheet(self._label_style())
            lbl.setWordWrap(True)
            cloud_layout.addWidget(lbl)
            self._cloud_labels[key] = lbl

        layout.addWidget(cloud_group)

        # ── 下行参数 (云端下发) ──
        downlink_group = QGroupBox("下行参数 Downlink")
        downlink_group.setStyleSheet(self._group_style())
        downlink_layout = QVBoxLayout(downlink_group)
        downlink_layout.setContentsMargins(3, 3, 3, 3)
        downlink_layout.setSpacing(2)

        self._downlink_labels: dict[str, QLabel] = {}
        downlink_fields = [
            ("param_file",   "地图文件: —"),
            ("param_md5",    "文件 MD5: —"),
            ("param_url",    "下载 URL: —"),
            ("param_local",  "本地路径: —"),
        ]
        for key, text in downlink_fields:
            lbl = QLabel(text)
            lbl.setStyleSheet(self._label_style())
            lbl.setWordWrap(True)
            downlink_layout.addWidget(lbl)
            self._downlink_labels[key] = lbl

        layout.addWidget(downlink_group)

        # ── 上行发送 (停车字段) ──
        uplink_group = QGroupBox("上行发送 Uplink")
        uplink_group.setStyleSheet(self._group_style())
        uplink_layout = QVBoxLayout(uplink_group)
        uplink_layout.setContentsMargins(3, 3, 3, 3)
        uplink_layout.setSpacing(2)

        self._uplink_labels: dict[str, QLabel] = {}
        uplink_fields = [
            ("reason_code", "故障原因: —"),
            ("run_state",   "运行状态: —"),
            ("stop_reason", "停车原因: —"),
        ]
        for key, text in uplink_fields:
            lbl = QLabel(text)
            lbl.setStyleSheet(self._label_style())
            uplink_layout.addWidget(lbl)
            self._uplink_labels[key] = lbl

        layout.addWidget(uplink_group)

        # ── 模块状态 ──
        mod_group = QGroupBox("模块状态")
        mod_group.setStyleSheet(self._group_style())
        mod_layout = QVBoxLayout(mod_group)
        mod_layout.setContentsMargins(3, 3, 3, 3)
        mod_layout.setSpacing(2)

        self._mod_labels: dict[str, QLabel] = {}
        for name in ["Gateway", "Planning", "Perception", "Cloud", "Control"]:
            lbl = QLabel(f"{name}: —")
            lbl.setStyleSheet(self._label_style())
            lbl.setWordWrap(True)
            mod_layout.addWidget(lbl)
            self._mod_labels[name] = lbl

        layout.addWidget(mod_group)

        # ── 操作按钮 ──
        btn_group = QGroupBox("操作")
        btn_group.setStyleSheet(self._group_style())
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setContentsMargins(3, 3, 3, 3)
        btn_layout.setSpacing(2)

        btn_load = QPushButton("加载 .traj 任务文件")
        btn_load.clicked.connect(self._on_load_task)
        btn_load.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_load)

        layout.addWidget(btn_group)
        layout.addStretch()

    # ========== 公共接口 ==========

    def set_task_info(self, task_sn: str = "", task_type: str = "", task_status: str = ""):
        self._label_task_sn.setText(f"任务编号: {task_sn or '—'}")
        self._label_task_type.setText(f"任务类型: {task_type or '—'}")
        self._label_task_status.setText(f"任务状态: {task_status or '—'}")

    def set_progress(self, percent: float):
        self._progress_bar.setValue(int(percent))

    def set_module_status(self, name: str, text: str, color: str = "#b0c0d0"):
        """设置模块状态文字

        Args:
            name: 模块名
            text: 状态文字
            color: 状态颜色 (默认灰, 绿色=正常, 黄色=进行中, 红色=异常)
        """
        if name in self._mod_labels:
            self._mod_labels[name].setText(
                f'{name}: <span style="color:{color};">{text}</span>'
            )

    def set_cloud_info(self, stats: dict):
        """根据 cloud_stats 字典更新云端状态全流程显示

        流程: MQTT 连接 → 鉴权 → 项目 → 地图下载 → 下发任务 → 消息统计
        """
        state = stats.get("state", "disconnected")
        authenticated = stats.get("authenticated", False)
        params_queried = stats.get("params_queried", False)

        # 状态指示符: ✓=完成 →=进行中 ✗=失败 —=待定
        def _step_done(text: str) -> str:
            return f'<span style="color:#00ff88;">✓</span> {text}'
        def _step_active(text: str) -> str:
            return f'<span style="color:#ffcc00;">→</span> {text}'
        def _step_fail(text: str) -> str:
            return f'<span style="color:#ff4444;">✗</span> {text}'
        def _step_pending(text: str) -> str:
            return f'<span style="color:#555566;">—</span> {text}'

        # ── 步骤1: MQTT 连接 ──
        broker = stats.get("mqtt_broker", "—")
        if state == "disconnected":
            mqtt_text = _step_pending(f"MQTT: {broker}")
        elif state == "connecting":
            mqtt_text = _step_active(f"MQTT: {broker} — 连接中")
        elif state in ("connected", "authenticating", "authenticated", "running"):
            mqtt_text = _step_done(f"MQTT: {broker} — 已连接")
        else:
            mqtt_text = _step_fail(f"MQTT: {broker} — {state}")
        self._cloud_labels["mqtt"].setText(mqtt_text)

        # ── 步骤2: 鉴权 ──
        imei = stats.get("imei", "—")
        if state in ("disconnected", "connecting", "connected"):
            auth_text = _step_pending(f"鉴权: IMEI={imei}")
        elif state == "authenticating":
            auth_text = _step_active(f"鉴权: IMEI={imei} — 鉴权中")
        elif authenticated:
            auth_text = _step_done(f"鉴权: IMEI={imei} — 已鉴权")
        elif state in ("authenticated", "running"):
            auth_text = _step_fail(f"鉴权: IMEI={imei} — 鉴权失败")
        else:
            auth_text = _step_pending(f"鉴权: IMEI={imei}")
        self._cloud_labels["auth"].setText(auth_text)

        # ── 步骤3: 项目 ──
        project_id = stats.get("project_id", "")
        if authenticated and project_id:
            self._cloud_labels["project"].setText(
                _step_done(f"项目: {project_id}")
            )
        elif authenticated:
            self._cloud_labels["project"].setText(
                _step_active("项目: 查询中")
            )
        else:
            self._cloud_labels["project"].setText(
                _step_pending("项目: —")
            )

        # ── 步骤4: 服务器参数查询 ──
        params_query_sent = stats.get("params_query_sent", False)
        if params_queried:
            self._cloud_labels["params"].setText(
                _step_done("参数查询: 已获取")
            )
        elif params_query_sent and authenticated:
            self._cloud_labels["params"].setText(
                _step_active("参数查询: 等待应答")
            )
        elif authenticated:
            self._cloud_labels["params"].setText(
                _step_pending("参数查询: 未发送")
            )
        else:
            self._cloud_labels["params"].setText(
                _step_pending("参数查询: —")
            )

        # ── 步骤5: 地图下载 ──
        download_status = stats.get("map_download_status", "")
        if download_status == "success":
            self._cloud_labels["map"].setText(
                _step_done("地图: 已下载")
            )
        elif download_status == "failed":
            self._cloud_labels["map"].setText(
                _step_fail("地图: 下载失败")
            )
        elif download_status == "downloading":
            self._cloud_labels["map"].setText(
                _step_active("地图: 下载中")
            )
        elif params_queried:
            self._cloud_labels["map"].setText(
                _step_active("地图: 等待下载")
            )
        elif authenticated:
            self._cloud_labels["map"].setText(
                _step_pending("地图: —")
            )
        else:
            self._cloud_labels["map"].setText(
                _step_pending("地图: —")
            )

        # ── 步骤5: 下发任务状态 ──
        task_status = stats.get("task_status", 0)
        load_state = stats.get("load_state", 0)
        task_status_text = {0: "空闲", 1: "执行中", 2: "完成"}.get(task_status, str(task_status))
        load_state_text = {0: "空载", 1: "装载", 2: "卸载"}.get(load_state, str(load_state))
        if task_status > 0:
            self._cloud_labels["task"].setText(
                _step_done(f"下发任务: {task_status_text} | {load_state_text}")
            )
        elif authenticated:
            self._cloud_labels["task"].setText(
                _step_pending("下发任务: 等待下发")
            )
        else:
            self._cloud_labels["task"].setText(
                _step_pending("下发任务: —")
            )

        # ── 步骤6: 消息统计 ──
        up = stats.get("uplink_count", 0)
        down = stats.get("downlink_count", 0)
        if up > 0 or down > 0:
            self._cloud_labels["msg"].setText(
                f'消息: <span style="color:#00aaff;">↑{up}</span> '
                f'<span style="color:#00cc88;">↓{down}</span>'
            )
        else:
            self._cloud_labels["msg"].setText(
                _step_pending("消息: —")
            )

    def set_downlink_params(self, stats: dict):
        """更新下行参数显示 (云端下发的服务器参数)"""
        map_file = stats.get("map_file", "")
        map_md5 = stats.get("map_md5", "")
        download_url = stats.get("download_base_url", "")
        download_status = stats.get("map_download_status", "")
        local_path = stats.get("map_download_path", "")

        status_text = {
            "": "—",
            "downloading": '<span style="color:#ffcc00;">下载中...</span>',
            "success": '<span style="color:#00ff88;">已下载</span>',
            "failed": '<span style="color:#ff4444;">下载失败</span>',
        }.get(download_status, download_status)

        self._downlink_labels["param_file"].setText(
            f'地图文件: {map_file if map_file else "—"}  {status_text}'
        )
        self._downlink_labels["param_md5"].setText(
            f'文件 MD5: {map_md5 if map_md5 else "—"}'
        )
        self._downlink_labels["param_url"].setText(
            f'下载 URL: {download_url if download_url else "—"}'
        )
        self._downlink_labels["param_local"].setText(
            f'本地路径: {local_path if local_path else "—"}'
        )

    def set_uplink_fields(self, stats: dict):
        """更新上行发送字段显示 (停车原因等)"""
        reason_code = stats.get("reason_code", 0)
        run_state = stats.get("run_state", 0)
        stop_reason = stats.get("stop_reason", 0)

        run_state_text = {0: "待命", 1: "运行中"}.get(run_state, str(run_state))
        stop_reason_text = {0: "无(正常行驶)", 1: "终点停车", 2: "紧急停车", 3: "避障停车"}.get(stop_reason, str(stop_reason))

        self._uplink_labels["reason_code"].setText(f"故障原因: {reason_code}")
        self._uplink_labels["run_state"].setText(f"运行状态: {run_state_text}")
        self._uplink_labels["stop_reason"].setText(f"停车原因: {stop_reason_text}")

    # ========== 槽 ==========

    def _on_load_task(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载任务轨迹文件", "",
            "轨迹文件 (*.traj *.csv);;所有文件 (*)"
        )
        if path:
            self.task_load_requested.emit(path)

    # ========== 样式 ==========

    @staticmethod
    def _group_style() -> str:
        return """
            QGroupBox {
                color: #c0d0e0;
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #2a3a5c;
                border-radius: 3px;
                margin-top: 5px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 3px;
            }
        """

    @staticmethod
    def _label_style() -> str:
        return "color: #b0c0d0; font-size: 10px; background: transparent; padding: 0px;"

    @staticmethod
    def _btn_style() -> str:
        return """
            QPushButton {
                color: #e0e8f0;
                background: #2a3a5c;
                border: 1px solid #3a4a6c;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3a5a8c;
            }
            QPushButton:pressed {
                background: #1a2a44;
            }
        """
