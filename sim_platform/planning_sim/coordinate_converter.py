"""坐标转换器 — WGS84 ↔ ENU 局部坐标 (F-09-07)"""

import math


class LocalCoordinateConverter:
    """WGS84 经纬度 ↔ 局部 ENU 坐标转换 (墨卡托近似)

    小范围内 (矿卡作业区通常 < 10km) 精度满足需求。
    """

    EARTH_RADIUS: float = 6378137.0  # WGS84 地球半径 (m)

    def __init__(self):
        self._ref_lat: float = 0.0
        self._ref_lon: float = 0.0
        self._ref_lat_rad: float = 0.0
        self._ref_lon_rad: float = 0.0

    def set_reference(self, ref_lat: float, ref_lon: float) -> None:
        """设置局部坐标系原点 (经纬度)"""
        self._ref_lat = ref_lat
        self._ref_lon = ref_lon
        self._ref_lat_rad = math.radians(ref_lat)
        self._ref_lon_rad = math.radians(ref_lon)

    def latlon_to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        """经纬度 → 局部 ENU 坐标 (m)

        x = R * (lon - ref_lon) * cos(ref_lat)
        y = R * (lat - ref_lat)
        """
        dlat = math.radians(lat) - self._ref_lat_rad
        dlon = math.radians(lon) - self._ref_lon_rad
        x = self.EARTH_RADIUS * dlon * math.cos(self._ref_lat_rad)
        y = self.EARTH_RADIUS * dlat
        return x, y

    def xy_to_latlon(self, x: float, y: float) -> tuple[float, float]:
        """局部 ENU 坐标 → 经纬度"""
        lat = self._ref_lat + math.degrees(y / self.EARTH_RADIUS)
        lon = self._ref_lon + math.degrees(
            x / (self.EARTH_RADIUS * math.cos(self._ref_lat_rad))
        )
        return lat, lon

    @staticmethod
    def latlon_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """计算两经纬度之间的近似距离 (m)"""
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        cos_lat = math.cos(math.radians((lat1 + lat2) / 2.0))
        return math.sqrt(
            (dlat * 6378137.0) ** 2 + (dlon * 6378137.0 * cos_lat) ** 2
        )
