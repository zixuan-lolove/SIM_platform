"""HTTP 文件下载器 — 对应 C++ HttpDownloader

用于从云端文件服务下载地图文件和任务压缩包 (tar.gz)。
请求头包含 timestamp + sign=md5("crccAuthentication" + timestamp) + projectid。
"""

import hashlib
import logging
import time
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class HttpDownloader:
    """HTTP 文件下载器"""

    AUTH_SECRET: str = "crccAuthentication"

    @staticmethod
    def download(url: str, dest_path: str, project_id: str = "", timeout: int = 30) -> bool:
        """下载文件到本地

        Args:
            url: 下载地址 (GET)
            dest_path: 本地保存路径
            project_id: 项目 ID (鉴权后获取)
            timeout: 超时秒数

        Returns:
            True 表示下载成功
        """
        timestamp = str(int(time.time()))
        sign = hashlib.md5(
            (HttpDownloader.AUTH_SECRET + timestamp).encode()
        ).hexdigest()

        headers = {
            "timestamp": timestamp,
            "sign": sign,
        }
        if project_id:
            headers["projectid"] = project_id

        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            with open(dest_path, "wb") as f:
                f.write(data)
            return True
        except Exception as e:
            logger.warning(f"HTTP download failed: {url} — {e}")
            return False

    @staticmethod
    def download_task_file(
        base_url: str,
        file_name: str,
        dest_dir: str,
        project_id: str = "",
    ) -> str:
        """下载任务文件 (.tar.gz) 到指定目录

        Args:
            base_url: 文件服务基地址 (来自 ServerParamsQueryResponse 0xF002)
            file_name: 文件名
            dest_dir: 目标目录
            project_id: 项目 ID

        Returns:
            下载后的完整文件路径，失败返回空字符串
        """
        import os
        url = f"{base_url.rstrip('/')}?fileName={file_name}"
        dest_path = os.path.join(dest_dir, file_name)
        os.makedirs(dest_dir, exist_ok=True)
        if HttpDownloader.download(url, dest_path, project_id):
            return dest_path
        return ""
