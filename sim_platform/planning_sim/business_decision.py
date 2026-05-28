"""业务决策 — Python 等价实现 C++ BussinessDecision (F-09-06)

负责: 任务切换检测、参考线更新、路权处理、任务完成判定、超时检测、停车判断。
"""

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

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
        """每规划周期执行一次的主决策逻辑 — 对应 C++ BussinessDecision::proc

        注意: 2m 任务邻近校验已移至 PlanningSim._handle_new_task，
        在消息到达时立即执行（早于 plan() 周期），保证拒绝任务时
        不会更新参考线，与 C++ 行为一致。
        """
        # 超时检测
        self._judge_over_time(frame, sim_time)

        # 更新 key_index (C++ line 53: 在完整 task_trajectory 上查找)
        self._update_key_index(frame)

        # 路权处理 (C++ lines 34-51: 无条件计算 autor_index + min-tracking + clamp)
        self._update_stop_from_authority(frame)

        # 任务完成判定
        if self._current_task_finish(frame):
            self._task_index += 1

        if frame.action_seq and self._task_index >= len(frame.action_seq):
            frame.task_finish = True

        # 超时 → 停车
        self._judge_stop(frame)

    def _update_key_index(self, frame: "PlanningFrame") -> None:
        """更新车辆在完整 task_trajectory 上的最近点索引 (C++ line 53)"""
        if not frame.ref_mgr:
            return
        loc = frame.localization
        if loc is None:
            return
        frame.key_index = frame.ref_mgr.find_closest_index(loc.x, loc.y)

    def _update_stop_from_authority(self, frame: "PlanningFrame") -> None:
        """路权处理 — 对应 C++ BussinessDecision::proc lines 34-51

        无条件计算 autor_index: 无 MA 时 endpoint=(0,0) → 最近点 ≈ 0，
        min-tracking 后 stop_index → 0，车辆停车。
        MA 到达后 endpoint 为正确坐标 → stop_index 更新为路权值。
        """
        if not frame.ref_mgr:
            return
        ref = frame.ref_mgr.current
        if not ref.points:
            return

        # endpoint lat/lon (C++ lines 35-36: 无条件读取，无 MA 时为 0,0)
        ma = frame.move_authority
        end_lat = ma.endpoint_lat if ma is not None else 0.0
        end_lon = ma.endpoint_lon if ma is not None else 0.0

        # 在当前参考线上找最近点 (C++ lines 44-45: getCurrentReferenceLine())
        autor_index = 0
        best_dist = float("inf")
        for i, p in enumerate(ref.points):
            dlat = p.lat - end_lat
            dlon = p.lon - end_lon
            d = dlat * dlat + dlon * dlon
            if d < best_dist:
                best_dist = d
                autor_index = i

        # min-tracking (C++ line 47: updateStopIndex)
        frame.ref_mgr.stop_index = min(frame.ref_mgr.stop_index, autor_index)

        # 无条件钳位到参考线末尾 (C++ lines 49-51)
        frame.ref_mgr.stop_index = min(frame.ref_mgr.stop_index, len(ref.points) - 1)

    def _current_task_finish(self, frame: "PlanningFrame") -> bool:
        """判断当前动作是否完成"""
        if not frame.action_seq or self._task_index >= len(frame.action_seq):
            return False

        action = frame.action_seq[self._task_index]

        if action.action_type == STOP_ACTION:
            # C++: 用完整的 task_trajectory 重新计算 task_index, 与 key_index 比较
            result = False
            pts = frame.ref_mgr.get_all_points()
            if pts and frame.localization:
                loc = frame.localization
                task_index = frame.ref_mgr.find_closest_index(loc.x, loc.y)
                # C++: key_index > task_index - 8 (task_index == key_index → 立即完成)
                if frame.key_index > task_index - 8:
                    frame.stop = True
                    result = True
                else:
                    frame.stop = False
                # C++ line 83: updateStopIndex(task_index)
                frame.ref_mgr.stop_index = min(frame.ref_mgr.stop_index, task_index)
            return result

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
