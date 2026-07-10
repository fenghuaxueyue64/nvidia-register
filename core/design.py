"""Material 3 Design System tokens — Google 风格统一设计语言。"""

# ============================================================
# 颜色 — Material 3 Token / 深色模式用 on-surface 半透明体系
# ============================================================
# (浅色, 深色)
COLOR_PRIMARY = ("#2F6FB7", "#8AB4F8")           # Muted operational blue
COLOR_ON_PRIMARY = ("#FFFFFF", "#003D8B")
COLOR_DANGER = ("#D93025", "#F28B82")            # Destructive red
COLOR_ERROR = COLOR_DANGER                         # Alias
COLOR_SUCCESS = ("#1E8E3E", "#81C995")           # Success green

COLOR_BG = ("#EEF2F6", "#0F0F10")                # Page background
COLOR_SURFACE = ("#F7F9FC", "#1C1C1F")           # Card surface
COLOR_SURFACE_VARIANT = ("#E8EDF3", "#232327")   # Sidebar / elevated surface
COLOR_OUTLINE = ("#CBD3DC", "#3C4043")             # Borders / dividers
# 文字 — 深色模式用高亮度灰阶（对应 Material on-surface 半透明）
COLOR_TEXT = ("#202124", "#E8EAED")                 # 主文字 (~92% opacity)
COLOR_TEXT_SECONDARY = ("#5F6368", "#A8ACB2")        # 次文字 (~65% opacity)
COLOR_TEXT_DISABLED = ("#80868B", "#5F6368")         # 禁用文字 (~38% opacity)

COLOR_TERMINAL_BG = ("#E9EEF4", "#0D1117")           # Terminal 背景
COLOR_ACTIVE_INDICATOR = ("#1A73E8", "#8AB4F8")      # Sidebar 高亮条
COLOR_INFO_BG = ("#E1EAF5", "#1A2844")               # 提示卡片

# 深色模式按钮 — 半透明表面色近似
COLOR_BTN_HOVER = ("#DDE5EE", "#35353A")             # hover 态 (~12% opacity)
COLOR_BTN_SURFACE = ("#EDF2F7", "#27272C")           # 填充表面 (~8% opacity)

# ============================================================
# 间距 — 8px 网格
# ============================================================
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24
SPACING_2XL = 32

# ============================================================
# 圆角
# ============================================================
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 8
RADIUS_FULL = 999

# ============================================================
# 字体
# ============================================================
FONT_FAMILY = "Segoe UI Variable"
FONT_MONO = "Cascadia Code"

FONT_H1 = (FONT_FAMILY, 28, "bold")
FONT_H2 = (FONT_FAMILY, 18, "bold")
FONT_H3 = (FONT_FAMILY, 15, "bold")
FONT_BODY = (FONT_FAMILY, 14)
FONT_BODY_SMALL = (FONT_FAMILY, 12)
FONT_CAPTION = (FONT_FAMILY, 11)
FONT_STAT = (FONT_FAMILY, 32, "bold")
FONT_MONO_BODY = (FONT_MONO, 13)
