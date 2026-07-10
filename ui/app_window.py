"""主窗口 — NVIDIARegister 桌面应用。Material 3。"""

import os
import customtkinter as ctk

from ui.sidebar import Sidebar
from ui.tabs.run_tab import RunTab
from ui.tabs.config_tab import ConfigTab
from ui.tabs.key_db_tab import KeyDBTab
from ui.tabs.domain_db_tab import DomainDBTab
from ui.tabs.log_tab import LogTab
from ui.tabs.model_test_tab import ModelTestTab
from core.config_manager import ConfigManager
from core.key_scanner import KeyScanner
from core.runner import RegisterRunner
from core.process_manager import ProcessManager
from core.log_manager import LogManager
from core.runtime_paths import app_base_dir
from core.runtime_paths import resource_path
from core.design import (
    COLOR_BG, COLOR_SURFACE, COLOR_OUTLINE, COLOR_TEXT_SECONDARY,
    SPACING_SM, FONT_CAPTION,
)

SCRIPT_DIR = app_base_dir()
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")
KEYS_DIR = os.path.join(SCRIPT_DIR, "keys")
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")


class NvidiaApp(ctk.CTk):
    """NVIDIA Register Control 主窗口。"""

    def __init__(self):
        super().__init__()

        self.title("NVIDIARegister")
        self.geometry("1280x800")
        self.minsize(1024, 700)
        self._set_window_icon()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        # 核心服务
        self._config_manager = ConfigManager(ENV_FILE)
        self._key_scanner = KeyScanner(KEYS_DIR)
        self._log_manager = LogManager(LOGS_DIR)
        self._process_manager = ProcessManager()
        self._runner = RegisterRunner(app=self)

        self._setup_layout()
        self._create_tabs()
        self._show_tab("run")
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ------ 布局 ------

    def _setup_layout(self):
        # 内容区（白/深色底）
        self._content_frame = ctk.CTkFrame(
            self, fg_color=COLOR_BG, corner_radius=0,
        )
        self._content_frame.pack(side="right", fill="both", expand=True)

        # 侧边栏
        self._sidebar = Sidebar(
            self,
            on_tab_selected=self._show_tab,
            on_theme_changed=self._on_theme_changed,
        )
        self._sidebar.pack(side="left", fill="y")

        # 状态栏
        self._status_bar = ctk.CTkFrame(
            self._content_frame, height=30, corner_radius=0, border_width=0,
            fg_color=COLOR_SURFACE,
        )
        self._status_bar.pack(side="bottom", fill="x")
        self._status_bar.pack_propagate(False)

        ctk.CTkFrame(
            self._content_frame, height=1, fg_color=COLOR_OUTLINE,
        ).pack(side="bottom", fill="x")

        env_exists = os.path.exists(ENV_FILE)
        check = "✓" if env_exists else "✗"
        display = ENV_FILE if env_exists else "未找到 .env"
        self._status_label = ctk.CTkLabel(
            self._status_bar,
            text=f"  {check} 配置: {display}",
            font=FONT_CAPTION, text_color=COLOR_TEXT_SECONDARY, anchor="w",
        )
        self._status_label.pack(side="left", fill="x", padx=SPACING_SM)

    def _create_tabs(self):
        self._tabs = {}
        self._tabs["run"] = RunTab(
            self._content_frame,
            runner=self._runner, config_manager=self._config_manager,
            key_scanner=self._key_scanner, log_manager=self._log_manager,
            process_manager=self._process_manager,
        )
        self._tabs["config"] = ConfigTab(
            self._content_frame, config_manager=self._config_manager,
        )
        self._tabs["key_db"] = KeyDBTab(
            self._content_frame, key_scanner=self._key_scanner, keys_dir=KEYS_DIR,
            config_manager=self._config_manager,
        )
        self._tabs["domain_db"] = DomainDBTab(
            self._content_frame, config_manager=self._config_manager,
        )
        self._tabs["log"] = LogTab(
            self._content_frame, log_manager=self._log_manager,
        )
        self._tabs["model_test"] = ModelTestTab(
            self._content_frame, config_manager=self._config_manager,
        )

    def _show_tab(self, tab_key: str):
        for key, tab in self._tabs.items():
            if key == tab_key:
                tab.pack(fill="both", expand=True, in_=self._content_frame,
                         side="top", before=self._status_bar)
            else:
                tab.pack_forget()
        if tab_key == "run" and hasattr(self._tabs.get("run", None), '_refresh_duckmail_selector'):
            self._tabs["run"]._refresh_duckmail_selector()

    def update_status(self, text: str):
        self._status_label.configure(text=f"  {text}")

    def _set_window_icon(self):
        icon_path = resource_path(os.path.join("icon", "app.ico"))
        if not os.path.exists(icon_path):
            return
        try:
            self.iconbitmap(icon_path)
        except Exception:
            pass

    def _on_theme_changed(self, theme: str):
        ctk.set_appearance_mode(theme)

    def _on_closing(self):
        if self._runner.is_running:
            self._runner.stop()
            if self._runner._thread:
                self._runner._thread.join(timeout=2.0)
        self.destroy()
