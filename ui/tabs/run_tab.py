"""运行标签页 — Material 3 卡片化布局，按钮层级分明。"""

import os
import threading
import customtkinter as ctk
from tkinter import filedialog

from core.ai_config import AI_MODEL_OPTIONS, normalize_ai_model, normalize_openai_base_url
from core.runner import RegisterRunner
from core.config_manager import ConfigManager
from core.key_paths import (
    resolve_key_save_target,
    resolve_key_scan_dir,
    shorten_display_path,
)
from core.key_scanner import KeyScanner
from core.log_manager import LogManager
from core.process_manager import ProcessManager
from core.design import (
    COLOR_BG, COLOR_SURFACE, COLOR_SURFACE_VARIANT, COLOR_OUTLINE,
    COLOR_BTN_HOVER, COLOR_BTN_SURFACE, COLOR_INFO_BG,
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_TEXT,
    COLOR_TEXT_SECONDARY, COLOR_TERMINAL_BG,
    SPACING_XS, SPACING_SM, SPACING_MD, SPACING_LG, SPACING_XL,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    FONT_CAPTION, FONT_MONO_BODY,
)
from ui.widgets.terminal_widget import TerminalWidget


def _mk_font(size: int, weight="normal", family="Segoe UI Variable"):
    return ctk.CTkFont(family=family, size=size, weight=weight)


