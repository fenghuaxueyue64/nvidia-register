"""终端组件 — 基于 Queue 的输出显示，支持颜色标签。"""

import queue
import customtkinter as ctk

from core.design import COLOR_TERMINAL_BG, COLOR_TEXT


class TerminalWidget(ctk.CTkTextbox):
    """自动滚动的终端显示组件，接收 stdout/stderr 输出。"""

    # 颜色映射
    TAG_COLORS = {
        "stderr": "#e74c3c",    # 红色
        "success": "#2ecc71",  # 绿色
        "warning": "#f39c12",  # 黄色
        "info": "#3498db",     # 蓝色
    }

    def __init__(self, master, output_queue: "queue.Queue | None" = None,
                 **kwargs):
        """
        Args:
            master: 父组件
            output_queue: RegisterRunner 的输出队列
        """
        kwargs.setdefault("font", ctk.CTkFont(family="Consolas", size=12))
        kwargs.setdefault("wrap", "none")
        kwargs.setdefault("activate_scrollbars", True)
        kwargs.setdefault("fg_color", COLOR_TERMINAL_BG)
        kwargs.setdefault("text_color", COLOR_TEXT)
        kwargs.setdefault("border_width", 0)
        super().__init__(master, **kwargs)

        self._output_queue = output_queue
        self._poll_interval = 100  # 毫秒
        self._polling = False
        self._tags_configured = False

    def _ensure_tags_configured(self):
        """确保颜色标签已配置（延迟到 widget 实际映射后）。"""
        if self._tags_configured:
            return
        try:
            inner = self._textbox  # CTkTextbox 内部的 tkinter Text
            for tag_name, color in self.TAG_COLORS.items():
                inner.tag_configure(f"tag_{tag_name}", foreground=color)
            self._tags_configured = True
        except Exception:
            pass

    def set_output_queue(self, output_queue: "queue.Queue"):
        """设置输出队列（运行开始后由 RunTab 调用）。"""
        self._output_queue = output_queue

    def start_polling(self):
        """开始轮询输出队列。"""
        if not self._polling:
            self._polling = True
            self._ensure_tags_configured()
            self._drain_queue()

    def stop_polling(self):
        """停止轮询。"""
        self._polling = False

    def _drain_queue(self):
        """从队列中取出所有待显示文本，批量插入。"""
        if not self._polling:
            return

        if self._output_queue:
            batch: "list[tuple[str, str]]" = []
            while True:
                try:
                    item = self._output_queue.get_nowait()
                    batch.append(item)
                except queue.Empty:
                    break

            if batch:
                self._ensure_tags_configured()
                inner = self._textbox
                for text, stream_name in batch:
                    tag = self._get_tag(text, stream_name)
                    inner.insert("end", text, tag if tag else ())
                inner.see("end")

        self.after(self._poll_interval, self._drain_queue)

    def _get_tag(self, text: str, stream_name: str) -> "str | None":
        """根据输出内容和流类型决定颜色标签。"""
        if stream_name == "stderr":
            return "tag_stderr"
        # 检测 emoji 标记
        if "✅" in text or "🎉" in text:
            return "tag_success"
        if "⚠️" in text or "⚠" in text:
            return "tag_warning"
        if "❌" in text:
            return "tag_stderr"
        return None

    def append_text(self, text: str, tag: "str | None" = None):
        """手动追加文本（线程安全，在主线程调用）。"""
        self._ensure_tags_configured()
        inner = self._textbox
        inner.insert("end", text, tag if tag else ())
        inner.see("end")

    def clear(self):
        """清空终端内容。"""
        self._textbox.delete("1.0", "end")
