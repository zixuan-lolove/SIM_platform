#!/usr/bin/env python3
"""T-A1-06 & T-A1-07 轨迹测试 CLI 脚本 (v0.3)

支持两种模式:
  1. 合成数据模式: 程序构造 7 组测试场景，验证阈值逻辑
     python3 tests/test_traj_validation.py

  2. 真实 .traj 文件模式: 加载指定 .traj 文件，输出验证结果
     python3 tests/test_traj_validation.py --traj path/to/file.traj
     python3 tests/test_traj_validation.py --traj path/to/file.traj --export report.json

输出: 每项测试的 PASS/FAIL 状态，可导出 JSON 报告。
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim_platform.models.sim_messages import TrajPoint
from sim_platform.a1.a1_types import AnomalySeverity, Verdict
from sim_platform.a1.a1_test_registry import A1ValidationRules


# ══════════════════════════════════════════════════════════════════
# 合成测试数据构造
# ══════════════════════════════════════════════════════════════════

def _make_traj(thetas_deg: list[float], step: float = 1.0) -> list[TrajPoint]:
    """用航向角度序列构造轨迹点 (theta 用弧度, heading 用度)"""
    pts = []
    for i, hdg_deg in enumerate(thetas_deg):
        pts.append(TrajPoint(
            x=i * step, y=0.0,
            heading=hdg_deg,
            theta=math.radians(hdg_deg),
            curvature=0.0, slope=0.0, s=i * step, v=5.0,
        ))
    return pts


def _make_dist_traj(start_x: float, start_y: float, n: int = 10) -> list[TrajPoint]:
    """构造起点在指定位置的轨迹"""
    pts = []
    for i in range(n):
        pts.append(TrajPoint(
            x=start_x + i * 1.0, y=start_y,
            heading=90.0, theta=math.radians(90.0),
            curvature=0.0, slope=0.0, s=i * 1.0, v=5.0,
        ))
    return pts


# ══════════════════════════════════════════════════════════════════
# T-A1-06: 航向跳变检测 (>10°)
# ══════════════════════════════════════════════════════════════════

def test_heading_normal():
    """S1: 100 点全 90° — 无误报"""
    pts = _make_traj([90.0] * 100)
    anomalies = A1ValidationRules.validate_heading_jump(pts)
    assert len(anomalies) == 0, f"期望 0, 实际 {len(anomalies)}"
    return {"test": "S1-正常轨迹无误报", "passed": True, "anomaly_count": 0}


def test_heading_15deg_jump():
    """S2: 前 25 点 90° → 后 25 点 105° — 检出 1 处 Δ=15°"""
    hdgs = [90.0] * 25 + [105.0] * 25
    pts = _make_traj(hdgs)
    anomalies = A1ValidationRules.validate_heading_jump(pts)
    assert len(anomalies) == 1, f"期望 1, 实际 {len(anomalies)}"
    a = anomalies[0]
    assert a.anomaly_type == "heading_jump"
    delta = a.details.get("delta_deg", 0.0)
    assert delta > 10.0, f"Δ={delta}° 应 > 10°"
    return {"test": "S2-15度跳变检出", "passed": True, "anomaly_count": 1,
            "delta_deg": delta}


def test_heading_8deg_no_trigger():
    """S3: 8° 跳变 — 不触发 (<10° 阈值)"""
    hdgs = [90.0] * 25 + [98.0] * 25
    pts = _make_traj(hdgs)
    anomalies = A1ValidationRules.validate_heading_jump(pts)
    assert len(anomalies) == 0, f"期望 0, 实际 {len(anomalies)}"
    return {"test": "S3-8度跳变不触发", "passed": True, "anomaly_count": 0}


def test_heading_multi_jump():
    """S4: 90°→105°→90°→80° — 检出 3 处跳变"""
    hdgs = [90.0] * 20 + [105.0] * 20 + [90.0] * 20 + [80.0] * 20
    pts = _make_traj(hdgs)
    anomalies = A1ValidationRules.validate_heading_jump(pts)
    # 跳变: 90→105 Δ=15, 105→90 Δ=15, 90→80 Δ=10 (边界触发)
    assert len(anomalies) == 3, f"期望 3, 实际 {len(anomalies)}"
    deltas = [a.details.get("delta_deg", 0.0) for a in anomalies]
    return {"test": "S4-多跳变轨迹", "passed": True, "anomaly_count": 3,
            "deltas_deg": [round(d, 1) for d in deltas]}


# ══════════════════════════════════════════════════════════════════
# T-A1-07: 起点距离检查 (≤3m)
# ══════════════════════════════════════════════════════════════════

def _run_dist(dist_m: float) -> dict:
    pts = _make_dist_traj(0.0, 0.0)
    first = pts[0]
    verdicts = A1ValidationRules.validate_start_point_distance(
        dist_m, 0.0, first.x, first.y, 0.0
    )
    v = verdicts[0]
    return {"verdict": v.verdict, "distance": v.details.get("distance", 0.0)}


def test_start_dist_1m():
    """D1: 1m — PASS"""
    r = _run_dist(1.0)
    assert r["verdict"] == Verdict.PASS, f"期望 PASS, 实际 {r['verdict'].name}"
    return {"test": "D1-起点1m PASS", "passed": True,
            "verdict": "PASS", "distance": r["distance"]}


def test_start_dist_3m_boundary():
    """D2: 3m 边界 — PASS (≤3m)"""
    r = _run_dist(3.0)
    assert r["verdict"] == Verdict.PASS, f"期望 PASS, 实际 {r['verdict'].name}"
    return {"test": "D2-起点3m边界 PASS", "passed": True,
            "verdict": "PASS", "distance": r["distance"]}


def test_start_dist_5m():
    """D3: 5m — WARN"""
    r = _run_dist(5.0)
    assert r["verdict"] == Verdict.WARN, f"期望 WARN, 实际 {r['verdict'].name}"
    return {"test": "D3-起点5m WARN", "passed": True,
            "verdict": "WARN", "distance": r["distance"]}


# ══════════════════════════════════════════════════════════════════
# 真实 .traj 文件验证
# ══════════════════════════════════════════════════════════════════

def validate_traj_file(traj_path: str, vehicle_x: float = 0.0,
                       vehicle_y: float = 0.0) -> dict:
    """加载真实 .traj 文件并运行 A1-06 + A1-07 验证"""
    from sim_platform.gateway_sim.traj_parser import TrajParser

    parser = TrajParser()
    traj = parser.parse_file(traj_path)
    pts = traj.points

    if not pts:
        return {"error": "轨迹文件无数据点"}

    # A1-06
    heading_anomalies = A1ValidationRules.validate_heading_jump(pts)
    a106 = {
        "total_points": len(pts),
        "anomaly_count": len(heading_anomalies),
        "max_delta_deg": max(
            (a.details.get("delta_deg", 0.0) for a in heading_anomalies),
            default=0.0
        ),
        "anomalies": [
            {
                "point_index": a.details.get("point_index"),
                "delta_deg": a.details.get("delta_deg"),
            }
            for a in heading_anomalies
        ],
    }

    # A1-07
    first = pts[0]
    dist = math.hypot(first.x - vehicle_x, first.y - vehicle_y)
    verdicts = A1ValidationRules.validate_start_point_distance(
        vehicle_x, vehicle_y, first.x, first.y, 0.0
    )
    a107 = {
        "distance_m": round(dist, 2),
        "verdict": verdicts[0].verdict.name if verdicts else "N/A",
        "ref_start": (round(first.x, 2), round(first.y, 2)),
        "vehicle": (round(vehicle_x, 2), round(vehicle_y, 2)),
    }

    return {
        "file": traj_path,
        "A1-06_heading_jump": a106,
        "A1-07_start_distance": a107,
    }


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

ALL_SYNTHETIC_TESTS = [
    test_heading_normal,
    test_heading_15deg_jump,
    test_heading_8deg_no_trigger,
    test_heading_multi_jump,
    test_start_dist_1m,
    test_start_dist_3m_boundary,
    test_start_dist_5m,
]


def main():
    ap = argparse.ArgumentParser(
        description="T-A1-06 & T-A1-07 轨迹测试 CLI (v0.3)"
    )
    ap.add_argument("--traj", type=str, default=None,
                    help="真实 .traj 文件路径 (可选)")
    ap.add_argument("--vehicle-x", type=float, default=0.0,
                    help="车辆 ENU X (m), 默认 0")
    ap.add_argument("--vehicle-y", type=float, default=0.0,
                    help="车辆 ENU Y (m), 默认 0")
    ap.add_argument("--export", type=str, default=None,
                    help="导出报告 JSON 路径")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="详细输出")
    args = ap.parse_args()

    results = []
    report_data = {}

    if args.traj:
        # 真实 .traj 文件模式
        print(f"加载: {args.traj}")
        try:
            r = validate_traj_file(args.traj, args.vehicle_x, args.vehicle_y)
            if "error" in r:
                print(f"  ✗ {r['error']}")
                sys.exit(1)

            a106 = r["A1-06_heading_jump"]
            a107 = r["A1-07_start_distance"]

            print(f"\n{'='*50}")
            print(f"A1-06 航向跳变检测 (>10°)")
            print(f"  轨迹点数:     {a106['total_points']}")
            print(f"  异常点数:     {a106['anomaly_count']}")
            print(f"  最大跳变:     {a106['max_delta_deg']:.1f}°")
            for a in a106["anomalies"]:
                print(f"    idx={a['point_index']}  Δ={a['delta_deg']}°")

            print(f"\nA1-07 起点距离 (≤3m)")
            print(f"  车辆位置:     {a107['vehicle']}")
            print(f"  参考线起点:   {a107['ref_start']}")
            print(f"  距离:         {a107['distance_m']}m")
            print(f"  判定:         {a107['verdict']}")
            print(f"{'='*50}")

            report_data = r
            results.append({"test": "traj_file", "passed": True})

        except Exception as e:
            print(f"  ✗ 验证失败: {e}")
            sys.exit(1)
    else:
        # 合成数据模式
        print("T-A1-06 & T-A1-07 合成数据测试 (v0.3)\n")

        heading_results = []
        start_dist_results = []

        print("── T-A1-06 航向跳变检测 (>10°) ──")
        for fn in ALL_SYNTHETIC_TESTS[:4]:
            try:
                r = fn()
                results.append(r)
                extra = ""
                if args.verbose:
                    if "delta_deg" in r:
                        extra = f"  Δ={r['delta_deg']}°"
                    elif "deltas_deg" in r:
                        extra = f"  Δs={r['deltas_deg']}"
                print(f"  ✓ PASS  {r['test']}{extra}")
            except AssertionError as e:
                results.append({"test": fn.__name__, "passed": False, "error": str(e)})
                print(f"  ✗ FAIL  {fn.__name__}: {e}")

        print("\n── T-A1-07 起点距离 (≤3m) ──")
        for fn in ALL_SYNTHETIC_TESTS[4:]:
            try:
                r = fn()
                results.append(r)
                extra = ""
                if args.verbose:
                    extra = f"  dist={r['distance']:.1f}m"
                print(f"  ✓ PASS  {r['test']}{extra}")
            except AssertionError as e:
                results.append({"test": fn.__name__, "passed": False, "error": str(e)})
                print(f"  ✗ FAIL  {fn.__name__}: {e}")

        # 汇总
        passed = sum(1 for r in results if r.get("passed"))
        total = len(results)
        print(f"\n{'='*50}")
        print(f"  结果: {passed}/{total} 通过")
        if passed == total:
            print(f"  状态: ✅ 全部通过")
        else:
            print(f"  状态: ❌ {total - passed} 项失败")

        report_data = {"synthetic_results": results}

    # 导出
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"test_suite": "T-A1-06 & T-A1-07", "version": "v0.3"},
                **report_data,
            }, f, ensure_ascii=False, indent=2)
        print(f"  报告已导出: {args.export}")

    passed = sum(1 for r in results if r.get("passed"))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
