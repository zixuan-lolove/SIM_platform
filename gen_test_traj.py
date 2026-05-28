#!/usr/bin/env python3
"""生成仿真测试用 .traj 轨迹文件"""
import math

# ====================== 参数 ======================
N_POINTS = 200
START_LAT, START_LON = 30.000000, 120.000000   # 装载区
END_LAT,   END_LON   = 30.004000, 120.007000   # 卸载区 (~1km)

def generate_waypoints():
    """生成装载 → 卸载的路径控制点"""
    pts = []
    # 1. 装载区直线 (0 - 150m)
    for d in range(0, 150, 5):
        pts.append((d * 1.0, 0.0, 8.0))  # x, y, v
    # 2. 右转弯 (150 - 250m, R ~ 80m)
    for ang in range(0, 45, 1):
        rad = math.radians(ang)
        x = 150 + 80 * math.sin(rad)
        y = 80 * (1 - math.cos(rad))
        pts.append((x, y, 6.0))
    # 3. 直线连接 (250 - 400m)
    x0, y0 = pts[-1][0], pts[-1][1]
    angle = math.radians(45)
    for d in range(0, 150, 5):
        pts.append((x0 + d * math.cos(angle), y0 + d * math.sin(angle), 8.0))
    # 4. 左转弯 (400 - 550m, R ~ 100m)
    x1, y1 = pts[-1][0], pts[-1][1]
    for ang in range(0, 60, 1):
        rad = math.radians(ang)
        x = x1 + 100 * math.sin(rad)
        y = y1 - 100 * (1 - math.cos(rad))
        pts.append((x, y, 5.0))
    # 5. 卸载区直线 (550 - 700m)
    x2, y2 = pts[-1][0], pts[-1][1]
    angle2 = math.radians(45 - 60)  # ≈ -15°
    for d in range(0, 150, 10):
        pts.append((x2 + d * math.cos(angle2), y2 + d * math.sin(angle2), 3.0))
    return pts


def resample(waypoints, n):
    """均匀间隔重采样"""
    # 计算总长度
    dists = [0.0]
    for i in range(1, len(waypoints)):
        dx = waypoints[i][0] - waypoints[i-1][0]
        dy = waypoints[i][1] - waypoints[i-1][1]
        dists.append(dists[-1] + math.hypot(dx, dy))
    total = dists[-1]

    result = []
    seg = 0
    for j in range(n):
        target_s = total * j / (n - 1)
        while seg < len(waypoints) - 2 and dists[seg + 1] < target_s:
            seg += 1
        seg_len = dists[seg + 1] - dists[seg]
        t = ((target_s - dists[seg]) / seg_len) if seg_len > 1e-9 else 0
        t = max(0, min(1, t))
        x = waypoints[seg][0] + t * (waypoints[seg + 1][0] - waypoints[seg][0])
        y = waypoints[seg][1] + t * (waypoints[seg + 1][1] - waypoints[seg][1])
        v = waypoints[seg][2] + t * (waypoints[seg + 1][2] - waypoints[seg][2])
        result.append((x, y, v))
    return result, total


def enu_to_latlon(x, y, ref_lat, ref_lon):
    """ENU → WGS84 近似"""
    R = 6371000.0
    ref_lat_rad = math.radians(ref_lat)
    dlat = y / R
    dlon = x / (R * math.cos(ref_lat_rad))
    return ref_lat + math.degrees(dlat), ref_lon + math.degrees(dlon)


def main():
    waypoints = generate_waypoints()
    resampled, total_length = resample(waypoints, N_POINTS)

    # 起始点作为局部 ENU 参考
    ref_x, ref_y = resampled[0][0], resampled[0][1]
    ref_lat, ref_lon = START_LAT, START_LON

    lines = []
    for i, (x, y, v) in enumerate(resampled):
        lat, lon = enu_to_latlon(x - ref_x, y - ref_y, ref_lat, ref_lon)

        # heading: 从当前点到下一点的方位角
        if i < len(resampled) - 1:
            dx = resampled[i+1][0] - x
            dy = resampled[i+1][1] - y
        else:
            dx = x - resampled[i-1][0]
            dy = y - resampled[i-1][1]
        heading = math.degrees(math.atan2(dx, dy)) % 360   # 0=N, clockwise

        # attribute_1 位标志 (与 traj_parser._get_bit 1-indexed 一致)
        # bit1=is_re_park, bit2=is_lift_forward, bit3=is_park,
        # bit4=has_right_wall, bit5=has_left_wall, bit6=is_reverse, bit7=is_preview
        attr1 = 0
        progress = i / (N_POINTS - 1)
        if progress < 0.05:
            attr1 |= (1 << 2)  # is_park (bit 3 1-indexed)
        elif progress < 0.1:
            attr1 |= (1 << 1)  # is_lift_forward (bit 2 1-indexed, 装载)
        if progress > 0.9:
            attr1 |= (1 << 0)  # is_re_park (bit 1 1-indexed, 卸载区)
        if 0.3 < progress < 0.7:
            attr1 |= (1 << 3)  # has_right_wall (bit 4 1-indexed)
            attr1 |= (1 << 4)  # has_left_wall (bit 5 1-indexed)

        # curvature: 从前后点估算
        curv = 0.0
        if 0 < i < len(resampled) - 1:
            px, py = resampled[i-1][0], resampled[i-1][1]
            nx, ny = resampled[i+1][0], resampled[i+1][1]
            a = math.hypot(x - px, y - py)
            b = math.hypot(nx - x, ny - y)
            c = math.hypot(nx - px, ny - py)
            if a * b * c > 1e-9:
                curv = 2 * ((nx - px) * (y - py) - (ny - py) * (x - px)) / (a * b * c)

        # altitude (模拟: 卸载区比装载区高 30m)
        alt = progress * 30.0

        # slope
        slope = math.atan2(30.0, total_length) if progress < 0.95 else 0.0

        line = (
            f"$, {i % 9999}, {heading:.3f}, {lat:.8f}, {lon:.8f}, "
            f"{y:.3f}, {x:.3f}, {alt:.1f}, {v:.1f}, "
            f"15.0, 15.0, {float(attr1)}, {slope:.6f}, {curv:.6f}, "
            f"0, 100.0, 100.0, $"
        )
        lines.append(line)

    # 写入文件
    path = "/home/zy/SIM/sim_test_mission.traj"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已生成: {path}")
    print(f"点数: {N_POINTS}, 总长: {total_length:.0f}m, "
          f"起点: ({START_LAT},{START_LON}), 终点: ({END_LAT},{END_LON})")


if __name__ == "__main__":
    main()
