"""模型测试面板 — 测试多模态 LLM 的图片理解能力。"""

import base64
import io
import os
import threading

import customtkinter as ctk
from PIL import Image as PILImage
from tkinter import filedialog

from core.ai_config import AI_MODEL_OPTIONS, DEFAULT_AI_MODEL, mask_secret, normalize_ai_model
from core.config_manager import ConfigManager
from core.llm_client import LLMClient
from core.design import (
    COLOR_BG, COLOR_SURFACE, COLOR_SURFACE_VARIANT, COLOR_OUTLINE,
    COLOR_TEXT, COLOR_TEXT_SECONDARY, COLOR_PRIMARY, COLOR_ERROR,
    SPACING_SM, SPACING_MD, SPACING_LG, SPACING_XL,
    RADIUS_MD, FONT_CAPTION,
)


MODELS = AI_MODEL_OPTIONS

IMG_MAX_SIZE = 800   # 图片预览最大边长
IMG_MAX_BYTES = 10 * 1024 * 1024  # 10MB


class ModelTestTab(ctk.CTkFrame):
    """模型测试面板。"""

    def __init__(self, master, config_manager: ConfigManager | None = None, **kwargs):
        super().__init__(master, fg_color=COLOR_BG, corner_radius=0, **kwargs)

        self._image_b64: str | None = None
        self._image_path: str | None = None
        self._sending = False
        self._cm = config_manager

        self._build_ui()
        self._load_credentials()

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_ui(self):
        """双栏布局：左-输入区，右-响应区。"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # ---- 顶栏：标题 + 模型选择 + 测试按钮 ----
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=3, sticky="ew", padx=SPACING_LG, pady=(SPACING_LG, SPACING_SM))

        ctk.CTkLabel(
            top, text="Model Test",
            font=ctk.CTkFont(family="Segoe UI Variable", size=18, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")

        self._status_label = ctk.CTkLabel(
            top, text="", font=FONT_CAPTION, text_color=COLOR_TEXT_SECONDARY,
        )
        self._status_label.pack(side="left", padx=(SPACING_LG, SPACING_SM))

        ctk.CTkLabel(top, text="Model:", text_color=COLOR_TEXT_SECONDARY,
                     font=FONT_CAPTION).pack(side="left", padx=(SPACING_XL, SPACING_SM))
        self._model_selector = ctk.CTkOptionMenu(
            top, values=MODELS, font=FONT_CAPTION, width=200, height=28,
            corner_radius=RADIUS_MD,
        )
        self._model_selector.set(DEFAULT_AI_MODEL)
        self._model_selector.pack(side="left", padx=(0, SPACING_SM))

        self._test_btn = ctk.CTkButton(
            top, text="Test Connection", font=FONT_CAPTION, width=100, height=28,
            corner_radius=RADIUS_MD, command=self._test_connection,
        )
        self._test_btn.pack(side="left", padx=(0, SPACING_SM))

        # ---- 左栏：图片 + 提示词 ----
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", padx=(SPACING_LG, SPACING_SM), pady=(0, SPACING_LG))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=0)
        left.grid_rowconfigure(1, weight=1)

        # 图片区域
        img_label = ctk.CTkLabel(
            left, text="Image",
            font=ctk.CTkFont(family="Segoe UI Variable", size=12, weight="bold"),
            text_color=COLOR_TEXT,
        )
        img_label.grid(row=0, column=0, sticky="w", pady=(0, SPACING_SM))

        self._img_frame = ctk.CTkFrame(left, fg_color=COLOR_SURFACE_VARIANT, corner_radius=RADIUS_MD)
        self._img_frame.grid(row=1, column=0, sticky="nsew")
        self._img_frame.grid_rowconfigure(0, weight=1)
        self._img_frame.grid_columnconfigure(0, weight=1)

        # 空状态占位
        self._img_placeholder = ctk.CTkLabel(
            self._img_frame,
            text="Drop image here\nor click to browse\n\nJPEG / PNG / WebP\nMax 10MB",
            font=ctk.CTkFont(family="Segoe UI Variable", size=14),
            text_color=COLOR_TEXT_SECONDARY,
            justify="center",
        )
        self._img_placeholder.grid(row=0, column=0)

        self._img_preview = ctk.CTkLabel(self._img_frame, text="")

        # 绑定点击事件
        self._img_frame.bind("<Button-1>", lambda e: self._pick_image())
        self._img_placeholder.bind("<Button-1>", lambda e: self._pick_image())

        # 按钮行
        img_btns = ctk.CTkFrame(left, fg_color="transparent")
        img_btns.grid(row=2, column=0, sticky="ew", pady=(SPACING_SM, 0))
        ctk.CTkButton(
            img_btns, text="Browse...", font=FONT_CAPTION,
            width=80, height=28, corner_radius=RADIUS_MD,
            command=self._pick_image,
        ).pack(side="left")
        ctk.CTkButton(
            img_btns, text="Clear", font=FONT_CAPTION,
            width=60, height=28, corner_radius=RADIUS_MD,
            fg_color="transparent", border_width=1, border_color=COLOR_OUTLINE,
            text_color=COLOR_TEXT_SECONDARY,
            command=self._clear_image,
        ).pack(side="left", padx=(SPACING_SM, 0))

        # ---- 分隔线 ----
        sep = ctk.CTkFrame(self, width=1, fg_color=COLOR_OUTLINE)
        sep.grid(row=1, column=1, sticky="ns", padx=SPACING_MD, pady=(0, SPACING_LG))

        # ---- 右栏：提示词 + 发送 + 响应 ----
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=2, sticky="nsew", padx=(SPACING_SM, SPACING_LG), pady=(0, SPACING_LG))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=0)
        right.grid_rowconfigure(3, weight=0)

        # 提示词标签
        ctk.CTkLabel(
            right, text="Prompt",
            font=ctk.CTkFont(family="Segoe UI Variable", size=12, weight="bold"),
            text_color=COLOR_TEXT,
        ).grid(row=0, column=0, sticky="w", pady=(0, SPACING_SM))

        # 提示词输入
        self._prompt_input = ctk.CTkTextbox(
            right, font=ctk.CTkFont(family="Segoe UI Variable", size=14),
            corner_radius=RADIUS_MD, height=100,
            wrap="word",
        )
        self._prompt_input.grid(row=1, column=0, sticky="ew", pady=(0, 0))
        self._prompt_input.insert("1.0", "What is in this image? Describe it in detail.")

        # 响应标签
        ctk.CTkLabel(
            right, text="Response",
            font=ctk.CTkFont(family="Segoe UI Variable", size=12, weight="bold"),
            text_color=COLOR_TEXT,
        ).grid(row=2, column=0, sticky="w", pady=(SPACING_MD, SPACING_SM))

        # 响应区域
        self._response_box = ctk.CTkTextbox(
            right, font=ctk.CTkFont(family="Segoe UI Variable", size=14),
            corner_radius=RADIUS_MD, state="disabled",
            wrap="word",
        )
        self._response_box.grid(row=3, column=0, sticky="nsew")

        # 发送按钮
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.grid(row=4, column=0, sticky="ew", pady=(SPACING_MD, 0))
        self._send_btn = ctk.CTkButton(
            btn_row, text="Send",
            font=ctk.CTkFont(family="Segoe UI Variable", size=13, weight="bold"),
            width=80, height=32, corner_radius=RADIUS_MD,
            command=self._send,
        )
        self._send_btn.pack(side="right")

        self._loading_label = ctk.CTkLabel(
            btn_row, text="", text_color=COLOR_TEXT_SECONDARY, font=FONT_CAPTION,
        )
        self._loading_label.pack(side="right", padx=(0, SPACING_MD))

    # ================================================================
    # 凭证加载
    # ================================================================

    def _load_credentials(self):
        config = ConfigManager.normalize_values(self._cm.read()) if self._cm else {}
        config_key = config.get("AI_VISION_API_KEY", "").strip()
        config_base = config.get("AI_VISION_API_BASE", "").strip()
        config_model = normalize_ai_model(config.get("AI_VISION_MODEL", ""))

        if config_model:
            self._model_selector.set(config_model)

        if config_key and config_base and config_base.lower() != "auto":
            self._api_key = config_key
            self._base_url = config_base
            self._status_label.configure(
                text=f".env API | key: {mask_secret(config_key)}"
            )
            return

        discovered = LLMClient.discover_api_txt()
        if discovered:
            api_key, base_url = discovered
            self._api_key = api_key
            self._base_url = base_url
            self._status_label.configure(text=f"API.txt found | key: {mask_secret(api_key)}")
        else:
            self._api_key = ""
            self._base_url = ""
            self._status_label.configure(
                text="No .env AI config or API.txt found", text_color=COLOR_ERROR
            )

    # ================================================================
    # 图片操作
    # ================================================================

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="Choose an image",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._load_image(path)

    def _load_image(self, path: str):
        try:
            fsize = os.path.getsize(path)
            if fsize > IMG_MAX_BYTES:
                self._set_status("Image too large (>10MB)", COLOR_ERROR)
                return

            img = PILImage.open(path)
            img = img.convert("RGB")

            # 编码为 PNG base64
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self._image_b64 = base64.b64encode(buf.getvalue()).decode()
            self._image_path = path

            # 创建预览缩略图
            img.thumbnail((IMG_MAX_SIZE, IMG_MAX_SIZE), PILImage.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)

            self._img_placeholder.grid_remove()
            self._img_preview.configure(image=ctk_img, text="")
            self._img_preview.image = ctk_img  # 保持引用
            self._img_preview.grid(row=0, column=0)

            fname = os.path.basename(path)
            self._set_status(f"Loaded: {fname} ({img.size[0]}x{img.size[1]})")
        except Exception as e:
            self._set_status(f"Failed to load image: {e}", COLOR_ERROR)

    def _clear_image(self):
        self._image_b64 = None
        self._image_path = None
        self._img_preview.grid_remove()
        self._img_placeholder.grid(row=0, column=0)
        self._set_status("Image cleared")

    # ================================================================
    # 发送 & 测试
    # ================================================================

    def _send(self):
        if self._sending:
            return
        if not self._api_key or not self._base_url:
            self._set_status("No API credentials. Place API.txt or configure .env", COLOR_ERROR)
            return

        prompt = self._prompt_input.get("1.0", "end").strip()
        if not prompt:
            self._set_status("Please enter a prompt", COLOR_ERROR)
            return

        self._sending = True
        self._send_btn.configure(state="disabled", text="Sending...")
        self._loading_label.configure(text="Thinking...")
        self._set_response("")

        model = self._model_selector.get()

        def _do_send():
            try:
                client = LLMClient(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    model=model,
                )
                msgs = [{"role": "user", "content": prompt}]
                result = client.chat(
                    messages=msgs,
                    image_b64=self._image_b64,
                    max_tokens=1024,
                )
                self.after(0, lambda: self._set_response(result))
                self.after(0, lambda: self._set_status("Done"))
            except Exception as e:
                self.after(0, lambda: self._set_response(f"ERROR: {e}"))
                self.after(0, lambda: self._set_status(f"Failed: {e}", COLOR_ERROR))
            finally:
                self.after(0, lambda: self._send_btn.configure(state="normal", text="Send"))
                self.after(0, lambda: self._loading_label.configure(text=""))
                self.after(0, setattr, self, '_sending', False)

        threading.Thread(target=_do_send, daemon=True).start()

    def _test_connection(self):
        if not self._api_key or not self._base_url:
            self._set_status("No credentials", COLOR_ERROR)
            return

        model = self._model_selector.get()
        self._test_btn.configure(state="disabled", text="Testing...")

        def _do_test():
            try:
                import time
                t0 = time.time()
                client = LLMClient(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    model=model,
                )
                result = client.test_connectivity()
                ms = int((time.time() - t0) * 1000)
                if result["ok"]:
                    self.after(0, lambda: self._set_status(
                        f"Connected! {result.get('model', model)} ({ms}ms)", "#1D9E75"))
                else:
                    self.after(0, lambda: self._set_status(
                        f"Failed: {result['message']}", COLOR_ERROR))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"Error: {e}", COLOR_ERROR))
            finally:
                self.after(0, lambda: self._test_btn.configure(state="normal", text="Test Connection"))

        threading.Thread(target=_do_test, daemon=True).start()

    # ================================================================
    # 工具方法
    # ================================================================

    def _set_response(self, text: str):
        self._response_box.configure(state="normal")
        self._response_box.delete("1.0", "end")
        self._response_box.insert("1.0", text)
        self._response_box.configure(state="disabled")

    def _set_status(self, text: str, color: str = None):
        self._status_label.configure(
            text=text,
            text_color=color or COLOR_TEXT_SECONDARY,
        )
