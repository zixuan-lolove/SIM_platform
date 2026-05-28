"""业务决策 — Python 等价实现 C++ BussinessDecision (F-09-06)

负责: 任务切换检测、参考线更新、路权处理、任务完成判定、超时检测、停车判断。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .planning_sim import PlanningFrame


# 动作类型常量
UNKNOWN_ACTION = 0
STOP_ACTION = 1
LOAD_ACTION = 2
DUMP_ACTION = 3
LIFT_ACTION = 4


class BusinessDecision:
    """任务状态机与决策逻辑

    注意: dump_process 和 last_action 在 C++ 中是 static 变量 (存在重入 bug)，
    此处改正为普通成员变量。
    """

    def __init__(self):
        self._task_index: int = 0
        self._last_action: int = UNKNOWN_ACTION
        self._dump_process: int = 0  # 0=待举升, 1=举升中, 2=待下降, 3=下降中, 4=已到底
        self._dump_cycle_counter: int = 0
        self._last_localization_time: float = 0.0
        self._last_chassis_time: float = 0.0
        self._last_obstacles_time: float = 0.0

    def reset(self) -> None:
        self._task_index = 0
        self._last_action = UNKNOWN_ACTION
        self._dump_process = 0
        self._dump_cycle_counter = 0

    def proc(self, frame: "PlanningFrame", sim_time: float = 0.0) -> None:
        """每规划周期执行一次的主决策逻辑"""
        # 超时检测
        self._judge_over_time(frame, sim_time)

        # 任务更新检测
        if frame.task_received():
            frame.accept_task()
            self._task_index = 0

        # 更新 key_index (车辆在参考线上的最近点)
        self._update_key_index(frame)

        # 路权处理 (更新 stop_index)
        self._update_stop_from_authority(frame)

        # 任务完成判定
        if self._current_task_finish(frame):
            self._task_index += 1

        if frame.action_seq and self._task_index >= len(frame.action_seq):
            frame.task_finish = True

        # 超时 → 停车
        self._judge_stop(frame)

    def _update_key_index(self, frame: "PlanningFrame") -> None:
        """更新车辆在任务轨迹上的最近点索引"""
        if not frame.ref_mgr:
            return
        loc = frame.localization
        if loc is None:
            return
        frame.key_index = frame.ref_mgr.find_closest_index(loc.x, loc.y)

    def _update_stop_from_authority(self, frame: "PlanningFrame") -> None:
        """从路权信息更新停车点"""
        if frame.move_authority is not None and frame.ref_mgr:
            frame.ref_mgr.stop_index = frame.move_authority.stop_index
        # 默认: 当前参考线末尾
        elif frame.ref_mgr:
            ref = frame.ref_mgr.current
            if ref.points:
                frame.ref_mgr.stop_index = len(ref.points) - 1

    def _current_task_finish(self, frame: "PlanningFrame") -> bool:
        """判断当前动作是否完成"""
        if not frame.action_seq or self._task_index >= len(frame.action_seq):
            return False

        action = frame.action_seq[self._task_index]

        if action.action_type == STOP_ACTION:
            # 接近停车点 (8 个点以内) → 完成
            if frame.key_index > frame.ref_mgr.stop_index - 8:
                frame.stop = True
                return True
            frame.stop = False
            return False

        elif action.action_type == LOAD_ACTION:
            # 装载: 到达即停车 (TODO: 需平台确认装载完成信号)
            frame.stop = True
            return False  # 等待外部确认

        elif action.action_type == DUMP_ACTION:
            return self._handle_dump_action(frame, action)

        elif action.action_type == LIFT_ACTION:
            frame.lift_cmd = 1  # UP
            frame.stop = True
            return False  # 等待外部确认

        self._last_action = action.action_type
        return False

    # 每个举升/下降阶段持续的规划周期数（10Hz 下 30 周期 ≈ 3s）
    _DUMP_CYCLES_PER_STAGE: int = 30

    def _handle_dump_action(self, frame: "PlanningFrame", action) -> bool:
        """卸载动作状态机 (修正了 C++ 中的 static 变量 bug)

        状态:
          0=待举升 → 1=举升中 → 2=待下降 → 3=下降中 → 4=完成
        """
        from .planning_sim import PlanningFrame  # noqa: F811

        if self._last_action != DUMP_ACTION:
            self._dump_process = 0
            self._dump_cycle_counter = 0

        self._dump_cycle_counter += 1

        if self._dump_process == 0:
            frame.lift_cmd = 1  # UP
            if self._dump_cycle_counter >= self._DUMP_CYCLES_PER_STAGE:
                self._dump_process = 2
                self._dump_cycle_counter = 0
            return False
        elif self._dump_process == 2:
            frame.lift_cmd = -1  # DOWN
            if self._dump_cycle_counter >= self._DUMP_CYCLES_PER_STAGE:
                self._dump_process = 4
                self._dump_cycle_counter = 0
            return False
        elif self._dump_process == 4:
            frame.lift_cmd = 0  # KEEP
            self._last_action = action.action_type
            return True

        return False

    def _judge_over_time(self, frame: "PlanningFrame", sim_time: float) -> None:
        """检测传感器数据超时 (> 500ms)"""
        frame.is_over_time = False

        loc_age = sim_time - frame.last_localization_time
        ch_age = sim_time - frame.last_chassis_time
        obs_age = sim_time - frame.last_obstacles_time

        if loc_age > 0.5 or ch_age > 0.5 or obs_age > 0.5:
            frame.is_over_time = True

    def _judge_stop(self, frame: "PlanningFrame") -> None:
        """超时 → 停车"""
        if frame.is_over_time:
            frame.stop = True
