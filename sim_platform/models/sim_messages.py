"""仿真平台进程内消息数据模型 — 对应 DDS Topic 消息体

所有模块通过 SimMessageBus 交换这些 dataclass 实例，
替代真实系统中的 Protobuf + DDS 序列化/反序列化链路。
"""

from dataclasses import dataclass, field
from typing import Optional


# ==================== 上行 Topic: Localization (Kinematics → Planning, Control, Gateway) ====================

@dataclass
class Localization:
    """车辆定位数据 — 对应 common::Localization / INS 融合定位输出"""
    x: float = 0.0              # ENU X 坐标 (m)
    y: float = 0.0              # ENU Y 坐标 (m)
    z: float = 0.0              # 海拔高程 (m)
    theta: float = 0.0          # 航向角 (rad)，正东为 0，逆时针为正
    v: float = 0.0              # 纵向速度 (m/s)
    yaw_rate: float = 0.0       # 横摆角速度 (rad/s)
    gear: int = 2               # 档位
    timestamp: float = 0.0      # 仿真时间戳 (s)
    lat: float = 0.0            # WGS84 纬度 (deg)，供 GatewaySim 上报用
    lon: float = 0.0            # WGS84 经度 (deg)
    gnss_status: int = 0        # 定位状态: 0=无效,1=单点,2=差分,3=RTK
    satellite_count: int = 0    # 可见卫星数
    hdop: float = 0.0           # 水平精度因子


# ==================== 上行 Topic: Chassis (Kinematics → Planning, Control, Gateway) ====================

@dataclass
class Chassis:
    """底盘反馈数据 — 对应 canbus::Chassis"""
    gear: int = 2               # 档位: 0=P, 1=R, 2=N, 3=D
    brake_pressure: float = 0.0 # 制动压力 (MPa)
    steer_angle: float = 0.0    # 前轮转角 (rad)
    speed_kmh: float = 0.0      # 车速 (km/h)
    throttle_percent: float = 0.0   # 油门百分比 0-100
    brake_percent: float = 0.0      # 制动百分比 0-100
    engine_rpm: float = 0.0     # 发动机/电机转速 (RPM)
    lift_status: int = 0        # 举升状态: 0=底部, 1=运动中, 2=顶部
    mileage: float = 0.0        # 累计里程 (km)
    battery_voltage: float = 0.0    # 电池电压 (V)
    coolant_temp: float = 0.0       # 冷却液温度 (°C)
    oil_pressure: float = 0.0       # 机油压力 (kPa)
    timestamp: float = 0.0


# ==================== 轨迹数据 ====================

@dataclass
class TrajPoint:
    """单个轨迹路径点 — 对应 gateway::TaskTrajInfo"""
    lat: float = 0.0            # WGS84 纬度
    lon: float = 0.0            # WGS84 经度
    heading: float = 0.0        # 航向角 (deg)
    altitude: float = 0.0       # 海拔 (m)
    x: float = 0.0              # ENU X (m)
    y: float = 0.0              # ENU Y (m)
    s: float = 0.0              # 累计里程 (m)
    v: float = 0.0              # 参考速度 (m/s)
    theta: float = 0.0          # 参考航向 (rad)
    planned_v: float = 0.0      # 规划速度 (m/s)
    # attribute_1 7-bit 标志
    is_re_park: bool = False
    is_lift_forward: bool = False
    is_park: bool = False
    has_right_wall: bool = False
    has_left_wall: bool = False
    is_reverse: bool = False
    is_preview: bool = False
    # 附加字段
    slope: float = 0.0
    curvature: float = 0.0
    road_id: int = 0
    left_dis: float = 0.0
    right_dis: float = 0.0
    overtake_left_dis: float = 0.0
    overtake_right_dis: float = 0.0


@dataclass
class TaskTraj:
    """任务轨迹集合 — 对应 Planning 收到的完整参考轨迹"""
    points: list[TrajPoint] = field(default_factory=list)
    task_id: str = ""


# ==================== 下行 Topic: TaskToPlanning (Gateway → Planning) ====================

@dataclass
class Action:
    """任务动作定义 — 对应 DispatchTask.Action"""
    action_type: int = 0        # 1=STOP, 2=LOAD, 3=DUMP, 4=LIFT
    lon: float = 0.0            # 目标经度
    lat: float = 0.0            # 目标纬度
    heading: float = 0.0        # 目标航向 (deg)


@dataclass
class TaskToPlanning:
    """任务下发消息 — 对应 DDS TaskToPlanning"""
    task_traj: TaskTraj = field(default_factory=TaskTraj)
    action_seq: list[Action] = field(default_factory=list)
    task_sn: str = ""           # 任务流水号
    task_type: int = 0          # 任务类型 (1=LOAD, 2=UNLOAD, 3=PARKING, ...)
    command_type: int = 0       # 指令类型
    timestamp: float = 0.0


# ==================== 下行 Topic: MoveAuthority (Gateway → Planning) ====================

@dataclass
class MoveAuthority:
    """路权信息 — 对应 MovemntAuthoritySend (cloudmsg.proto:249-290)

    C++ 中 BussinessDecision 使用 safeOccupied.endPoint 在参考线上查找 stop_index。
    """
    # safeOccupied.endPoint — 行车许可末端点 (路权终点)
    endpoint_lat: float = 0.0       # 终点纬度
    endpoint_lon: float = 0.0       # 终点经度
    end_point_index: int = 0        # 终点在车道上的序号
    end_point_line_sn: int = 0      # 终点所在车道序号

    # safeOccupied.startPoint — 行车许可开始点 (车辆当前位置)
    start_point_lat: float = 0.0
    start_point_lon: float = 0.0
    start_point_index: int = 0
    start_point_line_sn: int = 0

    # 参考线上计算的索引
    right_of_way_index: int = 0     # 路权终点在参考线上的索引 (由 GatewaySim 计算)
    stop_index: int = 0             # 停车点索引 (由 BusinessDecision.updateStopIndex 更新)

    # MovemntAuthor list
    segment_count: int = 0          # 路权分段数量 (list 长度)
    last_lane_id: int = 0           # 最后一段车道编号
    last_point_index: int = 0       # 最后一段在路径文件中的位置点序号
    last_direction: float = 0.0     # 最后一段航向角 (deg)

    # safeOccupied.lineSnQ
    line_snq: str = ""              # 车道线序号序列 (逗号分隔)

    timestamp: float = 0.0


