"""2D 地图视图 — 俯视鸟瞰车辆运动"""

import math
from typing import Optional, Tuple

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPolygonF,
    QPainterPath, QTransform,
)

from ..models.vehicle_params import VehicleParams
from ..core.vehicle_state import VehicleState


class MapView(QWidget):
    """2D 俯视地图视图
    绘制车辆、轨迹、网格、坐标轴。
    """

    def __init__(self, params: VehicleParams, parent=None):
        super().__init__(parent)
        self.params = params
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        # 视图状态
        self._state: Optional[VehicleState] = None
        self._trail_x: list[float] = []
        self._trail_y: list[float] = []

        # 参考轨迹
        self._ref_traj_x: list[float] = []
        self._ref_traj_y: list[float] = []
        self._lookahead_x: float = 0.0
        self._lookahead_y: float = 0.0
        self._has_lookahead: bool = False

        # 障碍物
        self._obstacles: list = []

        # 平移 & 缩放
        self._offset_x: float = 0.0
        self._offset_y: float = 0.0
        self._default_scale: float = 10.0  # 默认像素/米（矿卡约9.5m → 95px）
        self._scale: float = self._default_scale
        self._min_scale: float = 0.1
        self._max_scale: float = 80.0

        # 鼠标交互
        self._panning: bool = False
        self._last_mouse_pos: Optional[QPointF] = None

        # 颜色
        self._bg_color = QColor(26, 26, 46)
        self._grid_color = QColor(255, 255, 255, 20)
        self._grid_color_minor = QColor(255, 255, 255, 8)
        self._vehicle_color = QColor(0, 255, 136)
        self._trail_color = QColor(0, 212, 255)
        self._text_color = QColor(200, 208, 224)
        self._axis_color = QColor(255, 255, 255, 60)

        self.setFocusPolicy(Qt.StrongFocus)

    # ========== 公共接口 ==========

    def update_state(self, state: VehicleState, trail_x: list[float], trail_y: list[float]):
        """更新当前车辆状态和轨迹"""
        self._state = state
        self._trail_x = trail_x
        self._trail_y = trail_y
        self.update()

    def set_reference_trajectory(self, traj_x: list[float], traj_y: list[float]):
        """设置参考轨迹"""
        self._ref_traj_x = traj_x
        self._ref_traj_y = traj_y
        self.update()

    def set_lookahead_point(self, x: float, y: float):
        """设置预瞄点"""
        self._lookahead_x = x
        self._lookahead_y = y
        self._has_lookahead = True
        self.update()

    def clear_lookahead(self):
        self._has_lookahead = False
        self.update()

    def clear_reference_trajectory(self):
        self._ref_traj_x.clear()
        self._ref_traj_y.clear()
        self._has_lookahead = False
        self.update()

    def set_obstacles(self, obstacles: list):
        """设置障碍物列表"""
        self._obstacles = obstacles
        self.update()

    def clear_obstacles(self):
        self._obstacles.clear()
        self.update()

    def set_scale(self, scale: float):
        self._scale = max(self._min_scale, min(self._max_scale, scale))
        self.update()

    def zoom_in(self):
        self.set_scale(self._scale * 1.2)

    def zoom_out(self):
        self.set_scale(self._scale / 1.2)

    def center_on(self, wx: float, wy: float):
        """将视图平移到以世界坐标 (wx, wy) 为中心"""
        self._offset_x = -wx
        self._offset_y = wy
        self.update()

    def fit_view(self):
        """适应窗口（回到默认缩放和原点）"""
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._scale = self._default_scale
        self.update()

    def reset_view(self):
        self.fit_view()

    # ========== 坐标变换 ==========

    def _world_to_screen(self, wx: float, wy: float) -> Tuple[float, float]:
        """世界坐标 → 屏幕坐标 (左上角原点)"""
        sx = (wx + self._offset_x) * self._scale + self.width() / 2
        sy = (-wy + self._offset_y) * self._scale + self.height() / 2
        return sx, sy

    def _screen_to_world(self, sx: float, sy: float) -> Tuple[float, float]:
        """屏幕坐标 → 世界坐标"""
        wx = (sx - self.width() / 2) / self._scale - self._offset_x
        wy = -((sy - self.height() / 2) / self._scale - self._offset_y)
        return wx, wy

    # ========== 事件处理 ==========

    def wheelEvent(self, event):
        """滚轮缩放"""
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 1 / 1.1
        # 以鼠标位置为中心缩放
        mx, my = event.pos().x(), event.pos().y()
        wx_before, wy_before = self._screen_to_world(mx, my)
        self._scale = max(self._min_scale, min(self._max_scale, self._scale * factor))
        wx_after, wy_after = self._screen_to_world(mx, my)
        self._offset_x += wx_after - wx_before
        self._offset_y += wy_after - wy_before
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._panning and self._last_mouse_pos is not None:
            dx = event.pos().x() - self._last_mouse_pos.x()
            dy = event.pos().y() - self._last_mouse_pos.y()
            self._offset_x += dx / self._scale
            self._offset_y += dy / self._scale
            self._last_mouse_pos = event.pos()
            self.update()
        # 显示世界坐标（状态栏用）
        wx, wy = self._screen_to_world(event.pos().x(), event.pos().y())
        self.setToolTip(f"World: ({wx:.2f}, {wy:.2f}) m")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._panning = False
            self._last_mouse_pos = None
            self.setCursor(Qt.ArrowCursor)

    def keyPressEvent(self, event):
        """键盘快捷键"""
        if event.key() == Qt.Key_Plus or event.key() == Qt.Key_Equal:
            self.zoom_in()
        elif event.key() == Qt.Key_Minus:
            self.zoom_out()
        elif event.key() == Qt.Key_F:
            self.fit_view()
        elif event.key() == Qt.Key_R:
            self.reset_view()

    # ========== 绘制 ==========

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0 or self._scale <= 0:
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            # 背景
            painter.fillRect(0, 0, w, h, self._bg_color)

            # 网格
            self._draw_grid(painter)

            # 参考轨迹
            self._draw_reference_trajectory(painter)

            # 障碍物
            self._draw_obstacles(painter)

            # 预瞄点
            if self._has_lookahead:
                self._draw_lookahead_point(painter)

            # 轨迹
            self._draw_trail(painter)

            # 车辆
            self._draw_vehicle(painter)

            # 比例尺
            self._draw_scale_bar(painter)

            # 坐标信息
            self._draw_coord_info(painter)

        except Exception:
            pass
        finally:
            painter.end()

    def _draw_grid(self, painter: QPainter):
        """绘制坐标网格"""
        w, h = self.width(), self.height()

        # 计算合适的网格间距
        grid_spacing = 10.0  # 默认 10m
        # 根据缩放调整
        pixel_spacing = grid_spacing * self._scale
        while pixel_spacing < 30:
            grid_spacing *= 2
            pixel_spacing = grid_spacing * self._scale
        while pixel_spacing > 120:
            grid_spacing /= 2
            pixel_spacing = grid_spacing * self._scale

        # 计算网格起始位置
        wx_min, wy_min = self._screen_to_world(0, h)
        wx_max, wy_max = self._screen_to_world(w, 0)

        # 大网格
        pen_major = QPen(self._grid_color, 1, Qt.SolidLine)
        painter.setPen(pen_major)

        start_x = math.floor(wx_min / grid_spacing) * grid_spacing
        x = start_x
        while x <= wx_max:
            sx, _ = self._world_to_screen(x, 0)
            painter.drawLine(int(sx), 0, int(sx), h)
            x += grid_spacing

        start_y = math.floor(wy_min / grid_spacing) * grid_spacing
        y = start_y
        while y <= wy_max:
            _, sy = self._world_to_screen(0, y)
            painter.drawLine(0, int(sy), w, int(sy))
            y += grid_spacing

        # 小网格（5等分）
        minor_spacing = grid_spacing / 5
        pen_minor = QPen(self._grid_color_minor, 1, Qt.DotLine)
        painter.setPen(pen_minor)

        x = start_x - grid_spacing
        while x <= wx_max + grid_spacing:
            sx, _ = self._world_to_screen(x, 0)
            painter.drawLine(int(sx), 0, int(sx), h)
            x += minor_spacing

        y = start_y - grid_spacing
        while y <= wy_max + grid_spacing:
            _, sy = self._world_to_screen(0, y)
            painter.drawLine(0, int(sy), w, int(sy))
            y += minor_spacing

        # 坐标轴（X=0, Y=0 加粗）
        pen_axis = QPen(self._axis_color, 1.5, Qt.SolidLine)
        painter.setPen(pen_axis)
        origin_sx, origin_sy = self._world_to_screen(0, 0)
        painter.drawLine(int(origin_sx), 0, int(origin_sx), h)
        painter.drawLine(0, int(origin_sy), w, int(origin_sy))

    def _draw_trail(self, painter: QPainter):
        """绘制车辆行驶轨迹"""
        if len(self._trail_x) < 2:
            return

        painter.setPen(QPen(self._trail_color, 2, Qt.SolidLine))
        painter.setBrush(Qt.NoBrush)

        path = QPainterPath()
        first = True
        for wx, wy in zip(self._trail_x, self._trail_y):
            sx, sy = self._world_to_screen(wx, wy)
            if first:
                path.moveTo(sx, sy)
                first = False
            else:
                path.lineTo(sx, sy)
        painter.drawPath(path)

    def _draw_reference_trajectory(self, painter: QPainter):
        """绘制参考轨迹（绿色虚线）"""
        if len(self._ref_traj_x) < 2:
            return

        pen = QPen(QColor(0, 220, 100, 180), 2, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        path = QPainterPath()
        first = True
        for wx, wy in zip(self._ref_traj_x, self._ref_traj_y):
            sx, sy = self._world_to_screen(wx, wy)
            if first:
                path.moveTo(sx, sy)
                first = False
            else:
                path.lineTo(sx, sy)
        painter.drawPath(path)

    def _draw_obstacles(self, painter: QPainter):
        """绘制障碍物（黄色填充矩形 + ID 标签）"""
        for obs in self._obstacles:
            if not obs.corners:
                continue
            corners_screen = []
            for cx, cy in obs.corners:
                sx, sy = self._world_to_screen(cx, cy)
                corners_screen.append(QPointF(sx, sy))

            # 填充
            fill_color = QColor(255, 180, 40, 80) if obs.obstacle_type == 0 else QColor(255, 80, 40, 100)
            painter.setPen(QPen(QColor(255, 180, 40, 200), 2, Qt.SolidLine))
            painter.setBrush(QBrush(fill_color))
            painter.drawPolygon(QPolygonF(corners_screen))

            # 中心标签
            sx, sy = self._world_to_screen(obs.center_x, obs.center_y)
            font = QFont("Arial", 8)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 200))
            painter.drawText(int(sx) + 4, int(sy) - 4, f"#{obs.id}")

    def _draw_lookahead_point(self, painter: QPainter):
        """绘制预瞄点（高亮空心圆 + 十字线）"""
        sx, sy = self._world_to_screen(self._lookahead_x, self._lookahead_y)

        # 外圈
        painter.setPen(QPen(QColor(255, 200, 60, 220), 2.5, Qt.SolidLine))
        painter.setBrush(QBrush(QColor(255, 200, 60, 40)))
        r = 6
        painter.drawEllipse(QPointF(sx, sy), r, r)

        # 十字线
        painter.setPen(QPen(QColor(255, 200, 60, 180), 1.5, Qt.SolidLine))
        cross = 10
        painter.drawLine(int(sx - cross), int(sy), int(sx + cross), int(sy))
        painter.drawLine(int(sx), int(sy - cross), int(sx), int(sy + cross))

    def _draw_vehicle(self, painter: QPainter):
        """绘制车辆俯视图（含车身、车轮及转向状态）"""
        if self._state is None:
            return

        state = self._state
        p = self.params

        L = p.wheelbase          # 轴距
        W = p.width              # 车宽
        Tf = p.front_track       # 前轮距
        Tr = p.rear_track        # 后轮距
        total_len = p.length     # 车总长
        l_f = p.front_overhang   # 前悬
        l_r = p.rear_overhang    # 后悬
        r_tire = p.tire_radius   # 轮胎半径
        steer = state.steer_angle

        cos_t = math.cos(state.theta)
        sin_t = math.sin(state.theta)

        # ========== 辅助：车辆坐标 → 屏幕坐标 ==========
        def veh_to_screen(vx: float, vy: float) -> tuple[float, float]:
            """车辆局部坐标 (vx 前, vy 左) → 屏幕坐标"""
            wx = state.x + vx * cos_t - vy * sin_t
            wy = state.y + vx * sin_t + vy * cos_t
            return self._world_to_screen(wx, wy)

        # ========== 1. 绘制轨迹（后轴中心轨迹）==========
        # （轨迹已在 _draw_trail 中绘制，此处不重复）

        # ========== 2. 绘制车身 ==========
        rear_to_back = l_r
        rear_to_front = total_len - l_r

        # 车身轮廓
        body_corners_local = [
            (rear_to_front, -W / 2),   # 左前
            (rear_to_front, W / 2),    # 右前
            (-rear_to_back, W / 2),    # 右后
            (-rear_to_back, -W / 2),   # 左后
        ]
        body_corners_screen = [
            QPointF(*veh_to_screen(vx, vy)) for vx, vy in body_corners_local
        ]

        # 车身填充（半透明深色）
        painter.setPen(QPen(QColor(0, 200, 120), 2, Qt.SolidLine))
        painter.setBrush(QBrush(QColor(0, 180, 100, 40)))
        body_poly = QPolygonF(body_corners_screen)
        painter.drawPolygon(body_poly)

        # ========== 3. 绘制驾驶室（前部区域） ==========
        cab_front = rear_to_front
        cab_rear = L * 0.55  # 驾驶室后沿约在前轴后一点
        cab_width = W * 0.85
        cab_corners_local = [
            (cab_front - 0.3, -cab_width / 2),
            (cab_front - 0.3, cab_width / 2),
            (cab_rear, cab_width / 2),
            (cab_rear, -cab_width / 2),
        ]
        cab_corners_screen = [
            QPointF(*veh_to_screen(vx, vy)) for vx, vy in cab_corners_local
        ]
        painter.setPen(QPen(QColor(0, 220, 160, 150), 1.5, Qt.SolidLine))
        painter.setBrush(QBrush(QColor(0, 200, 140, 25)))
        cab_poly = QPolygonF(cab_corners_screen)
        painter.drawPolygon(cab_poly)

        # ========== 4. 绘制前后保险杠 ==========
        # 前保险杠线
        fb_left = veh_to_screen(rear_to_front, -W / 2)
        fb_right = veh_to_screen(rear_to_front, W / 2)
        painter.setPen(QPen(QColor(255, 80, 60, 200), 3, Qt.SolidLine))
        painter.drawLine(QPointF(*fb_left), QPointF(*fb_right))

        # 后保险杠线
        rb_left = veh_to_screen(-rear_to_back, -W / 2)
        rb_right = veh_to_screen(-rear_to_back, W / 2)
        painter.setPen(QPen(QColor(150, 150, 160, 180), 2.5, Qt.SolidLine))
        painter.drawLine(QPointF(*rb_left), QPointF(*rb_right))

        # ========== 5. 绘制车轮 ==========
        # 车轮尺寸（局部坐标）
        wheel_len = r_tire * 1.6    # 轮胎长度（沿车身纵向）
        wheel_wid = r_tire * 0.55   # 轮胎宽度（沿车身横向）

        # 前轴中心位置 (L, 0)
        # 后轴中心位置 (0, 0)
        wheel_positions = [
            # (轴x, 横向偏移, 是否转向轮, 标签)
            (L, -Tf / 2, True),    # 左前轮
            (L, Tf / 2, True),     # 右前轮
            (0, -Tr / 2, False),   # 左后轮
            (0, Tr / 2, False),    # 右后轮
        ]

        for ax_x, lat_offset, is_steerable in wheel_positions:
            self._draw_wheel(
                painter, state, ax_x, lat_offset,
                wheel_len, wheel_wid, is_steerable, steer
            )

        # ========== 6. 车头方向箭头 ==========
        # 箭头从后轴中点出发，延伸出车头，表示车辆前进方向
        rear_sx, rear_sy = veh_to_screen(0, 0)
        arrow_len = rear_to_front + 2.0    # 超出车头 2m
        arrow_x = state.x + arrow_len * cos_t
        arrow_y = state.y + arrow_len * sin_t
        arrow_sx, arrow_sy = self._world_to_screen(arrow_x, arrow_y)

        # 屏幕空间的车辆方向 (世界 Y 翻转)
        screen_dir_x = cos_t
        screen_dir_y = -sin_t
        norm = math.hypot(screen_dir_x, screen_dir_y)
        if norm > 0:
            screen_dir_x /= norm
            screen_dir_y /= norm
        perp_x = -screen_dir_y
        perp_y = screen_dir_x

        painter.setPen(QPen(QColor(0, 255, 136, 200), 2.5, Qt.SolidLine))
        painter.drawLine(int(rear_sx), int(rear_sy), int(arrow_sx), int(arrow_sy))

        # 箭头三角 — 在屏幕空间计算，保证尖端指向正确
        head_len = 8.0
        head_width = 4.0
        painter.setBrush(QBrush(QColor(0, 255, 136, 200)))
        painter.setPen(Qt.NoPen)
        p_tip = QPointF(arrow_sx, arrow_sy)
        p_left = QPointF(
            arrow_sx - head_len * screen_dir_x + head_width * perp_x,
            arrow_sy - head_len * screen_dir_y + head_width * perp_y,
        )
        p_right = QPointF(
            arrow_sx - head_len * screen_dir_x - head_width * perp_x,
            arrow_sy - head_len * screen_dir_y - head_width * perp_y,
        )
        painter.drawPolygon(QPolygonF([p_tip, p_left, p_right]))

        # ========== 7. 后轴中心标记点 ==========
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 255, 136)))
        painter.drawEllipse(QPointF(rear_sx, rear_sy), 3, 3)

    def _draw_wheel(
        self, painter: QPainter, state, ax_x: float, lat_offset: float,
        wheel_len: float, wheel_wid: float, is_steerable: bool, steer_angle: float,
    ):
        """绘制单个车轮

        Args:
            ax_x: 轴在车辆坐标系中的 x 位置（前为正）
            lat_offset: 车轮横向偏移（左为负）
            is_steerable: 是否为转向轮
            steer_angle: 前轮转角 (rad)，仅对转向轮生效
        """
        cos_t = math.cos(state.theta)
        sin_t = math.sin(state.theta)

        # 车轮中心在世界坐标
        wx_c = state.x + ax_x * cos_t - lat_offset * sin_t
        wy_c = state.y + ax_x * sin_t + lat_offset * cos_t

        # 车轮方向角
        if is_steerable:
            wheel_theta = state.theta + steer_angle
        else:
            wheel_theta = state.theta

        cos_w = math.cos(wheel_theta)
        sin_w = math.sin(wheel_theta)

        # 车轮四个角（局部：x 沿车轮方向，y 垂直于车轮方向）
        hw_len = wheel_len / 2
        hw_wid = wheel_wid / 2
        corners_local = [
            (hw_len, -hw_wid),
            (hw_len, hw_wid),
            (-hw_len, hw_wid),
            (-hw_len, -hw_wid),
        ]

        corners_screen = []
        for dx, dy in corners_local:
            sx = wx_c + dx * cos_w - dy * sin_w
            sy = wy_c + dx * sin_w + dy * cos_w
            corners_screen.append(QPointF(*self._world_to_screen(sx, sy)))

        # 车轮颜色：转向轮用黄色，非转向轮用灰白色
        if is_steerable:
            wheel_color = QColor(255, 180, 40, 220)
            wheel_fill = QColor(255, 180, 40, 60)
        else:
            wheel_color = QColor(180, 190, 200, 200)
            wheel_fill = QColor(180, 190, 200, 40)

        painter.setPen(QPen(wheel_color, 1.5, Qt.SolidLine))
        painter.setBrush(QBrush(wheel_fill))
        painter.drawPolygon(QPolygonF(corners_screen))

        # 转向轮画中心十字线
        if is_steerable and abs(steer_angle) > 0.01:
            cx_s, cy_s = self._world_to_screen(wx_c, wy_c)
            cross_len = wheel_len * 0.35
            # 沿车轮方向
            c1_sx, c1_sy = self._world_to_screen(
                wx_c + cross_len * cos_w, wy_c + cross_len * sin_w
            )
            c2_sx, c2_sy = self._world_to_screen(
                wx_c - cross_len * cos_w, wy_c - cross_len * sin_w
            )
            painter.setPen(QPen(QColor(255, 220, 80, 150), 1, Qt.SolidLine))
            painter.drawLine(int(c1_sx), int(c1_sy), int(c2_sx), int(c2_sy))

    def _draw_scale_bar(self, painter: QPainter):
        """左下角比例尺"""
        w, h = self.width(), self.height()
        bar_x = 20
        bar_y = h - 30

        # 计算合适的比例尺长度（取整十米）
        target_pixel = 80
        bar_meters = target_pixel / self._scale
        # 向上取整到 1, 2, 5, 10, 20, 50, 100...
        nice = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
        for n in nice:
            if n >= bar_meters:
                bar_meters = n
                break
        bar_pixels = int(bar_meters * self._scale)

        painter.setPen(QPen(self._text_color, 1, Qt.SolidLine))
        painter.setBrush(QBrush(self._text_color))
        painter.drawLine(bar_x, bar_y, bar_x + bar_pixels, bar_y)
        painter.drawLine(bar_x, bar_y - 5, bar_x, bar_y + 5)
        painter.drawLine(bar_x + bar_pixels, bar_y - 5, bar_x + bar_pixels, bar_y + 5)

        font = QFont("Arial", 9)
        painter.setFont(font)
        if bar_meters >= 1000:
            label = f"{bar_meters / 1000:.0f} km"
        else:
            label = f"{bar_meters:.0f} m"
        painter.drawText(bar_x, bar_y - 8, label)

    def _draw_coord_info(self, painter: QPainter):
        """左上角坐标信息"""
        if self._state is None:
            return

        state = self._state
        font = QFont("Consolas", 9)
        painter.setFont(font)
        painter.setPen(self._text_color)

        lines = [
            f"X: {state.x:8.2f} m",
            f"Y: {state.y:8.2f} m",
            f"θ: {state.theta_deg:7.2f}°",
            f"v: {state.v_kmh:7.2f} km/h",
        ]

        x0, y0 = 10, 20
        for i, line in enumerate(lines):
            painter.drawText(x0, y0 + i * 18, line)
