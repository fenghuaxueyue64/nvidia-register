"""Key 数据库标签页 — 展示当前配置目录下的 API Key 文件。"""

import os
import customtkinter as ctk
from core.config_manager import ConfigManager
from core.key_paths import resolve_key_scan_dir, shorten_display_path
from core.key_scanner import KeyScanner, KeyEntry


class KeyDBTab(ctk.CTkFrame):
    """Key 数据库标签页：扫描并展示当前配置目录下的 Key 文件。"""

    def __init__(self, master, key_scanner: KeyScanner, keys_dir: str,
                 config_manager: ConfigManager | None = None,
                 font_title=None, font_body=None, font_small=None, **kwargs):
        super().__init__(master, **kwargs)
        self._ks = key_scanner
        self._keys_dir = keys_dir
        self._default_keys_dir = keys_dir
        self._cm = config_manager
        self._config_base_dir = os.path.dirname(config_manager.env_path) if config_manager else None
        self._font_title = font_title or ctk.CTkFont(family="Roboto", size=20, weight="bold")
        self._font_body = font_body or ctk.CTkFont(family="Roboto", size=13)
        self._font_small = font_small or ctk.CTkFont(family="Roboto", size=11)

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        """构建 Key 数据库标签页 UI。"""
        # ===== 顶部：标题 + 操作按钮 =====
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(10, 5))

        ctk.CTkLabel(
            header, text="Key 数据库",
            font=self._font_title, anchor="w",
        ).pack(side="left")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        self._stats_label = ctk.CTkLabel(
            btn_frame, text="Key: 0",
            font=self._font_body,
            text_color=("gray40", "gray60"),
        )
        self._stats_label.pack(side="left", padx=(0, 15))

        ctk.CTkButton(
            btn_frame, text="🔄 刷新", font=self._font_small,
            width=70, height=28,
            command=self.refresh,
        ).pack(side="right", padx=3)

        ctk.CTkButton(
            btn_frame, text="📂 打开目录", font=self._font_small,
            width=90, height=28,
            command=self._open_dir,
        ).pack(side="right", padx=3)

        # 分隔线
        ctk.CTkFrame(
            self, height=1, fg_color=("gray80", "gray30"),
        ).pack(fill="x", padx=15, pady=(0, 5))

        self._dir_label = ctk.CTkLabel(
            self, text="", font=self._font_small,
            text_color=("gray45", "gray60"), anchor="w",
        )
        self._dir_label.pack(fill="x", padx=15, pady=(0, 5))

        # ===== 表头 =====
        col_header = ctk.CTkFrame(self, fg_color=("gray90", "gray20"))
        col_header.pack(fill="x", padx=15, pady=(0, 2))

        headers = ["批次", "文件名", "API Key", "时间", ""]
        widths = [60, 250, 300, 130, 50]
        for i, (text, width) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(
                col_header, text=text,
                font=ctk.CTkFont(family="Roboto", size=12, weight="bold"),
                width=width, anchor="w",
            ).pack(side="left", padx=8, pady=4)

        # ===== 表格区域（可滚动） =====
        self._table_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._table_scroll.pack(fill="both", expand=True, padx=15, pady=5)

    def refresh(self):
        """刷新 Key 列表。"""
        self._sync_key_scanner()
        entries = self._ks.scan()
        stats = self._ks.stats()

        # 更新统计
        self._stats_label.configure(
            text=f"Key: {stats['total_keys']} | 批次: {stats['batches']}"
        )
        self._dir_label.configure(text=f"目录: {shorten_display_path(self._keys_dir)}")

        # 清空现有行
        for widget in self._table_scroll.winfo_children():
            widget.destroy()

        if not entries:
            ctk.CTkLabel(
                self._table_scroll,
                text="暂无 Key 数据",
                font=self._font_body,
                text_color=("gray50", "gray60"),
            ).pack(pady=30)
            return

        # 添加行
        for entry in entries:
            self._add_row(entry)

    def _add_row(self, entry: KeyEntry):
        """添加一行 Key 数据。"""
        row = ctk.CTkFrame(self._table_scroll, fg_color="transparent", height=32)
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        # 批次
        ctk.CTkLabel(
            row, text=entry.batch or "-",
            font=self._font_small, width=60, anchor="w",
        ).pack(side="left", padx=8)

        # 文件名
        ctk.CTkLabel(
            row, text=entry.filename,
            font=self._font_small, width=250, anchor="w",
        ).pack(side="left", padx=8)

        # API Key（脱敏）
        masked = self._mask_key(entry.key_value)
        key_label = ctk.CTkLabel(
            row, text=masked,
            font=ctk.CTkFont(family="Consolas", size=11),
            width=300, anchor="w",
        )
        key_label.pack(side="left", padx=8)

        # 时间
        formatted_time = self._format_time(entry.created_at)
        ctk.CTkLabel(
            row, text=formatted_time,
            font=self._font_small, width=130, anchor="w",
        ).pack(side="left", padx=8)

        # 复制按钮
        ctk.CTkButton(
            row, text="📋", font=self._font_small,
            width=36, height=24,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=lambda k=entry.key_value: self._copy_key(k),
        ).pack(side="left", padx=4)

    @staticmethod
    def _mask_key(key: str) -> str:
        """对 API Key 做脱敏处理。"""
        if not key or key == "(无法读取)":
            return key
        if len(key) <= 14:
            return key[:6] + "****"
        return key[:10] + "****" + key[-4:]

    @staticmethod
    def _format_time(ts: str) -> str:
        """格式化时间戳显示。"""
        if not ts:
            return "-"
        # 20260630_094213 → 2026-06-30 09:42:13
        parts = ts.split("_")
        if len(parts) == 2 and len(parts[0]) == 8 and len(parts[1]) == 6:
            date_part = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}"
            time_part = f"{parts[1][:2]}:{parts[1][2:4]}:{parts[1][4:6]}"
            return f"{date_part} {time_part}"
        return ts

    def _copy_key(self, key: str):
        """复制 Key 到剪贴板。"""
        try:
            self.clipboard_clear()
            self.clipboard_append(key)
        except Exception:
            pass

    def _open_dir(self):
        """打开当前 Key 目录。"""
        self._sync_key_scanner()
        os.makedirs(self._keys_dir, exist_ok=True)
        self._open_path(self._keys_dir)

    def _sync_key_scanner(self):
        if self._cm:
            config = self._cm.read()
            self._keys_dir = resolve_key_scan_dir(
                config.get("NV_KEY_FILE", ""), self._default_keys_dir, self._config_base_dir
            )
        self._ks.keys_dir = self._keys_dir
        return self._keys_dir

    @staticmethod
    def _open_path(path: str):
        """跨平台打开路径。"""
        import sys
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
