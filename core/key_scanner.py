"""Key 扫描器 — 扫描当前配置目录，返回结构化的 Key 列表。"""

import os
from dataclasses import dataclass


@dataclass
class KeyEntry:
    """单个 API Key 条目。"""
    filepath: str            # 完整路径
    filename: str            # 文件名
    key_value: str           # API Key 值
    created_at: str          # 从文件名解析的时间戳
    batch: str               # 批次（子目录名）
    sequence: int            # 序号


class KeyScanner:
    """扫描目录下的 API Key 文件。"""

    def __init__(self, keys_dir: str):
        self.keys_dir = keys_dir

    def scan(self) -> list[KeyEntry]:
        """递归扫描当前目录，返回所有 Key 条目。"""
        entries: list[KeyEntry] = []
        if not os.path.exists(self.keys_dir):
            return entries

        for dirpath, _dirnames, filenames in os.walk(self.keys_dir):
            for fname in sorted(filenames):
                if not fname.startswith("nvidia_api_key_") or not fname.endswith(".txt"):
                    continue
                full_path = os.path.join(dirpath, fname)
                rel_dir = os.path.relpath(dirpath, self.keys_dir)
                batch = rel_dir if rel_dir != "." else ""

                created_at, sequence = self._parse_filename(fname)

                # 读取 Key 值
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        key_value = f.read().strip()
                except Exception:
                    key_value = "(无法读取)"

                entries.append(KeyEntry(
                    filepath=full_path,
                    filename=fname,
                    key_value=key_value,
                    created_at=created_at,
                    batch=batch,
                    sequence=sequence,
                ))

        # 按文件名时间戳降序（最新在前），序号只作为同一秒内的次级排序。
        entries.sort(key=self._entry_sort_key, reverse=True)
        return entries

    def stats(self) -> dict:
        """返回摘要统计信息。"""
        entries = self.scan()
        batches = set(e.batch for e in entries if e.batch)
        return {
            "total_keys": len(entries),
            "batches": len(batches),
            "keys_dir": self.keys_dir,
        }

    def get_latest_key_file(self) -> str | None:
        """返回最新 Key 文件的完整路径，无 Key 时返回 None。"""
        entries = self.scan()
        return entries[0].filepath if entries else None

    @staticmethod
    def _entry_sort_key(entry: KeyEntry) -> tuple[str, int, float]:
        try:
            modified_at = os.path.getmtime(entry.filepath)
        except OSError:
            modified_at = 0.0
        return (entry.created_at, entry.sequence, modified_at)

    @staticmethod
    def _parse_filename(filename: str) -> tuple[str, int]:
        """从文件名解析时间戳和序号。

        格式: nvidia_api_key_{seq}_{YYYYMMDD}_{HHMMSS}.txt
        返回: (created_at, sequence)
        """
        stem = filename[len("nvidia_api_key_"):-len(".txt")]
        parts = stem.split("_")
        sequence = 0
        created_at = ""
        try:
            sequence = int(parts[0])
        except (ValueError, IndexError):
            pass
        if len(parts) >= 3:
            created_at = f"{parts[-2]}_{parts[-1]}"
        return created_at, sequence
