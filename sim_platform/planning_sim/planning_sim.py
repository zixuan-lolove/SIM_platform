"""Planning 仿真编排器 — 10Hz 规划循环 (F-09)

串联: RTKPlanner → VelocityPlanner → BusinessDecision
通过 SimMessageBus 订阅输入、发布 PlanningResult。
"""

import time
from typing import Optional

from ..core.sim_message_bus import (
    SimMessageBus,
    TASK_TO_PLANNING,
    MOVE_AUTHORITY,
    LOCALIZATION,
    CHASSIS,
    OBSTACLES,
    PLANNING_RESULT,
)
from ..models.sim_messages import (
    TaskToPlanning,
    MoveAuthority,
    Localization,
    Chassis,
    Obstacle,
    PlanningResult,
    Action,
    TaskTraj,
)
from ..gateway_sim.reference_line_mgr import ReferenceLineManager
from .rtk_planner import RTKPlanner
from .business_decision import BusinessDecision


class PlanningFrame:
    """单次规划周期的输入数据聚合 — 等价于 C++ planning::PlanningFrame

    汇集一次 plan() 调用所需的所有输入，由 PlanningSim 填充后
    传给 BusinessDecision.proc()。
    """

    def __init__(self):
        self.localization: Optional[Localization] = None
        self.chassis: Optional[Chassis] = None
        self.obstacles: list[Obstacle] = []
        self.move_authority: Optional[MoveAuthority] = None
        self.ref_mgr: Optional[ReferenceLineManager] = None
        self.action_seq: list[Action] = []
        self.task_finish: bool = False

        # 规划中间状态
        self.key_index: int = 0
        self.stop: bool = False
        self.lift_cmd: int = 0
        self.is_over_time: bool = False

        # 传感器时间戳 (用于超时检测)
        self.last_localization_time: float = 0.0
        self.last_chassis_time: float = 0.0
        self.last_obstacles_time: float = 0.0

        # 新任务标志
        self._new_task: bool = False
        self._pending_task: Optional[TaskToPlanning] = None

    def task_received(self) -> bool:
        return self._new_task

    def accept_task(self) -> Optional[TaskToPlanning]:
        """消费新任务标志，返回 TaskToPlanning 并清除标志"""
        self._new_task = False
        task = self._pending_task
        self._pending_task = None
        return task

    def set_new_task(self, task: TaskToPlanning) -> None:
        self._new_task = True
        self._pending_task = task


class PlanningSim:
    """Planning 仿真器 — 10Hz 规划循环编排 (F-09-09)

    订阅:
      - TaskToPlanning   ← GatewaySim 下发新任务
      - MoveAuthority     ← GatewaySim 下发路权
      - Localization      ← Kinematics 定位
      - Chassis           ← Kinematics 底盘
      - Obstacles         ← PerceptionSim 障碍物

    发布:
      - PlanningResult    → Controller 控制指令生成
    """

    def __init__(self, bus: SimMessageBus, ref_mgr: ReferenceLineManager):
        self._bus = bus
        self._ref_mgr = ref_mgr

        self._rtk_planner = RTKPlanner()
        self._decision = BusinessDecision()

        # 输入缓存
        self._latest_localization: Optional[Localization] = None
        self._latest_chassis: Optional[Chassis] = None
        self._latest_obstacles: list[Obstacle] = []
        self._latest_move_authority: Optional[MoveAuthority] = None

        # 任务状态
        self._action_seq: list[Action] = []
        self._task_traj: Optional[TaskTraj] = None

        # 传感器时间戳
        self._last_localization_time: float = 0.0
        self._last_chassis_time: float = 0.0
        self._last_obstacles_time: float = 0.0

        # 订阅
        self._bus.subscribe(TASK_TO_PLANNING, self._on_task_to_planning)
        self._bus.subscribe(MOVE_AUTHORITY, self._on_move_authority)
        self._bus.subscribe(LOCALIZATION, self._on_localization)
        self._bus.subscribe(CHASSIS, self._on_chassis)
        self._bus.subscribe(OBSTACLES, self._on_obstacles)

    @property
    def reference_line_manager(self) -> ReferenceLineManager:
        return self._ref_mgr

    @property
    def has_task(self) -> bool:
        return self._task_traj is not None and len(self._task_traj.points) > 0

    @property
    def action_seq(self) -> list[Action]:
        return self._action_seq

    # ========== Bus 回调 ==========

    def _on_task_to_planning(self, topic: str, msg: TaskToPlanning) -> None:
        self._handle_new_task(msg)

    def _on_move_authority(self, topic: str, msg: MoveAuthority) -> None:
        self._latest_move_authority = msg

    def _on_localization(self, topic: str, msg: Localization) -> None:
        self._latest_localization = msg
        self._last_localization_time = msg.timestamp

    def _on_chassis(self, topic: str, msg: Chassis) -> None:
        self._latest_chassis = msg
        self._last_chassis_time = msg.timestamp

    def _on_obstacles(self, topic: str, msg: list[Obstacle]) -> None:
        self._latest_obstacles = list(msg)
        if msg:
            self._last_obstacles_time = msg[0].timestamp

    # ========== 主规划入口 (由 FullStackEngine 以 10Hz 调用) ==========

    def plan(self, sim_time: float) -> Optional[PlanningResult]:
        """执行一次规划周期

        Returns:
            PlanningResult (已发布到 SimMessageBus)，无任务/无定位时返回 None
        """
        if not self.has_task:
            return None
        if self._latest_localization is None:
            return None

        t_start = time.perf_counter()

        # 构建 PlanningFrame
        frame = PlanningFrame()
        frame.localization = self._latest_localization
        frame.chassis = self._latest_chassis
        frame.obstacles = list(self._latest_obstacles)
        frame.move_authority = self._latest_move_authority
        frame.ref_mgr = self._ref_mgr
        frame.action_seq = list(self._action_seq)
        frame.last_localization_time = self._last_localization_time
        frame.last_chassis_time = self._last_chassis_time
        frame.last_obstacles_time = self._last_obstacles_time

        # 步骤 1: 业务决策 (任务状态机、超时检测、key_index 更新、路权处理)
        self._decision.proc(frame, sim_time)

        # 步骤 2: RTK 规划 (参考线截取 → 障碍物处理 → 速度规划)
        trajectory, updated_stop = self._rtk_planner.plan(
            ref_line=self._ref_mgr.current,
            key_index=frame.key_index,
            stop_index=self._ref_mgr.stop_index,
            obstacles=frame.obstacles if frame.obstacles else None,
        )

        if not trajectory:
            return None

        self._ref_mgr.stop_index = updated_stop

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        result = PlanningResult(
            points=trajectory,
            lift_cmd=frame.lift_cmd,
            task_finish=frame.task_finish,
            stop=frame.stop,
            planner_type="rtk",
            planning_time_ms=elapsed_ms,
            timestamp=sim_time,
        )

        self._bus.publish(PLANNING_RESULT, result)
        return result

    # ========== 任务处理 ==========

    def _handle_new_task(self, task: TaskToPlanning) -> None:
        """收到新任务: B 样条平滑 → 构建参考线 → 重置决策状态"""
        task_traj = task.task_traj
        if not task_traj.points:
            return

        self._task_traj = task_traj
        self._ref_mgr.update_from_task(task_traj)
        self._action_seq = list(task.action_seq)
        self._decision.reset()

    def reset(self) -> None:
        """重置 Planning 状态"""
        self._decision.reset()
        self._task_traj = None
        self._action_seq.clear()
        self._latest_move_authority = None
        self._latest_obstacles.clear()
