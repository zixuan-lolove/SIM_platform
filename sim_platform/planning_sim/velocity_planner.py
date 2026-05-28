"""速度规划器 — Python 等价实现 C++ VelocityPlanner (F-09-04)

三阶段流程:
1. setEndPointZero — 终点速度置零
2. backwardDecelPlanning — 反向减速规划 (确保安全停车)
3. forwardSpeedConstraint — 正向速度约束 (弯道提前减速)
"""

import math
from ..models.sim_messages import PlanningTrajectoryPoint


class VelocityPlanner:
    """速度剖面规划器"""

    @staticmethod
    def plan_velocity(
        cur_index: int,
        target_index: int,
        trajectory: list[PlanningTrajectoryPoint],
        ref_decel: float = 1.0,
    ) -> None:
        """速度规划主入口 (修改 trajectory 的 velocity 字段)

        Args:
            cur_index: 车辆当前在轨迹上的索引
            target_index: 停车目标索引
            trajectory: 规划轨迹点列表 (in-place 修改)
            ref_decel: 参考减速度 (m/s², 正数)
        """
        if not trajectory or target_index >= len(trajectory):
            return

        decel = abs(ref_decel)

        # 步骤 1: 目标点及之后所有点速度置零
        for i in range(target_index, len(trajectory)):
            trajectory[i].velocity = 0.0

        # 终点速度强制为零
        trajectory[-1].velocity = 0.0

        # 步骤 2: 反向减速规划
        VelocityPlanner._backward_decel(trajectory, target_index, decel)

        # 步骤 3: 正向速度约束
        VelocityPlanner._forward_constraint(trajectory, cur_index)

    @staticmethod
    def _calc_stop_distance(start_v: float, decel: float) -> float:
        """匀减速停车距离: v² / (2a)"""
        if start_v <= 0.0:
            return 0.0
        return (start_v ** 2) / (2.0 * decel)

    @staticmethod
    def _backward_decel(
        traj: list[PlanningTrajectoryPoint],
        target_idx: int,
        decel: float,
    ) -> None:
        """反向减速规划

        从停车点前一个点开始，向前逐点计算:
        v_i = min(v_i, sqrt(v_{i+1}² - 2 * a * ds))
        """
        if target_idx == 0:
            return

        for i in range(target_idx - 1, -1, -1):
            cur = traj[i]
            nxt = traj[i + 1]
            ds = nxt.s - cur.s
            if ds < 0:
                ds = 0.0

            next_v = nxt.velocity
            # 反向能量守恒: v_i² = v_{i+1}² + 2*a*ds (减速时用 + 号)
            cur_v_ref = math.sqrt(max(0.0, next_v ** 2 + 2.0 * decel * ds))
            cur.velocity = min(cur.velocity, cur_v_ref)

        # 确保 target 之后全为零
        for i in range(target_idx, len(traj)):
            traj[i].velocity = 0.0

    @staticmethod
    def _forward_constraint(
        traj: list[PlanningTrajectoryPoint],
        cur_idx: int,
    ) -> None:
        """正向速度约束

        如果下一点速度更低 (弯道/限速)，提前将当前点速度降为下一点速度。
        """
        for i in range(cur_idx, len(traj) - 1):
            if traj[i + 1].velocity < traj[i].velocity:
                traj[i].velocity = traj[i + 1].velocity
