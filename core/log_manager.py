"""日志管理器 — 运行日志的保存和读取。"""

import os
import time
from dataclasses import dataclass


@dataclass
class LogEntry:
    """日志文件条目。"""
    filepath: str
    filename: str
    created_at: str       # 从文件名解析的时间


class LogManager:
    """管理运行日志的保存和读取。"""

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir

    def ensure_dir(self):
        """确保日志目录存在。"""
        os.makedirs(self.logs_dir, exist_ok=True)

    def save_run_log(self, content: str, run_index: int = 0) -> str:
        """保存一次运行的日志内容，返回日志文件路径。"""
        self.ensure_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"run_{run_index}_{ts}.log"
        filepath = os.path.join(self.logs_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def list_logs(self) -> list[LogEntry]:
        """返回所有日志文件条目，按时间降序排列。"""
        if not os.path.exists(self.logs_dir):
            return []

        entries: list[LogEntry] = []
        for fname in os.listdir(self.logs_dir):
            if not fname.endswith(".log"):
                continue
            filepath = os.path.join(self.logs_dir, fname)
            # 从文件名解析时间: run_1_20260630_094213.log
            created_at = self._parse_timestamp(fname)
            entries.append(LogEntry(
                filepath=filepath,
                filename=fname,
                created_at=created_at,
            ))

        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def read_log(self, filepath: str) -> str:
        """读取日志文件内容。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"(读取失败: {e})"

    @staticmethod
    def _parse_timestamp(filename: str) -> str:
        """从文件名解析时间戳。"""
        # run_1_20260630_094213.log → 20260630_094213
        stem = filename[:-len(".log")]
        parts = stem.split("_")
        if len(parts) >= 4:
            return f"{parts[-2]}_{parts[-1]}"
        return ""
