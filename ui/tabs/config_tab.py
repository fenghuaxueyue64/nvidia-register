"""配置标签页 — .env 配置文件的表单编辑器。"""

import os
import customtkinter as ctk
from core.config_manager import ConfigManager, ENV_FIELDS, FieldDef


class ConfigTab(ctk.CTkFrame):
    """.env 配置表单编辑器，支持按 MAIL_TYPE 动态显示/隐藏字段。"""

    def __init__(self, master, config_manager: ConfigManager,
                 font_title=None, font_body=None, font_small=None, **kwargs):
        super().__init__(master, **kwargs)
        self._cm = config_manager
        self._font_title = font_title or ctk.CTkFont(family="Roboto", size=20, weight="bold")
        self._font_body = font_body or ctk.CTkFont(family="Roboto", size=13)
        self._font_small = font_small or ctk.CTkFont(family="Roboto", size=11)

        self._entries: dict[str, ctk.CTkEntry | ctk.CTkOptionMenu] = {}
        self._sections: dict[str, ctk.CTkFrame] = {}

        self._build_ui()
        self.load_from_env()

    def _build_ui(self):
        """构建表单 UI。"""
        # 滚动容器
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # 标题
        ctk.CTkLabel(
            scroll, text="配置",
            font=self._font_title,
            anchor="w",
        ).pack(fill="x", pady=(5, 15))

        # 各分区
        section_labels = {
            "common": "通用配置",
            "api": "API 模式配置",
            "duckmail": "DuckMail 模式配置",
            "imap": "IMAP 模式配置",
            "optional": "可选配置",
            "network": "网络代理 (可选)",
            "ai_captcha": "🤖 AI 验证码 (可选)",
        }

        for section_name, fields in ENV_FIELDS.items():
            frame = ctk.CTkFrame(scroll, fg_color="transparent")
            self._sections[section_name] = frame

            # 分区标题
            section_text = section_labels.get(section_name, section_name)
            ctk.CTkLabel(
                frame, text=section_text,
                font=ctk.CTkFont(family="Roboto", size=14, weight="bold"),
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(10, 5))

            # 分隔线
            ctk.CTkFrame(
                frame, height=1,
                fg_color=("gray80", "gray30"),
            ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 5))

            # 字段行
            for row_offset, field_def in enumerate(fields, start=2):
                self._build_field_row(frame, field_def, row_offset)

            frame.columnconfigure(1, weight=1)
            frame.pack(fill="x", pady=5)

        # 管理所有分区在滚动容器中的 pack 顺序
        self._scroll = scroll

        # 初始显示/隐藏模式分区
        self._update_section_visibility()

        # 保存按钮区（在 _update_section_visibility 之后 pack，确保在最底部）
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._btn_frame = btn_frame

        self._save_btn = ctk.CTkButton(
            btn_frame, text="💾 保存配置", font=self._font_body,
            command=self._save_config,
        )
        self._save_btn.pack(side="left", padx=(0, 10))

        self._reload_btn = ctk.CTkButton(
            btn_frame, text="🔄 重新加载", font=self._font_body,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=self.load_from_env,
        )
        self._reload_btn.pack(side="left")

        # 保存结果标签
        self._save_result = ctk.CTkLabel(
            btn_frame, text="", font=self._font_small,
            text_color=("green", "#2ecc71"),
        )
        self._save_result.pack(side="left", padx=15)

    def _build_field_row(self, parent: ctk.CTkFrame, field_def: FieldDef, row: int):
        """构建单行字段。"""
        # 标签
        label_text = field_def.label
        if field_def.required:
            label_text += " *"
        desc = field_def.description or ""

        label = ctk.CTkLabel(
            parent, text=label_text,
            font=self._font_body,
            anchor="w",
        )
        label.grid(row=row, column=0, padx=(5, 15), pady=3, sticky="w")

        # 描述提示
        if desc:
            label.configure(text=f"{label_text}  ({desc})")

        # 输入控件
        if field_def.type == "optionmenu":
            widget = ctk.CTkOptionMenu(
                parent, values=field_def.options,
                font=self._font_body,
                command=self._on_mail_type_changed if field_def.key == "MAIL_TYPE" else None,
            )
        else:
            show = "*" if field_def.secret else ""
            placeholder = field_def.default if field_def.default else ""
            widget = ctk.CTkEntry(
                parent, show=show,
                placeholder_text=placeholder,
                font=self._font_body,
            )

        widget.grid(row=row, column=1, padx=5, pady=3, sticky="ew")
        self._entries[field_def.key] = widget

    # ------ 动态字段可见性 ------

    def _on_mail_type_changed(self, value: str):
        """MAIL_TYPE 改变时，显示/隐藏对应分区。"""
        self._update_section_visibility()

    def _update_section_visibility(self):
        """根据当前 MAIL_TYPE 显示/隐藏分区，并重新 pack 保证顺序。"""
        # 获取当前选中的 MAIL_TYPE
        mail_type_widget = self._entries.get("MAIL_TYPE")
        if isinstance(mail_type_widget, ctk.CTkOptionMenu):
            current_type = mail_type_widget.get()
        else:
            current_type = "api"

        # 决定哪些分区可见（保持顺序：common → mode → network → ai_captcha → optional → btn）
        visible_sections = ["common", current_type, "network", "ai_captcha", "optional"]

        # 先 forget 所有分区和按钮区
        for section_name in ("common", "api", "duckmail", "imap", "network", "ai_captcha", "optional"):
            frame = self._sections.get(section_name)
            if frame:
                frame.pack_forget()
        if hasattr(self, '_btn_frame'):
            self._btn_frame.pack_forget()

        # 按 visible_sections 顺序重新 pack
        for section_name in visible_sections:
            frame = self._sections.get(section_name)
            if frame:
                frame.pack(fill="x", pady=5, in_=self._scroll)

        # 重新 pack 保存按钮区
        if hasattr(self, '_btn_frame'):
            self._btn_frame.pack(fill="x", pady=(15, 5), in_=self._scroll)

    # ------ 数据加载/保存 ------

    def load_from_env(self):
        """从 .env 文件加载配置到表单。"""
        values = self._cm.read()
        for key, widget in self._entries.items():
            val = values.get(key, "")
            if isinstance(widget, ctk.CTkOptionMenu):
                widget.set(val or ConfigManager.default_value(key))
            else:
                widget.delete(0, "end")
                widget.insert(0, val)
        self._update_section_visibility()

    def save_to_env(self) -> bool:
        """将表单值保存到 .env 文件。返回是否成功。"""
        values = self._get_form_values()
        try:
            self._cm.write(values)
            self._save_result.configure(text="✅ 已保存")
            # 3秒后清除提示
            self.after(3000, lambda: self._save_result.configure(text=""))
            return True
        except Exception as e:
            self._save_result.configure(text=f"❌ 保存失败: {e}")
            return False

    def _save_config(self):
        """保存按钮回调。"""
        self.save_to_env()

    def _get_form_values(self) -> dict[str, str]:
        """从表单获取所有字段值。"""
        values = {}
        for key, widget in self._entries.items():
            if isinstance(widget, ctk.CTkOptionMenu):
                values[key] = widget.get()
            else:
                values[key] = widget.get()
        return values

    def get_config_dict(self) -> dict[str, str]:
        """获取当前表单的配置值（供外部调用）。"""
        return ConfigManager.normalize_values(self._get_form_values())

    def get_validation_errors(self) -> list[str]:
        """验证当前表单配置，返回缺失字段列表。"""
        values = self.get_config_dict()
        return self._cm.validate(values)
