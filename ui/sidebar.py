"""侧边栏 — Material 3 导航组件。"""

import os
import customtkinter as ctk
from PIL import Image
from core.runtime_paths import resource_path
from core.design import (
    COLOR_SURFACE_VARIANT, COLOR_OUTLINE, COLOR_TEXT,
    COLOR_TEXT_SECONDARY, COLOR_ACTIVE_INDICATOR, COLOR_PRIMARY,
    COLOR_BTN_HOVER,
    SPACING_SM, SPACING_MD, SPACING_LG, SPACING_XL,
    RADIUS_MD, RADIUS_FULL,
)

TAB_ICONS = ["▶", "⚙", "🔑", "🌐", "📋", "🧪"]
TAB_NAMES = ["运行", "配置", "Key 数据库", "域名数据库", "日志", "模型测试"]
TAB_KEYS  = ["run", "config", "key_db", "domain_db", "log", "model_test"]
THEMES = ["system", "light", "dark"]
THEME_LABELS = ["跟随系统", "浅色", "深色"]


class Sidebar(ctk.CTkFrame):
    """Material 3 左侧导航栏。"""

    def __init__(self, master, on_tab_selected=None, on_theme_changed=None, **kwargs):
        super().__init__(
            master, width=220, corner_radius=0,
            fg_color=COLOR_SURFACE_VARIANT, **kwargs,
        )
        self.pack_propagate(False)
        self._on_tab_selected = on_tab_selected
        self._on_theme_changed = on_theme_changed
        self._buttons: list[ctk.CTkFrame] = []
        self._active_index = 0
        self._brand_icon = None

        self._build_header()
        self._build_nav()
        self._build_footer()

    def _build_header(self):
        """品牌区 — logo + 标题。"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=SPACING_LG, pady=(SPACING_XL, SPACING_SM))

        brand_icon = self._load_brand_icon()
        if brand_icon:
            ctk.CTkLabel(header, text="", image=brand_icon, width=28).pack(
                side="left", padx=(0, SPACING_SM)
            )
        else:
            ctk.CTkLabel(
                header, text="●", font=ctk.CTkFont(size=18),
                text_color=("#76B900", "#76B900"),
            ).pack(side="left", padx=(0, SPACING_SM))

        ctk.CTkLabel(
            header, text="NVIDIARegister",
            font=ctk.CTkFont(family="Segoe UI Variable", size=16, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            self, text="Control Panel",
            font=ctk.CTkFont(family="Segoe UI Variable", size=11),
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(pady=(0, SPACING_LG), padx=SPACING_LG + 26, anchor="w")

        # 分组标题 — 导航
        ctk.CTkLabel(
            self, text="导航",
            font=ctk.CTkFont(family="Segoe UI Variable", size=10, weight="bold"),
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(anchor="w", padx=SPACING_LG, pady=(0, SPACING_SM))

    def _build_nav(self):
        """导航按钮 — 选中项左侧高亮条 + 圆角背景。"""
        for i in range(len(TAB_NAMES)):
            icon = TAB_ICONS[i]
            name = TAB_NAMES[i]
            is_active = (i == self._active_index)

            # 按钮容器（含高亮条 + 按钮）
            row = ctk.CTkFrame(self, fg_color="transparent", height=40)
            row.pack(fill="x", padx=SPACING_SM, pady=1)
            row.pack_propagate(False)

            # 左侧高亮指示条
            bar_w = 3 if is_active else 0
            bar = ctk.CTkFrame(
                row, width=bar_w, corner_radius=RADIUS_FULL,
                fg_color=COLOR_ACTIVE_INDICATOR if is_active else "transparent",
            )
            bar.pack(side="left", fill="y", padx=(0, 0))
            self._register_bar(i, bar)

            # 按钮本体
            btn = ctk.CTkButton(
                row,
                text=f"  {icon}  {name}",
                anchor="w",
                font=ctk.CTkFont(family="Segoe UI Variable", size=14),
                fg_color=COLOR_PRIMARY if is_active else "transparent",
                text_color=("#FFFFFF", "#003D8B") if is_active else COLOR_TEXT,
                hover_color=COLOR_BTN_HOVER if not is_active else COLOR_PRIMARY,
                corner_radius=RADIUS_MD,
                height=36,
                command=lambda idx=i: self._select(idx),
            )
            btn.pack(side="left", fill="both", expand=True, padx=(SPACING_SM, 0))
            self._buttons.append(btn)

    def _load_brand_icon(self):
        icon_path = resource_path(os.path.join("icon", "app-icon.png"))
        if not os.path.exists(icon_path):
            return None
        try:
            image = Image.open(icon_path)
            self._brand_icon = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=(24, 24),
            )
            return self._brand_icon
        except Exception:
            return None

    def _build_footer(self):
        """底部 — 主题切换 + 版本号。"""
        # 弹性占位
        ctk.CTkFrame(self, height=0, fg_color="transparent").pack(fill="both", expand=True)

        # 分隔线
        ctk.CTkFrame(self, height=1, fg_color=COLOR_OUTLINE).pack(
            fill="x", padx=SPACING_LG, pady=(0, SPACING_SM))

        # 主题标签
        ctk.CTkLabel(
            self, text="主题",
            font=ctk.CTkFont(family="Segoe UI Variable", size=10),
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(anchor="w", padx=SPACING_LG, pady=(0, 2))

        # 主题选择器
        self._theme_selector = ctk.CTkOptionMenu(
            self,
            values=THEME_LABELS,
            font=ctk.CTkFont(family="Segoe UI Variable", size=11),
            height=30, corner_radius=RADIUS_MD,
            command=self._on_theme_select,
        )
        self._theme_selector.pack(fill="x", padx=SPACING_LG, pady=(0, SPACING_MD))
        self._theme_selector.set(THEME_LABELS[0])

        # 版本
        ctk.CTkLabel(
            self, text="v1.0",
            font=ctk.CTkFont(family="Segoe UI Variable", size=10),
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(anchor="w", padx=SPACING_LG, pady=(0, SPACING_MD))

    # ------ 选择切换 ------

    def _select(self, index: int):
        """切换激活标签 — 按钮颜色 + 高亮条。"""
        self._active_index = index
        for i, btn in enumerate(self._buttons):
            active = (i == index)
            btn.configure(
                fg_color=COLOR_PRIMARY if active else "transparent",
                text_color=("#FFFFFF", "#003D8B") if active else COLOR_TEXT,
                hover_color=("#E8F0FE", "#2D2D2D") if not active else COLOR_PRIMARY,
            )
            # 高亮条
            if hasattr(self, f'_bar_{i}'):
                bar: ctk.CTkFrame = getattr(self, f'_bar_{i}')
                bar.configure(
                    width=3 if active else 0,
                    fg_color=COLOR_ACTIVE_INDICATOR if active else "transparent",
                )
        if self._on_tab_selected:
            self._on_tab_selected(TAB_KEYS[index])

    def _register_bar(self, index: int, bar: ctk.CTkFrame):
        """注册高亮条引用。"""
        setattr(self, f'_bar_{index}', bar)

    # ------ 主题 ------

    def _on_theme_select(self, label: str):
        try:
            idx = THEME_LABELS.index(label)
            if self._on_theme_changed:
                self._on_theme_changed(THEMES[idx])
        except ValueError:
            pass

    def set_theme(self, theme: str):
        try:
            idx = THEMES.index(theme)
            self._theme_selector.set(THEME_LABELS[idx])
        except ValueError:
            pass

    def select_tab(self, tab_key: str):
        if tab_key in TAB_KEYS:
            self._select(TAB_KEYS.index(tab_key))
