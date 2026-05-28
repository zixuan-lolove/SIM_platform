#!/usr/bin/env python3
"""仿真测试平台 — 程序入口"""

import sys
import os

# 将项目根目录（sim_platform 的父目录）加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    """主函数"""
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
