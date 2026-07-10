"""域名数据库标签页 — 展示当前配置中的域名信息。"""

import os
import customtkinter as ctk
from core.config_manager import ConfigManager


class DomainDBTab(ctk.CTkFrame):
    """域名数据库标签页：展示配置中的邮箱域名。"""

    def __init__(self, master, config_manager: ConfigManager,
                 font_title=None, font_body=None, font_small=None, **kwargs):
        super().__init__(master, **kwargs)
        self._cm = config_manager
        self._font_title = font_title or ctk.CTkFont(family="Segoe UI Variable", size=22, weight="bold")
        self._font_body = font_body or ctk.CTkFont(family="Segoe UI Variable", size=14)
        self._font_small = font_small or ctk.CTkFont(family="Segoe UI Variable", size=12)

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        """构建域名数据库标签页 UI。"""
        # ===== 顶部 =====
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(10, 5))

        ctk.CTkLabel(
            header, text="域名数据库",
            font=self._font_title, anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            header, text="🔄 刷新", font=self._font_small,
            width=70, height=28,
            command=self.refresh,
        ).pack(side="right")

        self._stats_label = ctk.CTkLabel(
            header, text="启用域名: 0",
            font=self._font_body,
            text_color=("gray40", "gray60"),
        )
        self._stats_label.pack(side="right", padx=(0, 15))

        # 分隔线
        ctk.CTkFrame(
            self, height=1, fg_color=("gray80", "gray30"),
        ).pack(fill="x", padx=15, pady=(0, 5))

        # ===== 表头 =====
        col_header = ctk.CTkFrame(self, fg_color=("gray90", "gray20"))
        col_header.pack(fill="x", padx=15, pady=(0, 2))

        for text, width in [("域名", 300), ("提供商", 100), ("状态", 80), ("来源字段", 200)]:
            ctk.CTkLabel(
                col_header, text=text,
                font=ctk.CTkFont(family="Segoe UI Variable", size=12, weight="bold"),
                width=width, anchor="w",
            ).pack(side="left", padx=8, pady=4)

        # ===== 表格区域 =====
        self._table_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._table_scroll.pack(fill="both", expand=True, padx=15, pady=5)

    def refresh(self):
        """刷新域名列表。"""
        # 清空
        for widget in self._table_scroll.winfo_children():
            widget.destroy()

        config = self._cm.read()
        mail_type = config.get("MAIL_TYPE", "api").lower()
        domains: list[dict] = []

        # 根据模式提取域名
        if mail_type == "api":
            domain = config.get("EMAIL_DOMAIN", "")
            if domain:
                domains.append({
                    "domain": domain,
                    "provider": "Legacy API",
                    "status": "✅ 启用",
                    "source": "EMAIL_DOMAIN",
                })
        elif mail_type == "duckmail":
            domain = config.get("DUCKMAIL_DOMAIN", "")
            if domain:
                domains.append({
                    "domain": domain,
                    "provider": "DuckMail",
                    "status": "✅ 启用",
                    "source": "DUCKMAIL_DOMAIN",
                })
            # 多账户
            accounts = ConfigManager.parse_duckmail_accounts(
                config.get("DUCKMAIL_ACCOUNTS", ""))
            for acct in accounts:
                domains.append({
                    "domain": acct["domain"],
                    "provider": f"DuckMail",
                    "status": "✅ 可用",
                    "source": "DUCKMAIL_ACCOUNTS",
                })
        elif mail_type == "imap":
            alias_domain = config.get("ALIAS_DOMAIN", "duck.com")
            domains.append({
                "domain": f"@{alias_domain}",
                "provider": "DDG + IMAP",
                "status": "✅ 启用",
                "source": "ALIAS_DOMAIN",
            })
            # 也显示 IMAP 服务器
            imap_host = config.get("IMAP_HOST", "")
            if imap_host:
                domains.append({
                    "domain": imap_host,
                    "provider": "IMAP 服务器",
                    "status": "✅ 连接",
                    "source": "IMAP_HOST",
                })

        # 更新统计
        self._stats_label.configure(text=f"启用域名: {len(domains)}")

        if not domains:
            ctk.CTkLabel(
                self._table_scroll,
                text="暂无域名配置",
                font=self._font_body,
                text_color=("gray50", "gray60"),
            ).pack(pady=30)
            return

        # 添加行
        for d in domains:
            row = ctk.CTkFrame(self._table_scroll, fg_color="transparent", height=32)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(
                row, text=d["domain"],
                font=ctk.CTkFont(family="Consolas", size=12),
                width=300, anchor="w",
            ).pack(side="left", padx=8)

            ctk.CTkLabel(
                row, text=d["provider"],
                font=self._font_small, width=100, anchor="w",
            ).pack(side="left", padx=8)

            # 状态着色
            status_color = ("green", "#2ecc71") if "✅" in d["status"] else ("gray40", "gray60")
            ctk.CTkLabel(
                row, text=d["status"],
                font=self._font_small, width=80, anchor="w",
                text_color=status_color,
            ).pack(side="left", padx=8)

            ctk.CTkLabel(
                row, text=d["source"],
                font=ctk.CTkFont(family="Consolas", size=11),
                width=200, anchor="w",
            ).pack(side="left", padx=8)
