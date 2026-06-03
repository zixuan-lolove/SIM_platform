"""业务决策 — Python 等价实现 C++ BussinessDecision (F-09-06)

负责: 任务切换检测、参考线更新、路权处理、任务完成判定、超时检测、停车判断。
"""

import logging
import math
from typing import TYPE_CHECKING, Callable, Optional

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
        # A1 参考线验证回调 (由 A1ValidationEngine 注入)
        self._ref_line_validator: Optional[Callable[[list], None]] = None

    def reset(self) -> None:
        self._task_index = 0
        self._last_action = UNKNOWN_ACTION
        self._dump_process = 0
        self._dump_cycle_counter = 0

    def set_ref_line_validator(self, validator: Optional[Callable[[list], None]]) -> None:
        """设置参考线验证回调 (A1-06/07/08/09)

        由 A1ValidationEngine 注入。回调签名为:
            validator(points: list[TrajPoint]) -> None
        在参考线加载/更新时调用。
        """
        self._ref_line_validator = validator

    def validate_current_ref_line(self, points: list) -> None:
        """触发参考线验证 (供 PlanningSim 在任务加载时调用)

        Args:
            points: TrajPoint 对象列表
        """
        if self._ref_line_validator and points:
            self._ref_line_validator(points)

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

        # 段切换: 车到段尾且 STOP 目标在下一段时切段
        self._check_segment_advance(frame)

        # 当前 action 类型 (在完成判定之前设置，确保完成时上报的是已完成 action 的类型)
        current_action_type = 0
        if frame.action_seq and self._task_index < len(frame.action_seq):
            current_action_type = frame.action_seq[self._task_index].action_type

        # 任务完成判定
        action_completed = self._current_task_finish(frame)
        if action_completed:
            # action 完成: 上报已完成 action 的类型 + status=2 (complete)
            frame.action_type = current_action_type
            frame.action_status = 2
            self._task_index += 1
        else:
            # action 执行中: status=1 (executing)
            frame.action_type = current_action_type
            frame.action_status = 1

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

    def _check_segment_advance(self, frame: "PlanningFrame") -> None:
        """段切换: 车到当前段末尾(key_index ≥ end_index-3)且 STOP 目标在下一段时切段"""
        if not frame.ref_mgr:
            return
        if frame.ref_mgr.current_index + 1 >= len(frame.ref_mgr._ref_lines):
            return
        if not (frame.action_seq and self._task_index < len(frame.action_seq)):
            return
        action = frame.action_seq[self._task_index]
        if action.action_type != STOP_ACTION:
            return
        current = frame.ref_mgr.current
        next_seg = frame.ref_mgr._ref_lines[frame.ref_mgr.current_index + 1]
        # 车到段尾
        if frame.key_index < current.end_index - 3:
            return
        # STOP 目标在下一段
        task_idx = frame.ref_mgr.find_closest_by_latlon(action.lat, action.lon)
        if task_idx >= next_seg.start_index:
            frame.ref_mgr.advance_to_next()
            logger.info(f"[BizDecision] Segment advance: key_idx={frame.key_index}, task_idx={task_idx}")

    def _update_stop_from_authority(self, frame: "PlanningFrame") -> None:
        """路权处理 — 对应 C++ BussinessDecision::proc lines 34-51

        无条件计算 autor_index；空 endpoint (0,0) 时跳过更新 (云端"停止下发"指令)，
        避免 min-tracking 将 stop_index 锁死在 0 导致有效 MA 无法恢复。
        有效 MA 到达后 endpoint 为正确坐标 → stop_index 更新为路权值。
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

        # 忽略空 endpoint 的 MA: 云端下发"停止下发"/"车辆无任务"时 endpoint 为 (0,0)
        # 若不拦截，min-tracking 会将 stop_index 锁死在 0，后续有效 MA 无法恢复
        if abs(end_lat) < 1e-8 and abs(end_lon) < 1e-8:
            cnt = getattr(self, '_stop_log_cnt', 0)
            if cnt <= 3 or cnt % 500 == 0:
                logger.warning(
                    f"[BizDecision] Ignoring MA with empty endpoint "
                    f"(lat={end_lat}, lon={end_lon}) — stop_index unchanged"
                )
            return

        # 优先用云端下发的 pointIndex，GPS 全段匹配做 fallback
        if ma is not None and ma.stop_index > 0:
            autor_index = ma.stop_index
        else:
            all_pts = frame.ref_mgr.get_all_points()
            autor_index = 0
            best_dist = float("inf")
            for i, p in enumerate(all_pts):
                dlat = p.lat - end_lat
                dlon = p.lon - end_lon
                d = dlat * dlat + dlon * dlon
                if d < best_dist:
                    best_dist = d
                    autor_index = i

        # MA 端点扩大时重置 sentinel，避免历史小值锁死 stop_index
        # (MA 端点缩小时仍用 min-tracking 保安全)
        old_stop = frame.ref_mgr.stop_index if frame.ref_mgr.stop_index < 10**8 else -1
        if autor_index > old_stop and old_stop >= 0:
            frame.ref_mgr.stop_index = 10 ** 9  # 重置，允许扩大
        frame.ref_mgr.stop_index = min(frame.ref_mgr.stop_index, autor_index)

        # 无条件钳位到参考线末尾 (全段点总数)
        frame.ref_mgr.stop_index = min(frame.ref_mgr.stop_index,
                                       frame.ref_mgr._total_points - 1)

        # 诊断日志 (前 3 次 + 每 500 周期)
        if not hasattr(self, '_stop_log_cnt'):
            self._stop_log_cnt = 0
        self._stop_log_cnt += 1
        if self._stop_log_cnt <= 3 or self._stop_log_cnt % 500 == 0:
            src = "cloud" if (ma and ma.stop_index > 0) else "gps"
            logger.info(f"[BizDecision] stop_index: {old_stop} → autor={autor_index} "
                        f"→ final={frame.ref_mgr.stop_index} "
                        f"(ep=({end_lat:.6f},{end_lon:.6f}), total_pts={frame.ref_mgr._total_points}, "
                        f"ma={'set' if ma else 'None'}, src={src})")

    def _current_task_finish(self, frame: "PlanningFrame") -> bool:
        """判断当前动作是否完成"""
        if not frame.action_seq or self._task_index >= len(frame.action_seq):
            return False

        action = frame.action_seq[self._task_index]

        if action.action_type == STOP_ACTION:
            # STOP 完成: 位置(1m) + 航向(2°) + 参考线索引 三重校验
            result = False
            if frame.ref_mgr and frame.localization:
                # 1. task_index: GPS+航向匹配，避免前进/倒车段混淆
                target_theta = math.radians((90.0 - action.heading) % 360.0)
                if target_theta > math.pi:
                    target_theta -= 2.0 * math.pi

                pts = frame.ref_mgr.get_all_points()
                best_idx = 0
                best_score = float("inf")
                for i, p in enumerate(pts):
                    d_gps = (p.lat - action.lat) ** 2 + (p.lon - action.lon) ** 2
                    d_hdg = abs(math.atan2(math.sin(p.theta - target_theta),
                                           math.cos(p.theta - target_theta)))
                    if d_hdg > math.radians(5.0):
                        d_hdg += 1000.0  # 排除航向不匹配的段
                    score = d_gps + d_hdg * 1e-5
                    if score < best_score:
                        best_score = score
                        best_idx = i
                task_index = best_idx

                # 2. 位置: 车在目标点 1m 内
                position_ok = (frame.key_index > task_index - 2)

                # 3. 航向: 车头朝向与目标差 < 2°
                heading_err = abs(math.atan2(
                    math.sin(frame.localization.theta - target_theta),
                    math.cos(frame.localization.theta - target_theta)))
                heading_ok = (heading_err < math.radians(2.0))

                if position_ok and heading_ok:
                    frame.stop = True
                    result = True
                else:
                    frame.stop = False

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
