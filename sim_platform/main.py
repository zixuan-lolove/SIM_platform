#!/usr/bin/env python3
"""仿真测试平台 — 程序入口"""

import logging
import logging.handlers
import sys
import os
# protobuf C 扩展与 numpy 不兼容会导致字段返回 0，必须在任何 protobuf import 之前设置
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
from datetime import datetime

# 将项目根目录（sim_platform 的父目录）加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 日志目录
LOG_DIR = os.path.join(PROJECT_ROOT, "sim_platform", "logs")

# 保存当前文件 handler 以便会话切换
_file_handler: logging.FileHandler | None = None


def _setup_logging():
    """配置日志：控制台 INFO 级别 + 文件 DEBUG 级别"""
    global _file_handler
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 控制台 handler (INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    # 文件 handler (DEBUG, 每次启动新文件)
    _file_handler = _create_file_handler(fmt)
    root.addHandler(_file_handler)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized: {_file_handler.baseFilename}")


def _create_file_handler(fmt: logging.Formatter) -> logging.FileHandler:
    """创建带时间戳的日志文件 handler"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"sim_{timestamp}.log")
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(fmt)
    return handler


def new_log_session():
    """开始新的日志会话（仿真启动/停止时调用）

    关闭当前文件 handler，创建新的时间戳命名日志文件。
    """
    global _file_handler
    root = logging.getLogger()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 移除旧文件 handler
    if _file_handler is not None:
        root.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:
            pass

    # 创建新文件 handler
    _file_handler = _create_file_handler(fmt)
    root.addHandler(_file_handler)

    logger = logging.getLogger(__name__)
    logger.info(f"=== New log session: {_file_handler.baseFilename} ===")


def main():
    """主函数"""
    _setup_logging()

    from sim_platform.ui.main_window import MainWindow
    from sim_platform.models.vehicle_params import VehicleParams
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt as QtCore

    # 禁用高 DPI 缩放（Linux 下可能导致崩溃）
    if hasattr(QtCore, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(QtCore.AA_EnableHighDpiScaling, False)
    if hasattr(QtCore, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(QtCore.AA_UseHighDpiPixmaps, False)

    app = QApplication(sys.argv)
    app.setApplicationName("MiningTruckSim")

    # 加载默认参数
    default_yaml = os.path.join(
        PROJECT_ROOT, "sim_platform", "config", "default_params.yaml"
    )
    params = None
    if os.path.exists(default_yaml):
        try:
            params = VehicleParams.from_yaml(default_yaml)
        except Exception:
            pass

    window = MainWindow(params)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
