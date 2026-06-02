"""高精地图匹配器 — 根据 GPS 坐标匹配当前所在车道 ID

地图数据库 (SQLite) 由云端下发，存储在 map_file_folder 目录下。
格式为 .db 文件或 .db.tar.gz 压缩包。

数据库关键表:
  - HDMAP_LANE:   车道定义 (laneid, trajectory WKT 格式)
  - HDMAP_LANENODE: 车道节点 (lon, lat) — 仅用于备用匹配

匹配策略:
  1. 优先使用 HDMAP_LANE.trajectory 中的点序列 (lon, lat 在每个点最前面)
  2. 遍历所有轨迹点，找最近的 → 返回该 lane 的 laneid
  3. 若 trajectory 不可用，回退到 HDMAP_LANENODE 节点匹配
"""

import logging
import os
import sqlite3
import tarfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HdMapMatcher:
    """高精地图车道匹配器

    根据车辆 GPS 坐标 (lat, lon) 查找当前所在的车道 ID (laneid)。
    使用惰性加载: 首次查询时自动扫描并加载地图数据库。
    """

    def __init__(self, map_folder: str = ""):
        """
        Args:
            map_folder: 地图文件存放目录 (来自 cloud_config.ini [download] map_file_folder)
        """
        self._map_folder = map_folder
        self._db_path: str = ""
        self._loaded: bool = False
        # 轨迹点列表: [(lat, lon, lane_id), ...]
        self._points: list[tuple[float, float, int]] = []

    # ========== 公共接口 ==========

    def find_lane_id(self, lat: float, lon: float) -> int:
        """根据 GPS 坐标查找所在车道 ID

        Args:
            lat: 纬度
            lon: 经度

        Returns:
            laneid (int), 未加载地图或无匹配时返回 0
        """
        if not self._loaded:
            self._try_load()
        if not self._points:
            return 0
        return self._find_nearest_lane(lat, lon)

    # ========== 内部实现 ==========

    def _try_load(self) -> None:
        """惰性加载: 扫描 map_folder → 找到 .db → 加载轨迹点"""
        self._loaded = True  # 只尝试一次，避免反复扫描

        if not self._map_folder or not os.path.isdir(self._map_folder):
            logger.debug(f"[HdMapMatcher] map_folder not found or empty: {self._map_folder}")
            return

        self._db_path = self._find_db_file()
        if not self._db_path:
            logger.warning(f"[HdMapMatcher] No .db file found in {self._map_folder}")
            return

        try:
            self._load_trajectory_points()
            logger.info(
                f"[HdMapMatcher] Loaded {len(self._points)} trajectory points "
                f"from {len(set(p[2] for p in self._points))} lanes"
            )
        except Exception as e:
            logger.error(f"[HdMapMatcher] Failed to load map DB: {e}")
            self._points.clear()

    def _find_db_file(self) -> str:
        """在 map_folder 中查找 .db 文件

        优先直接查找 .db，若无则尝试从 .db.tar.gz 解压。
        """
        folder = Path(self._map_folder)

        # 1) 查找已有的 .db 文件
        for f in folder.iterdir():
            if f.is_file() and f.suffix == ".db":
                return str(f)

        # 2) 查找 .db.tar.gz 并解压
        for f in folder.iterdir():
            if f.is_file() and f.name.endswith(".db.tar.gz"):
                extract_dir = str(folder)
                try:
                    with tarfile.open(str(f), "r:gz") as tar:
                        members = tar.getmembers()
                        for m in members:
                            if m.name.endswith(".db"):
                                tar.extract(m, extract_dir)
                                extracted = os.path.join(extract_dir, m.name)
                                logger.info(
                                    f"[HdMapMatcher] Extracted map DB: {f.name} → {extracted}"
                                )
                                return extracted
                except Exception as e:
                    logger.warning(f"[HdMapMatcher] Failed to extract {f.name}: {e}")

        return ""

    def _load_trajectory_points(self) -> None:
        """从 SQLite 加载所有车道轨迹点

        HDMAP_LANE.trajectory 格式:
          TRAJECTORY((lon,lat,alt,heading,...; lon,lat,...; ...))
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT laneid, trajectory FROM HDMAP_LANE "
                "WHERE trajectory IS NOT NULL AND trajectory != ''"
            ).fetchall()

            for lane_id, traj_text in rows:
                pts = self._parse_trajectory(traj_text)
                for lat, lon in pts:
                    self._points.append((lat, lon, lane_id))

            # 若 trajectory 不可用，回退到 LANENODE
            if not self._points:
                logger.info("[HdMapMatcher] No trajectory data, falling back to LANENODE")
                self._load_lanenode_points(conn)
        finally:
            conn.close()

    def _load_lanenode_points(self, conn: sqlite3.Connection) -> None:
        """回退方案: 从 HDMAP_LANENODE 加载节点坐标

        LANENODE 是车道端点，精度不如 trajectory 但可作为兜底。
        需要额外关联 HDMAP_LANE 的 pre_lanenodeid / suc_lanenodeid。
        """
        # 建立 node_id → lane_id 映射
        node_to_lane: dict[int, int] = {}
        lane_rows = conn.execute(
            "SELECT laneid, pre_lanenodeid, suc_lanenodeid FROM HDMAP_LANE"
        ).fetchall()
        for lane_id, pre, suc in lane_rows:
            if pre:
                node_to_lane[pre] = lane_id
            if suc:
                node_to_lane[suc] = lane_id

        # 加载节点坐标
        node_rows = conn.execute(
            "SELECT uniqueid, lat, lon FROM HDMAP_LANENODE"
        ).fetchall()
        for node_id, lat, lon in node_rows:
            if node_id in node_to_lane and lat and lon:
                self._points.append((lat, lon, node_to_lane[node_id]))

    @staticmethod
    def _parse_trajectory(traj_text: str) -> list[tuple[float, float]]:
        """解析 WKT TRAJECTORY 文本 → [(lat, lon), ...]

        格式: TRAJECTORY((lon,lat,alt,heading,speed,...; lon,lat,...; ...))
        每个点的前两个逗号分隔值为 (lon, lat)。
        """
        pts: list[tuple[float, float]] = []
        if not traj_text or not traj_text.startswith("TRAJECTORY"):
            return pts

        # 提取 "TRAJECTORY((" 和 "))" 之间的内容
        start = traj_text.find("((")
        end = traj_text.rfind("))")
        if start == -1 or end == -1 or end <= start:
            return pts

        inner = traj_text[start + 2:end]

        # 分号分隔每个点
        for point_str in inner.split(";"):
            point_str = point_str.strip()
            if not point_str:
                continue
            parts = point_str.split(",")
            if len(parts) >= 2:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    pts.append((lat, lon))
                except (ValueError, IndexError):
                    continue

        return pts

    def _find_nearest_lane(self, lat: float, lon: float) -> int:
        """暴力搜索最近轨迹点 → 返回所属 laneid"""
        best_id = 0
        best_dist = float("inf")
        for plat, plon, lid in self._points:
            dlat = plat - lat
            dlon = plon - lon
            d = dlat * dlat + dlon * dlon
            if d < best_dist:
                best_dist = d
                best_id = lid
        return best_id