# ==================== 内层 Topic: PlanningResult (Planning → Control) ====================

@dataclass
class PlanningTrajectoryPoint:
    """规划轨迹点 — 对应 PlanningResult 中的单个轨迹点"""
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0        # 航向角 (rad)
    velocity: float = 0.0       # 目标速度 (m/s)
    curvature: float = 0.0      # 曲率 (1/m)
    s: float = 0.0              # 累计里程 (m)
    lat: float = 0.0
    lon: float = 0.0
    altitude: float = 0.0
    planned_v: float = 0.0      # 规划速度 (m/s)


@dataclass
class PlanningResult:
    """规划结果消息 — 对应 DDS PlanningResult"""
    points: list[PlanningTrajectoryPoint] = field(default_factory=list)
    lift_cmd: int = 0           # 举升指令: 0=落, 1=升
    task_finish: bool = False   # 任务完成标志
    stop: bool = False          # 停车标志
    planner_type: str = "rtk"   # 使用的规划器类型
    planning_time_ms: float = 0.0  # 规划耗时 (ms)
    action_type: int = 0        # 当前 action 类型 (1=STOP,2=LOAD,3=DUMP,4=LIFT)
    action_status: int = 0      # 0=idle, 1=executing, 2=complete
    timestamp: float = 0.0


# ==================== 内层 Topic: ControlCmd (Control → Kinematics) ====================

@dataclass
class ControlCmd:
    """控制指令消息 — 对应 control::ControlCmd"""
    steer_angle: float = 0.0       # 前轮转角 (deg)，左正右负
    target_velocity: float = 0.0   # 目标车速 (km/h)
    throttle: float = 0.0          # 油门百分比 0-100
    brake: float = 0.0             # 制动百分比 0-100
    gear: int = 3                  # 目标档位 (D 档)
    cross_track_error: float = 0.0 # 横向偏差 (m)
    heading_error: float = 0.0     # 航向偏差 (deg)
    speed_error: float = 0.0       # 速度偏差 (km/h)
    timestamp: float = 0.0


# ==================== 横向 Topic: Obstacles (Perception → Planning) ====================

@dataclass
class Obstacle:
    """障碍物数据 — 对应 perception::Obstacle"""
    id: int = 0
    corners: list[tuple[float, float]] = field(default_factory=list)  # 4 个角点 ENU 坐标
    center_x: float = 0.0
    center_y: float = 0.0
    length: float = 3.0
    width: float = 2.0
    heading: float = 0.0        # 朝向角 (rad)
    speed: float = 0.0          # 速度 (m/s)，0=静态
    obstacle_type: int = 0      # 0=静态, 1=动态
    timestamp: float = 0.0


# ==================== 云端通信 Topic: CloudDispatchTask (Cloud → Gateway) ====================

@dataclass
class DispatchTask:
    """云端派发的运输任务 — 对应 CloudMsg.dispatchTask"""
    task_sn: str = ""           # 任务流水号
    task_type: int = 0          # 任务类型 (1=LOAD, 2=UNLOAD, ..., 10=PULLOVER_PARKING)
    task_file_path: str = ""    # 任务轨迹文件 URL/本地路径
    file_md5: str = ""          # 文件 MD5 校验
    action_seq: list[Action] = field(default_factory=list)
    command_type: int = 0       # 指令类型
    target_name: str = ""       # 目标区域名称
    target_element_id: str = "" # 目标元素 ID
    target_type: int = 0        # 目标类型
    dispatch_result: int = 0    # 派发结果: 0=成功


@dataclass
class AuthenticationApply:
    """鉴权应答 — 对应 CloudMsg.authenticationApply"""
    flow_id: str = ""
    reply_id: str = ""
    result_code: int = 0        # 0=成功
    device_name: str = ""
    mode: int = 1
    project_id: str = ""


@dataclass
class ServerParamsQueryResponse:
    """服务器参数查询应答"""
    flow_id: str = ""
    map_file_name: str = ""     # 0xF000 地图文件名
    map_md5: str = ""           # 0xF001 地图 MD5
    download_url: str = ""      # 0xF002 文件下载 URL


@dataclass
class CloudDispatchTask:
    """云端下行消息信封 — 对应 CloudMsg oneof"""
    msg_type: str = ""          # "dispatch_task" | "move_authority" | "authentication_apply" | "server_params_response"
    dispatch_task: Optional[DispatchTask] = None
    move_authority: Optional[MoveAuthority] = None
    authentication_apply: Optional[AuthenticationApply] = None
    server_params_response: Optional[ServerParamsQueryResponse] = None
    timestamp: float = 0.0


# ==================== 云端通信 Topic: CloudDeviceMsg (Gateway → Cloud) ====================

@dataclass
class CloudDeviceMsg:
    """设备上行消息信封 — 对应 DeviceMsg oneof"""
    msg_type: str = ""          # "authentication" | "position_report" | "monitor_report" | "state_report" | "stop_obstacle"
    imei: str = ""              # 设备 IMEI
    payload: dict = field(default_factory=dict)  # 消息体字段 key-value
    timestamp: float = 0.0
