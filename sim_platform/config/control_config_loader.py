"""C++ 控制模块配置加载器 — 读取 control_config.ini，确保参数同源"""

import os
import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _find_control_config() -> Optional[Path]:
    """查找 control_config.ini 路径
    从 sim_platform/ 向上一级到 SIM/，再进入 control/config/
    """
    # sim_platform/config/ → sim_platform/ → SIM/
    current = Path(__file__).resolve().parent.parent  # sim_platform/
    project_root = current.parent                     # SIM/
    candidate = project_root / "control" / "config" / "control_config.ini"
    if candidate.exists():
        return candidate
    # 备选：从环境变量读取
    env_path = os.environ.get("SIM_CONTROL_CONFIG", "")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    return None


@dataclass
class ControlConfig:
    """从 control_config.ini 解析出的控制参数"""

    # === [vehicle] ===
    wheel_base: float = 5.6
    max_steer_angle: float = 35.0

    # === [hv_controller] ===
    lat_controller: str = "pure_pursuit_controller"
    lon_controller: str = "spd_pid_controller"

    # === [pure_pursuit] ===
    lookahead_distance: float = 5.0

    # === [stanley] ===
    stanley_k_e: float = 1.0

    # === [spd_pid] ===
    spd_preview_base: float = 1.2
    spd_preview_v_factor: float = 0.2

    # === PID 参数（硬编码于 C++ spd_pid_controller.h，与 C++ 保持一致） ===
    pid_kp: float = 0.8
    pid_ki: float = 0.12
    pid_kd: float = 0.15
    pid_speed_dead_zone: float = 0.5

    # === 源文件路径 ===
    source_path: str = ""

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "ControlConfig":
        """从 control_config.ini 加载配置，未找到则使用默认值"""
        config = cls()

        if path is None:
            path = _find_control_config()

        if path is None or not Path(path).exists():
            return config

        config.source_path = str(path)
        parser = configparser.ConfigParser()
        parser.read(str(path), encoding="utf-8")

        # [vehicle]
        if parser.has_section("vehicle"):
            config.wheel_base = parser.getfloat("vehicle", "wheel_base", fallback=config.wheel_base)
            config.max_steer_angle = parser.getfloat("vehicle", "max_steer_angle", fallback=config.max_steer_angle)

        # [hv_controller]
        if parser.has_section("hv_controller"):
            config.lat_controller = parser.get("hv_controller", "lat_controller", fallback=config.lat_controller)
            config.lon_controller = parser.get("hv_controller", "lon_controller", fallback=config.lon_controller)

        # [pure_pursuit]
        if parser.has_section("pure_pursuit"):
            config.lookahead_distance = parser.getfloat("pure_pursuit", "lookhead_distance", fallback=config.lookahead_distance)

        # [stanley]
        if parser.has_section("stanley"):
            config.stanley_k_e = parser.getfloat("stanley", "k_e", fallback=config.stanley_k_e)

        # [spd_pid]
        if parser.has_section("spd_pid"):
            config.spd_preview_base = parser.getfloat("spd_pid", "preview_base", fallback=config.spd_preview_base)
            config.spd_preview_v_factor = parser.getfloat("spd_pid", "preview_v_factor", fallback=config.spd_preview_v_factor)

        return config

    def controller_type_display(self) -> str:
        """返回人类可读的控制器类型描述"""
        lat_map = {
            "pure_pursuit_controller": "PurePursuit",
            "stanley_controller": "Stanley",
            "lqr_controller": "LQR",
            "kinematics_mpc_controller": "KinematicsMPC",
            "dynamics_mpc_controller": "DynamicsMPC",
        }
        lon_map = {
            "spd_pid_controller": "PID",
        }
        lat_name = lat_map.get(self.lat_controller, self.lat_controller)
        lon_name = lon_map.get(self.lon_controller, self.lon_controller)
        return f"{lat_name} + {lon_name}"
