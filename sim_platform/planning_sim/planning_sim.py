"""Planning 仿真编排器 — 10Hz 规划循环 (F-09)

串联: RTKPlanner → VelocityPlanner → BusinessDecision
通过 SimMessageBus 订阅输入、发布 PlanningResult。
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

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
        self.action_type: int = 0      # 当前执行的 action 类型 (1=STOP,2=LOAD,3=DUMP,4=LIFT)
        self.action_status: int = 0    # 0=idle, 1=executing, 2=complete
        self.advance_segment: bool = False  # 本周期发生了参考线段切换

        # 传感器时间戳 (用于超时检测)
        self.last_localization_time: float = 0.0
        self.last_chassis_time: float = 0.0
        self.last_obstacles_time: float = 0.0


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
        self._last_task_sn: str = ""    # 用于判断任务更新 vs 新任务
        self._pending_validation: bool = False  # 新任务需在 plan() 中做 2m 邻近校验

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
            if not hasattr(self, '_no_task_logged'):
                self._no_task_logged = True
                logger.warning("[PlanningSim] plan() aborted: has_task=False")
            return None
        if self._latest_localization is None:
            if not hasattr(self, '_no_loc_logged'):
                self._no_loc_logged = True
                logger.warning("[PlanningSim] plan() aborted: no localization yet")
            return None

        # 新任务 2m 邻近校验 — 推迟到 plan() 而非在 _handle_new_task 中执行，
        # 确保 FullStackEngine 已设置坐标转换器参考原点并重置车辆位置，
        # 避免因 ENU 坐标框架不一致导致误拒绝。
        if self._pending_validation:
            self._pending_validation = False
            loc = self._latest_localization
            all_pts = self._ref_mgr.get_all_points()
            if all_pts:
                min_dis_sq = min(
                    (p.x - loc.x) ** 2 + (p.y - loc.y) ** 2 for p in all_pts
                )
                min_dist = min_dis_sq ** 0.5
                if min_dist > 2.0:
                    logger.warning(
                        f"[PlanningSim] Task rejected: vehicle too far from trajectory "
                        f"(dist={min_dist:.1f}m > 2m)"
                    )
                    self._task_traj = None
                    return None
                else:
                    logger.info(f"[PlanningSim] Proximity check PASSED: "
                                f"min_dist={min_dist:.2f}m, n_pts={len(all_pts)}, "
                                f"vehicle=({loc.x:.2f},{loc.y:.2f})")

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
            action_type=frame.action_type,
            action_status=frame.action_status,
            timestamp=sim_time,
        )

        self._bus.publish(PLANNING_RESULT, result, publisher="PlanningSim")
        return result

    # ========== 任务处理 ==========

    def _handle_new_task(self, task: TaskToPlanning) -> None:
        """收到新任务: 更新参考线 → 重置决策状态

        2m 邻近校验推迟到 plan() 中执行，此时 FullStackEngine 已完成
        坐标转换器初始化及车辆位置重置，ENU 坐标框架一致。
        """
        task_traj = task.task_traj
        if not task_traj.points:
            return

        same_sn = (task.task_sn == self._last_task_sn and self._last_task_sn)
        self._task_traj = task_traj
        self._ref_mgr.update_from_task(task_traj)
        self._action_seq = list(task.action_seq)
        self._last_task_sn = task.task_sn

        if same_sn:
            # 同 sn 任务更新 (轨迹文件变化): 保留决策进度 (task_index 等)，
            # 仅做邻近校验确保车辆与新轨迹对齐
            self._pending_validation = True
            logger.info(f"[PlanningSim] Task updated (same sn={task.task_sn}): "
                        f"{len(task_traj.points)} pts, decision state preserved")
        else:
            # 新任务: 完整重置
            self._decision.reset()
            self._pending_validation = True
            logger.info(f"[PlanningSim] New task: {len(task_traj.points)} pts, "
                        f"actions={len(self._action_seq)}, "
                        f"types={[a.action_type for a in self._action_seq]}")

    def reset(self) -> None:
        """重置 Planning 状态"""
        self._decision.reset()
        self._task_traj = None
        self._action_seq.clear()
        self._last_task_sn = ""
        self._latest_move_authority = None
        self._latest_obstacles.clear()
        self._pending_validation = False
