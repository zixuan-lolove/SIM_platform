"""感知仿真模块 — 障碍物管理，20Hz 发布到 SimMessageBus (F-12)"""

import math
from typing import Optional

from ..core.sim_message_bus import SimMessageBus, OBSTACLES
from ..models.sim_messages import Obstacle


class PerceptionSim:
    """感知仿真器

    管理障碍物列表，按 20Hz 周期发布到 SimMessageBus 的 OBSTACLES topic。

    职责:
    - 静态障碍物的增删改查
    - 动态障碍物位置更新（匀速直线运动）
    - 周期性发布障碍物列表 (20Hz)
    """

    def __init__(self, bus: SimMessageBus, publish_interval_s: float = 0.05):
        self._bus = bus
        self._publish_interval_s = publish_interval_s  # 50ms = 20Hz
        self._obstacles: dict[int, Obstacle] = {}
        self._next_id: int = 1
        self._last_publish_time: float = 0.0

    @property
    def obstacle_count(self) -> int:
        return len(self._obstacles)

    def add_obstacle(
        self,
        center_x: float,
        center_y: float,
        length: float = 3.0,
        width: float = 2.0,
        heading: float = 0.0,
        speed: float = 0.0,
        obstacle_type: int = 0,
    ) -> int:
        """添加障碍物，返回 obstacle ID

        Args:
            center_x, center_y: 障碍物中心 ENU 坐标 (m)
            length, width: 障碍物尺寸 (m)
            heading: 朝向角 (rad)
            speed: 速度 (m/s), 0=静态
            obstacle_type: 0=静态, 1=动态
        """
        obs_id = self._next_id
        self._next_id += 1
        corners = self._calc_corners(center_x, center_y, length, width, heading)
        self._obstacles[obs_id] = Obstacle(
            id=obs_id,
            corners=corners,
            center_x=center_x,
            center_y=center_y,
            length=length,
            width=width,
            heading=heading,
            speed=speed,
            obstacle_type=obstacle_type,
        )
        return obs_id

    def remove_obstacle(self, obs_id: int) -> bool:
        """删除指定 ID 的障碍物"""
        if obs_id in self._obstacles:
            del self._obstacles[obs_id]
            return True
        return False

    def update_obstacle(
        self,
        obs_id: int,
        center_x: Optional[float] = None,
        center_y: Optional[float] = None,
        length: Optional[float] = None,
        width: Optional[float] = None,
        heading: Optional[float] = None,
        speed: Optional[float] = None,
    ) -> bool:
        """更新障碍物属性"""
        obs = self._obstacles.get(obs_id)
        if obs is None:
            return False
        if center_x is not None:
            obs.center_x = center_x
        if center_y is not None:
            obs.center_y = center_y
        if length is not None:
            obs.length = length
        if width is not None:
            obs.width = width
        if heading is not None:
            obs.heading = heading
        if speed is not None:
            obs.speed = speed
        # 重算角点
        obs.corners = self._calc_corners(
            obs.center_x, obs.center_y, obs.length, obs.width, obs.heading
        )
        return True

    def clear_all(self) -> None:
        self._obstacles.clear()

    def get_all_obstacles(self) -> list[Obstacle]:
        return list(self._obstacles.values())

    def get_obstacle(self, obs_id: int) -> Optional[Obstacle]:
        return self._obstacles.get(obs_id)

    def update(self, sim_time: float, dt: float) -> None:
        """每仿真步调用:
        1. 更新动态障碍物位置
        2. 如果距上次发布时间 >= publish_interval_s，发布 Obstacles
        """
        # 动态障碍物位置更新
        for obs in self._obstacles.values():
            if obs.speed > 1e-6:
                obs.center_x += obs.speed * math.cos(obs.heading) * dt
                obs.center_y += obs.speed * math.sin(obs.heading) * dt
                obs.corners = self._calc_corners(
                    obs.center_x, obs.center_y, obs.length, obs.width, obs.heading
                )

        # 周期发布
        if sim_time - self._last_publish_time >= self._publish_interval_s:
            self.publish(sim_time)
            self._last_publish_time = sim_time

    def publish(self, sim_time: float) -> None:
        """立即发布当前障碍物列表到 SimMessageBus"""
        obstacles = list(self._obstacles.values())
        # 更新时间戳
        for obs in obstacles:
            obs.timestamp = sim_time
        self._bus.publish(OBSTACLES, obstacles, publisher="PerceptionSim")

    # ========== 预设场景 ==========

    def load_preset(self, preset_name: str) -> None:
        """加载预定义障碍物场景"""
        self.clear_all()
        if preset_name == "single_block":
            # 单个障碍物挡在参考线上 (前方 30m)
            self.add_obstacle(30.0, 0.0, length=4.0, width=2.5, heading=0.0)
        elif preset_name == "narrow_pass":
            # 窄道会车: 对向 1 个动态障碍物
            self.add_obstacle(50.0, 2.0, length=4.0, width=2.5, heading=math.pi, speed=3.0, obstacle_type=1)
        elif preset_name == "scattered":
            # 多障碍物散落
            self.add_obstacle(25.0, -2.0, length=3.0, width=2.0, heading=0.3)
            self.add_obstacle(40.0, 3.0, length=3.5, width=2.0, heading=-0.2)
            self.add_obstacle(55.0, -1.0, length=3.0, width=2.5, heading=0.1)

    @staticmethod
    def _calc_corners(
        cx: float, cy: float, length: float, width: float, heading: float
    ) -> list[tuple[float, float]]:
        """计算矩形障碍物的 4 个角点 (ENU 坐标)

        角点顺序: 前左, 前右, 后右, 后左 (closed polygon)
        """
        cos_h = math.cos(heading)
        sin_h = math.sin(heading)
        hl = length / 2.0
        hw = width / 2.0

        # 局部坐标 (x=前, y=左)
        local_corners = [
            (hl, hw),    # 前左
            (hl, -hw),   # 前右
            (-hl, -hw),  # 后右
            (-hl, hw),   # 后左
        ]

        corners = []
        for lx, ly in local_corners:
            gx = cx + lx * cos_h - ly * sin_h
            gy = cy + lx * sin_h + ly * cos_h
            corners.append((gx, gy))
        return corners