class RunTab(ctk.CTkFrame):
    """运行标签页 — 卡片化 Material 3 布局。"""

    def __init__(self, master,
                 runner: RegisterRunner,
                 config_manager: ConfigManager,
                 key_scanner: KeyScanner,
                 log_manager: LogManager,
                 process_manager: ProcessManager,
                 font_title=None, font_body=None, font_small=None,
                 **kwargs):
        super().__init__(master, fg_color=COLOR_BG, **kwargs)
        self._runner = runner
        self._cm = config_manager
        self._config_base_dir = os.path.dirname(config_manager.env_path)
        self._ks = key_scanner
        self._default_keys_dir = key_scanner.keys_dir
        self._lm = log_manager
        self._pm = process_manager
        self._pm.set_browser_config(self._cm.read())
        self._ft = font_title or _mk_font(18, "bold")
        self._fb = font_body or _mk_font(14)
        self._fs = font_small or _mk_font(12)

        # Runner 回调
        self._runner.on_progress = self._on_progress
        self._runner.on_complete = self._on_complete
        self._runner.on_error = self._on_error
        self._runner.on_state_changed = self._on_state_changed

        self._build_ui()
        self._load_ai_settings_from_config()
        self._load_export_settings_from_config()
        self._refresh_duckmail_selector()

    # ============================================================
    # UI 构建 — 卡片化
    # ============================================================

    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=SPACING_XL, pady=SPACING_LG)

        # ---- 1. 运行控制 Card ----
        self._build_control_card(scroll)

        # ---- 2. 统计卡片 ----
        self._build_stats_card(scroll)

        # ---- 3. 终端 Card ----
        self._build_terminal_card(scroll)

        # ---- 4. 提示卡 ----
        self._build_info_card(scroll)

    # ============================================================
    # Card 1: 运行控制
    # ============================================================

    def _build_control_card(self, parent):
        card = self._card(parent)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", pady=(0, SPACING_MD))
        ctk.CTkLabel(
            header, text="运行控制", font=_mk_font(15, "bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")
        self._build_top_actions(header)

        # 参数行：次数 + 账户 + 复选框
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", pady=(0, SPACING_MD))

        ctk.CTkLabel(row1, text="运行轮数", font=self._fb).pack(side="left", padx=(0, SPACING_SM))
        self._count_entry = ctk.CTkEntry(row1, width=56, font=self._fb, justify="center")
        self._count_entry.insert(0, "1")
        self._count_entry.pack(side="left", padx=(0, SPACING_LG))

        # (并发选择器已移至主操作行，紧挨开始按钮)

        # DuckMail 选择器
        self._duckmail_selector_frame = ctk.CTkFrame(row1, fg_color="transparent")
        self._duckmail_label = ctk.CTkLabel(
            self._duckmail_selector_frame, text="账户", font=self._fs,
        )
        self._duckmail_label.pack(side="left", padx=(0, SPACING_SM))
        self._duckmail_selector = ctk.CTkOptionMenu(
            self._duckmail_selector_frame,
            values=["默认"],
            font=self._fs, width=200,
            command=self._on_duckmail_changed,
        )
        self._duckmail_selector.pack(side="left")

        self._show_config_cb = ctk.CTkCheckBox(
            row1, text="预览配置", font=self._fs,
            border_width=2, checkbox_width=18, checkbox_height=18,
        )
        self._show_config_cb.select()
        self._show_config_cb.pack(side="left", padx=(SPACING_XL, 0))

        # ---- AI 验证码开关 ----
        self._ai_captcha_frame = ctk.CTkFrame(row1, fg_color="transparent")
        self._ai_captcha_label = ctk.CTkLabel(
            self._ai_captcha_frame, text="AI验证", font=self._fs,
        )
        self._ai_captcha_label.pack(side="left", padx=(0, SPACING_SM))
        self._ai_captcha_switch = ctk.CTkSwitch(
            self._ai_captcha_frame, text="", width=40,
            onvalue="true", offvalue="false",
            command=self._on_ai_captcha_toggled,
        )
        self._ai_captcha_switch.pack(side="left")
        self._ai_captcha_frame.pack(side="left", padx=(SPACING_XL, 0))

        # ---- 导出模式开关 ----
        self._export_frame = ctk.CTkFrame(row1, fg_color="transparent")

        self._export_key_frame = ctk.CTkFrame(self._export_frame, fg_color="transparent")
        ctk.CTkLabel(
            self._export_key_frame, text="导出Key", font=self._fs,
        ).pack(side="left", padx=(0, SPACING_SM))
        self._export_key_switch = ctk.CTkSwitch(
            self._export_key_frame, text="", width=40,
            onvalue="true", offvalue="false",
        )
        self._export_key_switch.pack(side="left")
        self._export_key_frame.pack(side="left", padx=(0, SPACING_MD))

        self._export_acct_frame = ctk.CTkFrame(self._export_frame, fg_color="transparent")
        ctk.CTkLabel(
            self._export_acct_frame, text="导出完整", font=self._fs,
        ).pack(side="left", padx=(0, SPACING_SM))
        self._export_acct_switch = ctk.CTkSwitch(
            self._export_acct_frame, text="", width=40,
            onvalue="true", offvalue="false",
        )
        self._export_acct_switch.pack(side="left")
        self._export_acct_frame.pack(side="left")

        self._export_frame.pack(side="left", padx=(SPACING_XL, 0))

        # ---- 主操作行 (Primary + Stop + Concurrency) ----
        row_primary = ctk.CTkFrame(card, fg_color="transparent")
        row_primary.pack(fill="x")

        self._start_btn = ctk.CTkButton(
            row_primary, text="▶ 开始运行", font=_mk_font(13, "bold"),
            fg_color=COLOR_PRIMARY, text_color=("#FFFFFF", "#003D8B"),
            hover_color=("#1557B0", "#A8C7FA"),
            corner_radius=RADIUS_MD, height=32, width=112,
            command=self._start_run,
        )
        self._start_btn.pack(side="left", padx=(0, SPACING_SM))

        self._stop_btn = ctk.CTkButton(
            row_primary, text="■ 停止", font=_mk_font(13, "bold"),
            fg_color=COLOR_BTN_SURFACE, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_OUTLINE,
            hover_color=COLOR_BTN_HOVER,
            corner_radius=RADIUS_MD, height=32, width=70,
            state="disabled", command=self._stop_run,
        )
        self._stop_btn.pack(side="left", padx=(0, SPACING_SM))

        self._small_action_button(
            row_primary, "测试连接", 82, self._test_ai_connection,
        ).pack(side="left", padx=(0, SPACING_LG))

        # ---- 并发数选择器 (紧挨操作按钮，醒目) ----
        ctk.CTkLabel(row_primary, text="并发数", font=self._fs).pack(
            side="left", padx=(0, SPACING_SM))
        self._concurrency_var = ctk.StringVar(value="1")
        self._concurrency_selector = ctk.CTkOptionMenu(
            row_primary,
            values=["1", "2", "3", "4", "5", "8", "10"],
            variable=self._concurrency_var,
            font=self._fs, width=62,
            command=self._on_concurrency_changed,
        )
        self._concurrency_selector.pack(side="left")

        # ---- 并发警告 (默认隐藏) ----
        self._concurrency_warning = ctk.CTkLabel(
            card, text="",
            font=self._fs,
            text_color=("#B06000", "#FDD663"),
            wraplength=600,
        )

        # ---- AI 验证码设置行 (可折叠) ----
        self._ai_settings_frame = ctk.CTkFrame(card, fg_color="transparent")

        ai_inner = ctk.CTkFrame(self._ai_settings_frame, fg_color=COLOR_SURFACE_VARIANT,
                                 corner_radius=RADIUS_MD)
        ai_inner.pack(fill="x")

        # 检测状态行
        self._ai_status_row = ctk.CTkFrame(ai_inner, fg_color="transparent")
        self._ai_status_row.pack(fill="x", padx=SPACING_SM, pady=(SPACING_SM, 2))
        self._ai_status_label = ctk.CTkLabel(
            self._ai_status_row, text="🔍 自动检测中...",
            font=FONT_CAPTION, text_color=COLOR_TEXT_SECONDARY,
        )
        self._ai_status_label.pack(side="left")

        # 高级设置行 (默认隐藏)
        self._ai_advanced_frame = ctk.CTkFrame(ai_inner, fg_color="transparent")

        ai_row1 = ctk.CTkFrame(self._ai_advanced_frame, fg_color="transparent")
        ai_row1.pack(fill="x", padx=SPACING_SM, pady=SPACING_SM)

        ctk.CTkLabel(ai_row1, text="API 地址:", font=self._fs).pack(side="left")
        self._ai_api_base_entry = ctk.CTkEntry(
            ai_row1, width=280, font=_mk_font(12),
            placeholder_text="auto (自动检测本地服务)",
        )
        self._ai_api_base_entry.pack(side="left", padx=(SPACING_XS, SPACING_SM), fill="x", expand=True)

        ctk.CTkLabel(ai_row1, text="模型:", font=self._fs).pack(side="left")
        self._ai_model_selector = ctk.CTkOptionMenu(
            ai_row1, values=AI_MODEL_OPTIONS,
            width=180, font=_mk_font(12),
            corner_radius=RADIUS_SM,
        )
        self._ai_model_selector.set("qwen3.6-flash")
        self._ai_model_selector.pack(side="left", padx=(SPACING_XS, 0))

        ai_row2 = ctk.CTkFrame(self._ai_advanced_frame, fg_color="transparent")
        ai_row2.pack(fill="x", padx=SPACING_SM, pady=(0, SPACING_SM))

        ctk.CTkLabel(ai_row2, text="API Key:", font=self._fs).pack(side="left")
        self._ai_key_entry = ctk.CTkEntry(
            ai_row2, width=400, font=_mk_font(12),
            placeholder_text="本地服务无需填写",
        )
        self._ai_key_entry.pack(side="left", padx=(SPACING_XS, 0), fill="x", expand=True)

        ctk.CTkButton(
            ai_row2, text="⚙ 高级", font=FONT_CAPTION, width=60, height=28,
            fg_color=COLOR_BTN_SURFACE, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_OUTLINE,
            corner_radius=RADIUS_SM,
            command=lambda: self._ai_advanced_frame.pack(
                fill="x", padx=0, pady=0, in_=ai_inner, after=self._ai_status_row)
                if not self._ai_advanced_frame.winfo_ismapped()
                else self._ai_advanced_frame.pack_forget(),
        ).pack(side="right", padx=(SPACING_SM, 0))

        # 进度 + 环境指示
        bot = ctk.CTkFrame(card, fg_color="transparent")
        bot.pack(fill="x", pady=(SPACING_SM, 0))
        self._progress_label = ctk.CTkLabel(
            bot, text="", font=self._fs, text_color=COLOR_TEXT_SECONDARY,
        )
        self._progress_label.pack(side="left")
        self._env_label = ctk.CTkLabel(
            bot, text="", font=FONT_CAPTION, text_color=COLOR_TEXT_SECONDARY,
        )
        self._env_label.pack(side="right")
        self._update_env_status()

    # ============================================================
    # Card 2: 统计卡片
    # ============================================================

    def _build_stats_card(self, parent):
        card = self._card(parent, pad_y=SPACING_MD)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x")

        self._build_key_actions(row)

        self._stat_key_num = self._build_stat_metric(row, "Keys", COLOR_PRIMARY)
        self._stat_acct_num = self._build_stat_metric(row, "账户", COLOR_SUCCESS)

        key_path_frame = ctk.CTkFrame(row, fg_color="transparent")
        key_path_frame.pack(side="left", fill="x", expand=True, padx=(SPACING_SM, SPACING_LG))

        ctk.CTkLabel(
            key_path_frame, text="Key 保存目录", font=FONT_CAPTION,
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(anchor="w")

        self._key_path_label = ctk.CTkLabel(
            key_path_frame, text="", font=FONT_CAPTION,
            text_color=COLOR_TEXT_SECONDARY, anchor="w",
        )
        self._key_path_label.pack(fill="x")

        self._update_db_stats()

    def _build_stat_metric(self, parent, label: str, color):
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.pack(side="left", padx=(0, SPACING_LG))

        number = ctk.CTkLabel(
            group, text="0", font=_mk_font(24, "bold"), text_color=color,
        )
        number.pack(side="left", padx=(0, SPACING_XS))

        ctk.CTkLabel(
            group, text=label, font=FONT_CAPTION,
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(side="left")

        return number

    # ============================================================
    # Card 3: 终端
    # ============================================================

    def _build_terminal_card(self, parent):
        card = self._card(parent, pad=False)
        # 终端卡片深色背景
        card.configure(fg_color=COLOR_TERMINAL_BG)

        # 标题栏
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.pack(fill="x", padx=SPACING_LG, pady=(SPACING_MD, 0))

        ctk.CTkLabel(
            bar, text="终端", font=_mk_font(14, "bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")

        ctk.CTkButton(
            bar, text="清空", font=FONT_CAPTION,
            fg_color="transparent", text_color=COLOR_TEXT_SECONDARY,
            hover_color=COLOR_BTN_HOVER,
            corner_radius=RADIUS_SM, height=24,
            command=self._terminal_clear,
        ).pack(side="right", padx=SPACING_XS)

        ctk.CTkButton(
            bar, text="复制全部", font=FONT_CAPTION,
            fg_color="transparent", text_color=COLOR_TEXT_SECONDARY,
            hover_color=COLOR_BTN_HOVER,
            corner_radius=RADIUS_SM, height=24,
            command=self._terminal_copy_all,
        ).pack(side="right", padx=SPACING_XS)

        # 终端本体
        self._terminal = TerminalWidget(
            card,
            output_queue=self._runner.output_queue,
            height=320,
        )
        self._terminal.pack(fill="both", expand=True, padx=SPACING_MD, pady=(SPACING_SM, SPACING_MD))
        self._terminal.start_polling()

    # ============================================================
    # Card 4: 提示
    # ============================================================

    def _build_info_card(self, parent):
        card = ctk.CTkFrame(
            parent, fg_color=COLOR_INFO_BG, corner_radius=RADIUS_LG,
        )
        card.pack(fill="x", pady=(0, SPACING_MD))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=SPACING_LG, pady=SPACING_MD)

        ctk.CTkLabel(
            row, text="ℹ", font=_mk_font(18, "bold"),
            text_color=COLOR_PRIMARY,
        ).pack(side="left", padx=(0, SPACING_MD))

        self._info_label = ctk.CTkLabel(
            row, text="浏览器使用本机 Chrome/Edge/Playwright 路径；Key 创建后保存到配置的目录。",
            font=self._fs, text_color=COLOR_TEXT, wraplength=700, justify="left",
        )
        self._info_label.pack(side="left")

    # ------ 卡片构建辅助 ------

    def _card(self, parent, pad=True, pad_y=SPACING_LG) -> ctk.CTkFrame:
        """创建圆角卡片容器。"""
        card = ctk.CTkFrame(
            parent, fg_color=COLOR_SURFACE, corner_radius=RADIUS_LG,
        )
        card.pack(fill="x", pady=(0, SPACING_LG))
        if pad:
            card._inner = ctk.CTkFrame(card, fg_color="transparent")
            card._inner.pack(fill="x", padx=SPACING_XL, pady=pad_y)
            return card._inner
        return card

    def _card_title(self, card, text: str):
        ctk.CTkLabel(
            card, text=text, font=_mk_font(15, "bold"),
            text_color=COLOR_TEXT,
        ).pack(anchor="w", pady=(0, SPACING_MD))

    def _build_top_actions(self, parent):
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(side="right")
        self._small_action_button(
            actions, "选择浏览器", 88, self._browse_browser_executable,
        ).pack(side="right", padx=(SPACING_XS, 0))
        self._small_action_button(
            actions, "检查配置", 74, self._check_config,
        ).pack(side="right", padx=(SPACING_XS, 0))
        self._small_action_button(
            actions, "保存配置", 74, self._save_config,
        ).pack(side="right", padx=(SPACING_XS, 0))

    def _build_key_actions(self, parent):
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(side="right")
        self._small_action_button(
            actions, "最新 Key", 70, self._open_key_file,
        ).pack(side="right", padx=(SPACING_XS, 0))
        self._small_action_button(
            actions, "打开目录", 74, self._open_dir,
        ).pack(side="right", padx=(SPACING_XS, 0))
        self._small_action_button(
            actions, "选择", 54, self._browse_save_path,
        ).pack(side="right", padx=(SPACING_XS, 0))

    def _small_action_button(self, parent, text: str, width: int, command):
        return ctk.CTkButton(
            parent, text=text, width=width, height=30,
            font=FONT_CAPTION,
            fg_color=COLOR_BTN_SURFACE, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_OUTLINE,
            hover_color=COLOR_BTN_HOVER,
            corner_radius=RADIUS_SM,
            command=command,
        )

    def _load_ai_settings_from_config(self):
        config = ConfigManager.normalize_values(self._cm.read())
        enabled = str(config.get("CAPTCHA_AI_ENABLED", "")).lower() in (
            "1", "true", "yes", "on"
        )
        api_key = config.get("AI_VISION_API_KEY", "")
        api_base = config.get("AI_VISION_API_BASE", "auto")
        model = normalize_ai_model(config.get("AI_VISION_MODEL", ""))

        self._ai_api_base_entry.delete(0, "end")
        self._ai_api_base_entry.insert(0, api_base)
        self._ai_key_entry.delete(0, "end")
        self._ai_key_entry.insert(0, api_key)
        self._ai_model_selector.set(model)

        if enabled:
            self._ai_captcha_switch.select()
            self._ai_settings_frame.pack(fill="x", pady=(SPACING_SM, 0))
            self._detect_backend()
        else:
            self._ai_captcha_switch.deselect()
            self._ai_settings_frame.pack_forget()

    def _load_export_settings_from_config(self):
        config = ConfigManager.normalize_values(self._cm.read())
        key_only = str(config.get("NV_EXPORT_KEY_ONLY", "true")).lower() in (
            "1", "true", "yes", "on"
        )
        acct_full = str(config.get("NV_EXPORT_ACCOUNT_FULL", "false")).lower() in (
            "1", "true", "yes", "on"
        )
        if key_only:
            self._export_key_switch.select()
        else:
            self._export_key_switch.deselect()
        if acct_full:
            self._export_acct_switch.select()
        else:
            self._export_acct_switch.deselect()

    def _get_ai_backend_values(self, config: dict[str, str] | None = None) -> tuple[str, str, str]:
        values = config or self._cm.read()
        api_key = self._ai_key_entry.get().strip() or values.get("AI_VISION_API_KEY", "").strip()
        api_base = self._ai_api_base_entry.get().strip() or values.get("AI_VISION_API_BASE", "auto").strip()
        model = self._ai_model_selector.get().strip() or values.get("AI_VISION_MODEL", "").strip()
        if api_base and api_base.lower() != "auto":
            api_base = normalize_openai_base_url(api_base)
        model = normalize_ai_model(model)
        return api_key, api_base, model

    def _sync_key_scanner(self, config: dict[str, str] | None = None) -> str:
        """Point the shared scanner at the currently configured key directory."""
        values = config if config is not None else self._cm.read()
        keys_dir = resolve_key_scan_dir(
            values.get("NV_KEY_FILE", ""), self._default_keys_dir, self._config_base_dir
        )
        self._ks.keys_dir = keys_dir
        return keys_dir

    def _configured_key_file(self, config: dict[str, str] | None = None) -> str | None:
        values = config if config is not None else self._cm.read()
        target = resolve_key_save_target(
            values.get("NV_KEY_FILE", ""), self._default_keys_dir, self._config_base_dir
        )
        return None if target.is_directory else target.path

    # ============================================================
    # 按钮回调
    # ============================================================

    def _save_config(self):
        config_tab = self._get_config_tab()
        if config_tab:
            ok = config_tab.save_to_env()
        else:
            self._cm.write(self._cm.read())
            ok = True
        if ok:
            self._runner.apply_config(self._cm.read())
        self._update_db_stats()
        self._refresh_duckmail_selector()

    def _check_config(self):
        config_tab = self._get_config_tab()
        if config_tab:
            errors = config_tab.get_validation_errors()
            values = config_tab.get_config_dict()
        else:
            values = self._cm.read()
            errors = self._cm.validate(values)
        if errors:
            msg = "❌ 缺失配置:\n" + "\n".join(f"  • {k}" for k in errors)
            self._terminal.append_text(msg + "\n", "tag_stderr")
        else:
            desensitized = ConfigManager.desensitize(values)
            lines = ["✅ 配置检查通过:\n"]
            for k, v in desensitized.items():
                lines.append(f"  {k} = {v}")
            self._terminal.append_text("\n".join(lines) + "\n", "tag_success")

    def _check_env(self) -> bool:
        self._pm.set_browser_config(self._cm.read())
        status = self._pm.get_detailed_status()
        pw_info = status["playwright"]
        if pw_info["browsers_installed"]:
            return True
        if not pw_info["importable"]:
            self._terminal.append_text(
                "\n[ERROR] Playwright 未安装\n  请运行: pip install playwright\n\n", "tag_stderr")
            return False
        self._terminal.append_text(
            "\n[WARN] 未找到可用浏览器\n"
            f"  {pw_info.get('error') or ''}\n"
            "  可在配置中填写 CHROMIUM_EXECUTABLE_PATH，或点击「选择浏览器」。\n"
            "  源码运行时也可执行: python -m playwright install chromium\n\n",
            "tag_warning",
        )
        dialog = ctk.CTkInputDialog(
            text="未找到浏览器。\n输入 browse 选择 chrome.exe/msedge.exe；源码运行可输入 install 自动安装：",
            title="环境检查 — 浏览器路径")
        answer = dialog.get_input()
        if answer and answer.strip().lower() in ("browse", "b"):
            return self._browse_browser_executable(recheck=True)
        if answer and answer.strip().lower() in ("install", "i"):
            return self._install_browsers()
        self._terminal.append_text("  已取消。可稍后点击「选择浏览器」。\n\n", "tag_warning")
        return False

    def _install_browsers(self) -> bool:
        self._terminal.append_text("  正在安装 Playwright 浏览器...\n", "tag_warning")
        self._update_button_states(running=True)
        def _do_install():
            success = self._pm.install_browsers(
                on_output=lambda text: self._terminal.append_text(text))
            self.after(0, lambda: self._on_install_done(success))
        threading.Thread(target=_do_install, daemon=True).start()
        return False

    def _on_install_done(self, success: bool):
        self._update_button_states(running=False)
        if success:
            self._terminal.append_text("[OK] Playwright 浏览器安装成功！\n\n", "tag_success")
        else:
            self._terminal.append_text("[ERROR] 安装失败，手动: python -m playwright install chromium\n\n", "tag_stderr")
        self._update_env_status()

    def _browse_browser_executable(self, recheck: bool = False) -> bool:
        initial = os.environ.get("PROGRAMFILES", "C:\\")
        path = filedialog.askopenfilename(
            title="选择 Chrome / Edge / Chromium",
            initialdir=initial if os.path.isdir(initial) else "C:\\",
            filetypes=[
                ("Chromium browsers", ("chrome.exe", "msedge.exe", "brave.exe", "chromium.exe")),
                ("Executable", "*.exe"),
                ("All files", "*.*"),
            ],
            parent=self.winfo_toplevel(),
        )
        if not path:
            return False
        values = self._cm.read()
        values["CHROMIUM_EXECUTABLE_PATH"] = path
        self._cm.write(values)
        self._runner.apply_config(values)
        self._pm.set_browser_config(values)
        self._terminal.append_text(f"浏览器路径已保存: {path}\n", "tag_success")
        self._update_env_status()
        return self._check_env() if recheck else True

    def _start_run(self):
        try:
            count = int(self._count_entry.get())
        except ValueError:
            count = 1
        if count < 1:
            self._terminal.append_text("⚠️ 运行轮数需 >= 1，已修正\n", "tag_warning")
            count = 1
            self._count_entry.delete(0, "end")
            self._count_entry.insert(0, "1")
        if not self._check_env():
            return
        config_tab = self._get_config_tab()
        if config_tab:
            config_dict = config_tab.get_config_dict()
        else:
            config_dict = ConfigManager.normalize_values(self._cm.read())

        # ---- 注入 AI 验证码设置到配置 ----
        ai_enabled = self._ai_captcha_switch.get()
        config_dict["CAPTCHA_AI_ENABLED"] = ai_enabled
        if ai_enabled == "true":
            api_key, api_base, model = self._get_ai_backend_values(config_dict)
            config_dict["AI_VISION_API_BASE"] = api_base
            config_dict["AI_VISION_MODEL"] = model
            if api_key:
                config_dict["AI_VISION_API_KEY"] = api_key

        # ---- 注入导出模式设置到配置 ----
        config_dict["NV_EXPORT_KEY_ONLY"] = self._export_key_switch.get()
        config_dict["NV_EXPORT_ACCOUNT_FULL"] = self._export_acct_switch.get()

        errors = self._cm.validate(config_dict)
        if errors:
            self._terminal.append_text(
                "❌ 配置不完整: " + ", ".join(errors) + "\n", "tag_stderr")
            return
        if self._show_config_cb.get() == 1:
            desensitized = ConfigManager.desensitize(config_dict)
            self._terminal.append_text("\n── 运行配置 ──\n")
            for k, v in desensitized.items():
                if v:
                    self._terminal.append_text(f"  {k} = {v}\n")
            self._terminal.append_text("───\n\n")
        if config_dict.get("MAIL_TYPE", "").lower() == "duckmail":
            selected = self._get_selected_duckmail_account()
            if selected:
                self._runner.set_duckmail_account(selected["key"], selected["domain"])
            else:
                self._runner.clear_duckmail_account()
        self._runner.apply_config(config_dict)
        self._terminal.set_output_queue(self._runner.output_queue)
        concurrency = 1
        try:
            concurrency = int(self._concurrency_var.get())
            concurrency = max(1, min(concurrency, 10))
        except ValueError:
            concurrency = 1
        self._runner.start(count, concurrency=concurrency)

    def _stop_run(self):
        self._runner.stop()
        self._terminal.append_text("\n⚠️ 正在停止...\n", "tag_warning")

    def _on_concurrency_changed(self, value: str):
        """并发数变更回调：大于 1 时显示警告。"""
        try:
            conc = int(value)
        except ValueError:
            return
        if conc > 1:
            self._concurrency_warning.configure(
                text=f"将同时打开 {conc} 个浏览器窗口，请确保系统资源充足"
            )
            self._concurrency_warning.pack(fill="x", pady=(SPACING_SM, 0))
        else:
            self._concurrency_warning.pack_forget()

    def _on_ai_captcha_toggled(self):
        """AI 验证码开关切换时显示/隐藏设置行。"""
        value = self._ai_captcha_switch.get()
        if value == "true":
            self._ai_settings_frame.pack(fill="x", pady=(SPACING_SM, 0))
            self._detect_backend()
        else:
            self._ai_settings_frame.pack_forget()
            self._info_label.configure(
                text="浏览器使用本机 Chrome/Edge/Playwright 路径；Key 创建后保存到配置的目录。"
            )

    def _detect_backend(self):
        """检测 AI 后端状态。"""
        import threading
        def _check():
            try:
                api_key, api_base, model = self._get_ai_backend_values()
                if api_base and api_base.lower() != "auto":
                    if api_key:
                        self.after(0, lambda: self._ai_status_label.configure(
                            text=f"✅ UI API configured — {model}", text_color="#1D9E75"))
                        self.after(0, lambda: self._info_label.configure(
                            text="AI enabled. hCaptcha will use the API configured in this UI."
                        ))
                    else:
                        self.after(0, lambda: self._ai_status_label.configure(
                            text="⚠️ API address set, API Key missing", text_color="#EF9F27"))
                    return
                from core.llm_client import LLMClient
                discovered = LLMClient.discover_api_txt()
                if discovered:
                    self.after(0, lambda: self._ai_status_label.configure(
                        text="✅ API.txt detected — ready", text_color="#1D9E75"))
                    self.after(0, lambda: self._info_label.configure(
                        text="AI enabled. hCaptcha will be auto-solved via direct API (qwen3.6-flash)."
                    ))
                else:
                    self.after(0, lambda: self._ai_status_label.configure(
                        text="⚠️ No API.txt found, check config", text_color="#EF9F27"))
            except Exception:
                self.after(0, lambda: self._ai_status_label.configure(
                    text="Checking...", text_color=COLOR_TEXT_SECONDARY))
        threading.Thread(target=_check, daemon=True).start()

    def _test_ai_connection(self):
        """测试 AI LLM API 连通性。"""
        import threading, base64, io
        from PIL import Image

        self._terminal.append_text("Testing LLM API...\n", "tag_info")

        def _do_test():
            try:
                from core.captcha_solver import test_connection
                api_key, api_base, model_name = self._get_ai_backend_values()
                self.after(0, lambda: self._terminal.append_text(
                    f"Backend: {model_name} @ {api_base}\n", "tag_info"))
                result = test_connection(api_key=api_key, base_url=api_base, model=model_name)
                if not result["ok"]:
                    self.after(0, lambda: self._terminal.append_text(
                        f"FAIL: {result['message']}\n\n", "tag_stderr"))
                    return

                ms = result["latency_ms"]
                model = result.get("model", "unknown")
                api_base = result.get("base_url", api_base)
                self.after(0, lambda: self._terminal.append_text(
                    f"OK: {model} ({ms}ms) @ {api_base}\n", "tag_info"))

                # 测试图片识别
                self.after(0, lambda: self._terminal.append_text(
                    "Testing vision...\n", "tag_info"))
                img = Image.new("RGB", (100, 100), color=(255, 80, 80))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                test_b64 = base64.b64encode(buf.getvalue()).decode()

                from core.llm_client import LLMClient
                if not api_key or not api_base or api_base.lower() == "auto":
                    discovered = LLMClient.discover_api_txt()
                    if not discovered:
                        self.after(0, lambda: self._terminal.append_text(
                            "FAIL: no API credentials\n\n", "tag_stderr"))
                        return
                    api_key, api_base = discovered
                client = LLMClient(api_key=api_key, base_url=api_base, model=model)
                reply = client.chat(
                    messages=[{"role": "user", "content": "What is this image? One short sentence."}],
                    image_b64=test_b64,
                    max_tokens=50,
                )
                self.after(0, lambda: self._terminal.append_text(
                    f"Vision test: {reply}\n\n", "tag_info"))
            except Exception as e:
                self.after(0, lambda: self._terminal.append_text(
                    f"FAIL: {e}\n\n", "tag_stderr"))
        threading.Thread(target=_do_test, daemon=True).start()

    def _open_dir(self):
        keys_dir = self._sync_key_scanner()
        os.makedirs(keys_dir, exist_ok=True)
        self._open_path(keys_dir)

    def _open_key_file(self):
        config = self._cm.read()
        self._sync_key_scanner(config)
        configured_file = self._configured_key_file(config)
        if configured_file and os.path.exists(configured_file):
            self._open_path(configured_file)
            return
        latest = self._ks.get_latest_key_file()
        if latest:
            self._open_path(latest)
        else:
            self._terminal.append_text("⚠️ 未找到 Key 文件\n", "tag_warning")

    def _browse_save_path(self):
        """浏览选择 Key 保存目录。"""
        config = self._cm.read()
        initial = resolve_key_scan_dir(
            config.get("NV_KEY_FILE", ""), self._default_keys_dir, self._config_base_dir
        )
        if not os.path.isdir(initial):
            initial = self._default_keys_dir
        directory = filedialog.askdirectory(
            title="选择 Key 保存目录", initialdir=initial,
            parent=self.winfo_toplevel(),
        )
        if directory:
            # 写入 .env
            values = self._cm.read()
            values["NV_KEY_FILE"] = directory
            self._cm.write(values)
            self._runner.apply_config(values)
            self._sync_key_scanner(values)
            self._update_db_stats()
            self._terminal.append_text(f"📁 Key 保存目录已更新: {directory}\n")

    @staticmethod
    def _open_path(path: str):
        if os.sys.platform == "win32":
            os.startfile(path)
        elif os.sys.platform == "darwin":
            import subprocess; subprocess.Popen(["open", path])
        else:
            import subprocess; subprocess.Popen(["xdg-open", path])

    # ============================================================
    # Runner 回调
    # ============================================================

    def _on_progress(self, current: int, total: int, step: str):
        self._progress_label.configure(text=f"运行 {current}/{max(total,1)} — {step}")
        self._update_button_states()

    def _on_complete(self, results: list):
        self._save_terminal_log()
        if not results:
            self._progress_label.configure(text="未执行")
            self._update_button_states()
            return
        success_count = sum(1 for r in results if r.get("success"))
        total_count = len(results)
        self._progress_label.configure(text=f"完成: {success_count}/{total_count}")
        self._terminal.append_text(f"\n{'='*40}\n✅ 完成: {success_count}/{total_count}\n{'='*40}\n")
        self._update_button_states()
        self._update_db_stats()
        if success_count > 0:
            self.after(500, lambda: self._show_result_dialog(results))

    def _on_error(self, error_str: str):
        self._terminal.append_text(f"\n❌ {error_str}\n", "tag_stderr")
        self._update_button_states()

    def _on_state_changed(self):
        self._update_button_states()

    def _save_terminal_log(self):
        try:
            log_content = self._terminal._textbox.get("1.0", "end")
            if log_content.strip():
                self._lm.save_run_log(log_content)
        except Exception:
            pass

    # ============================================================
    # 按钮状态
    # ============================================================

    def _update_button_states(self, running: bool | None = None):
        if running is None:
            running = self._runner.is_running
        self._start_btn.configure(state="disabled" if running else "normal")
        self._stop_btn.configure(state="normal" if running else "disabled")

    # ============================================================
    # 统计 / DuckMail / 剪贴板 / 结果弹窗 / ...
    # ============================================================

    def _update_db_stats(self):
        config = self._cm.read()
        active_key_dir = self._sync_key_scanner(config)
        stats = self._ks.stats()
        mail_type = config.get("MAIL_TYPE", "api").lower()
        domain_count = 0
        if mail_type == "api" and config.get("EMAIL_DOMAIN"):
            domain_count = 1
        elif mail_type == "duckmail":
            if config.get("DUCKMAIL_DOMAIN"):
                domain_count = 1
            accounts = ConfigManager.parse_duckmail_accounts(config.get("DUCKMAIL_ACCOUNTS", ""))
            domain_count += len(accounts)
        elif mail_type == "imap" and config.get("ALIAS_DOMAIN"):
            domain_count = 1
        self._stat_key_num.configure(text=str(stats["total_keys"]))
        self._stat_acct_num.configure(text=str(domain_count))
        self._key_path_label.configure(text=shorten_display_path(active_key_dir))

    def _update_env_status(self):
        self._pm.set_browser_config(self._cm.read())
        self._env_label.configure(text="环境检测中...")

        def _detect():
            text = self._pm.get_status_text()
            try:
                self.after(0, lambda: self._env_label.configure(text=text))
            except RuntimeError:
                pass

        threading.Thread(target=_detect, daemon=True).start()

    def _refresh_duckmail_selector(self):
        config = ConfigManager.normalize_values(self._cm.read())
        mail_type = config.get("MAIL_TYPE", "").lower()
        if mail_type != "duckmail":
            self._duckmail_selector_frame.pack_forget()
            return
        accounts = ConfigManager.parse_duckmail_accounts(config.get("DUCKMAIL_ACCOUNTS", ""))
        prev_domain = getattr(self, '_duckmail_selected_domain', None)
        options = []
        self._duckmail_accounts_cache = []
        default_domain = config.get("DUCKMAIL_DOMAIN", "默认")
        self._duckmail_accounts_cache.append({
            "key": config.get("DUCKMAIL_API_KEY", ""), "domain": default_domain,
        })
        options.append(default_domain)
        for acct in accounts:
            self._duckmail_accounts_cache.append(acct)
            options.append(acct["domain"])
        self._duckmail_selector.configure(values=options)
        if prev_domain and prev_domain in options:
            self._duckmail_selector.set(prev_domain)
        else:
            self._duckmail_selector.set(options[0])
        self._duckmail_selector_frame.pack(
            side="left", padx=(SPACING_LG, 0), before=self._show_config_cb
        )

    def _on_duckmail_changed(self, value: str):
        self._duckmail_selected_domain = value

    def _get_selected_duckmail_account(self) -> dict | None:
        selected = self._duckmail_selector.get()
        if not hasattr(self, '_duckmail_accounts_cache') or not self._duckmail_accounts_cache:
            return None
        self._duckmail_selected_domain = selected
        values = self._duckmail_selector.cget("values")
        for i, v in enumerate(values):
            if v == selected:
                if i == 0:
                    return None
                if i < len(self._duckmail_accounts_cache):
                    return self._duckmail_accounts_cache[i]
        return None

    # ---- 弹窗 ----

    def _show_result_dialog(self, results: list):
        success_results = [r for r in results if r.get("success") and r.get("api_key")]
        if not success_results:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("运行结果")
        dialog.geometry("540x420")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.update_idletasks()
        x = self.winfo_toplevel().winfo_x() + 100
        y = self.winfo_toplevel().winfo_y() + 80
        dialog.geometry(f"+{x}+{y}")
        dialog.resizable(False, False)
        ctk.CTkLabel(
            dialog, text=f"🎉 注册完成: {len(success_results)} 个 Key",
            font=_mk_font(16, "bold"),
        ).pack(pady=(15, 10))
        scroll = ctk.CTkScrollableFrame(dialog, height=200)
        scroll.pack(fill="both", expand=True, padx=20, pady=5)
        for i, r in enumerate(success_results, 1):
            key_text = r.get("api_key", "")
            save_path = r.get("save_path", "")
            account_save_path = r.get("account_save_path", "")
            display_key = key_text[:20] + "..." + key_text[-10:] if len(key_text) > 30 else key_text
            frame = ctk.CTkFrame(scroll, fg_color=COLOR_SURFACE_VARIANT)
            frame.pack(fill="x", pady=3)
            ctk.CTkLabel(frame, text=f"Key #{i}", font=_mk_font(12, "bold")).pack(anchor="w", padx=10, pady=(5, 0))
            kf = ctk.CTkFrame(frame, fg_color="transparent")
            kf.pack(fill="x", padx=10, pady=2)
            ke = ctk.CTkEntry(kf, font=FONT_MONO_BODY, height=28)
            ke.insert(0, display_key)
            ke.configure(state="readonly")
            ke.pack(side="left", fill="x", expand=True, padx=(0, 5))
            ctk.CTkButton(
                kf, text="复制", width=50, height=28, font=FONT_CAPTION,
                command=lambda k=key_text: self._copy_to_clipboard(k),
            ).pack(side="right")
            if save_path:
                ctk.CTkLabel(
                    frame, text=f"📁 {save_path}",
                    font=FONT_CAPTION, text_color=COLOR_TEXT_SECONDARY,
                ).pack(anchor="w", padx=10, pady=(0, 2))
            if account_save_path:
                ctk.CTkLabel(
                    frame, text=f"📋 {account_save_path}",
                    font=FONT_CAPTION, text_color=COLOR_SUCCESS,
                ).pack(anchor="w", padx=10, pady=(0, 5))
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(5, 15))
        ctk.CTkButton(
            btn_frame, text="📂 打开文件夹", font=self._fb,
            command=lambda: self._on_open_result_dir(success_results),
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btn_frame, text="确定", font=self._fb, command=dialog.destroy,
        ).pack(side="right")

    def _on_open_result_dir(self, results: list):
        for r in results:
            save_path = r.get("save_path", "")
            if save_path and os.path.exists(save_path):
                self._open_path(os.path.dirname(save_path))
                return
            elif save_path:
                parent = os.path.dirname(save_path)
                if os.path.exists(parent):
                    self._open_path(parent)
                    return
        self._open_dir()

    @staticmethod
    def _copy_to_clipboard(text: str):
        try:
            import tkinter as tk
            root = tk._default_root
            if root:
                root.clipboard_clear()
                root.clipboard_append(text)
            else:
                r = tk.Tk(); r.withdraw()
                r.clipboard_clear(); r.clipboard_append(text)
                r.update(); r.destroy()
        except Exception:
            pass

    def _terminal_clear(self):
        self._terminal.clear()

    def _terminal_copy_all(self):
        text = self._terminal._textbox.get("1.0", "end-1c")
        self._copy_to_clipboard(text)

    def _get_config_tab(self):
        try:
            app = self.winfo_toplevel()
            if hasattr(app, '_tabs') and 'config' in app._tabs:
                return app._tabs['config']
        except Exception:
            pass
        return None
