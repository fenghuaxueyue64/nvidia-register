"""
独立多模态 LLM 客户端 — 直接调用 OpenAI 兼容 API。

支持:
  - 多模态对话 (图片 + 文本)
  - 多轮对话历史
  - SSE 流式 / 非流式
  - 连通性测试
  - 从 API.txt 自动发现凭证

默认模型: qwen3.6-flash
"""

import json
import time
from typing import Optional

import requests

from core.ai_config import normalize_ai_model, normalize_openai_base_url


class LLMClient:
    """OpenAI 兼容多模态 LLM 客户端。"""

    def __init__(self, api_key: str, base_url: str,
                 model: str = "qwen3.6-flash",
                 timeout: int = 60):
        self.api_key = api_key
        self.model = normalize_ai_model(model)
        self.timeout = timeout

        # 规范化 base_url
        self._base_url = normalize_openai_base_url(base_url)

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    @property
    def base_url(self) -> str:
        return self._base_url

    # ================================================================
    # 核心方法
    # ================================================================

    def chat(self, messages: list[dict],
             image_b64: Optional[str] = None,
             image_b64_list: Optional[list[str]] = None,
             max_tokens: int = 2048) -> str:
        """多模态对话，支持单图或多图。

        Args:
            messages: 标准 OpenAI 消息列表 [{"role":"user","content":"..."}, ...]
            image_b64: 单张图片 base64
            image_b64_list: 多张图片 base64 列表
            max_tokens: 最大输出 token

        Returns:
            AI 回复文本
        """
        api_msgs = list(messages)

        # 收集图片
        all_images = []
        if image_b64:
            all_images.append(f"data:image/png;base64,{image_b64}")
        if image_b64_list:
            for b in image_b64_list:
                all_images.append(f"data:image/png;base64,{b}")

        if all_images:
            # 注入到最后一条 user 消息
            for i in range(len(api_msgs) - 1, -1, -1):
                if api_msgs[i]["role"] == "user":
                    content_parts = []
                    for img_uri in all_images:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": img_uri},
                        })
                    original = api_msgs[i].get("content", "")
                    content_parts.append({
                        "type": "text",
                        "text": original if isinstance(original, str) else "",
                    })
                    api_msgs[i] = {"role": "user", "content": content_parts}
                    break

        payload = {
            "model": self.model,
            "messages": api_msgs,
            "max_tokens": max_tokens,
        }

        url = f"{self._base_url}/chat/completions"
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def test_connectivity(self) -> dict:
        """连通性测试。返回 {"ok": True/False, "model": ..., "latency_ms": ...}"""
        t0 = time.time()
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "Reply: OK"}],
                "max_tokens": 5,
            }
            url = f"{self._base_url}/chat/completions"
            resp = self._session.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            return {
                "ok": True,
                "message": f"Connected! Model: {self.model}",
                "latency_ms": int((time.time() - t0) * 1000),
                "model": self.model,
                "base_url": self._base_url,
                "response": reply,
            }
        except Exception as e:
            return {
                "ok": False,
                "message": str(e),
                "latency_ms": int((time.time() - t0) * 1000),
            }

    # ================================================================
    # 静态方法
    # ================================================================

    @staticmethod
    def from_api_txt(api_txt_path: str = None,
                     model: str = "qwen3.6-flash") -> "LLMClient":
        """从 API.txt 文件自动创建客户端。

        API.txt 格式:
          第1行: api_key
          第2行: base_url
          第3行: (可选) 备用 base_url
        """
        import os as _os

        if api_txt_path is None:
            current = _os.path.dirname(_os.path.abspath(__file__))
            parent = _os.path.dirname(_os.path.dirname(current))
            api_txt_path = _os.path.join(parent, "QWEN-PHOTO-API", "API.txt")

        if not _os.path.exists(api_txt_path):
            raise FileNotFoundError(f"API.txt not found: {api_txt_path}")

        with open(api_txt_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        if len(lines) < 2:
            raise ValueError("API.txt needs at least 2 lines: api_key + base_url")

        return LLMClient(
            api_key=lines[0],
            base_url=lines[1],
            model=model,
        )

    @staticmethod
    def discover_api_txt() -> Optional[tuple]:
        """自动发现 API.txt 中的凭证。返回 (api_key, base_url) 或 None."""
        import os as _os

        current = _os.path.dirname(_os.path.abspath(__file__))
        parent = _os.path.dirname(_os.path.dirname(current))
        api_path = _os.path.join(parent, "QWEN-PHOTO-API", "API.txt")

        try:
            with open(api_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            if len(lines) >= 2:
                return (lines[0], lines[1])
        except Exception:
            pass
        return None
