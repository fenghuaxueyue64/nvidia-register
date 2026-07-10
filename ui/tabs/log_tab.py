"""日志标签页 — 查看历史运行日志。"""

import os
import customtkinter as ctk
from core.log_manager import LogManager


class LogTab(ctk.CTkFrame):
    """日志标签页：展示历史运行日志列表和内容。"""

    def __init__(self, master, log_manager: LogManager,
                 font_title=None, font_body=None, font_small=None, **kwargs):
        super().__init__(master, **kwargs)
        self._lm = log_manager
        self._font_title = font_title or ctk.CTkFont(family="Segoe UI Variable", size=22, weight="bold")
        self._font_body = font_body or ctk.CTkFont(family="Segoe UI Variable", size=14)
        self._font_small = font_small or ctk.CTkFont(family="Segoe UI Variable", size=12)

        self._selected_log_path: str | None = None

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        """构建日志标签页 UI — 左右分栏。"""
        # 顶部标题栏
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(10, 5))

        ctk.CTkLabel(
            header, text="日志",
            font=self._font_title, anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            header, text="🔄 刷新", font=self._font_small,
            width=70, height=28,
            command=self.refresh,
        ).pack(side="right")

        self._count_label = ctk.CTkLabel(
            header, text="日志: 0",
            font=self._font_body,
            text_color=("gray40", "gray60"),
        )
        self._count_label.pack(side="right", padx=(0, 15))

        # 分隔线
        ctk.CTkFrame(
            self, height=1, fg_color=("gray80", "gray30"),
        ).pack(fill="x", padx=15, pady=(0, 5))

        # ===== 主体：左列表 + 右内容（用 weight 比例分配，适配窗口宽度）=====
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=15, pady=5)
        # 左:右 = 1:3 比例，minwidth 保证不塌陷
        body.columnconfigure(0, weight=1, minsize=200)
        body.columnconfigure(1, weight=3, minsize=400)
        body.rowconfigure(0, weight=1)

        # 左侧：日志列表
        left_frame = ctk.CTkFrame(body, fg_color=("gray96", "gray17"))
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        ctk.CTkLabel(
            left_frame, text="日志列表",
            font=ctk.CTkFont(family="Segoe UI Variable", size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(8, 4))

        self._log_list = ctk.CTkScrollableFrame(left_frame, fg_color="transparent")
        self._log_list.pack(fill="both", expand=True, padx=2, pady=2)

        # 右侧：日志内容
        right_frame = ctk.CTkFrame(body, fg_color=("gray96", "gray17"))
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        self._log_content = ctk.CTkTextbox(
            right_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="none",
            activate_scrollbars=True,
            state="disabled",
        )
        self._log_content.pack(fill="both", expand=True, padx=5, pady=5)

    def refresh(self):
        """刷新日志列表。"""
        # 清空列表
        for widget in self._log_list.winfo_children():
            widget.destroy()

        logs = self._lm.list_logs()
        self._count_label.configure(text=f"日志: {len(logs)}")

        if not logs:
            ctk.CTkLabel(
                self._log_list,
                text="暂无日志",
                font=self._font_small,
                text_color=("gray50", "gray60"),
            ).pack(pady=20)
            self._set_content("暂无日志记录。运行注册任务后日志将自动保存。")
            return

        for log_entry in logs:
            # 格式化时间显示
            display_time = self._format_time(log_entry.created_at)
            btn = ctk.CTkButton(
                self._log_list,
                text=display_time,
                font=ctk.CTkFont(family="Consolas", size=11),
                fg_color="transparent",
                hover_color=("gray85", "gray25"),
                text_color=("gray10", "gray90"),
                anchor="w",
                height=28,
                command=lambda p=log_entry.filepath: self._select_log(p),
            )
            btn.pack(fill="x", padx=2, pady=1)

    def _select_log(self, filepath: str):
        """选中一个日志文件并显示内容。"""
        self._selected_log_path = filepath
        content = self._lm.read_log(filepath)
        self._set_content(content)

    def _set_content(self, text: str):
        """设置日志内容区域的文本。"""
        self._log_content.configure(state="normal")
        self._log_content.delete("1.0", "end")
        self._log_content.insert("1.0", text)
        self._log_content.configure(state="disabled")

    @staticmethod
    def _format_time(ts: str) -> str:
        """格式化时间戳。"""
        if not ts:
            return "(unknown)"
        parts = ts.split("_")
        if len(parts) == 2 and len(parts[0]) == 8 and len(parts[1]) == 6:
            date_part = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}"
            time_part = f"{parts[1][:2]}:{parts[1][2:4]}:{parts[1][4:6]}"
            return f"{date_part} {time_part}"
        return ts
