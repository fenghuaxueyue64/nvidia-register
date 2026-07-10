"""Shared AI backend configuration helpers."""

DEFAULT_AI_MODEL = "qwen3.6-flash"

AI_MODEL_OPTIONS = [
    "qwen3.6-flash",
    "qwen3.7-plus",
    "qwen-vl-max",
    "qwen-vl-plus",
    "qwen-plus",
    "qwen3.6-flash-2026-04-16",
    "qwen3.7-plus-2026-05-26",
]

_INVALID_MODEL_PLACEHOLDERS = {
    "",
    "api",
    "auto",
    "v1",
    "compatible-mode",
    "compatible-mode/v1",
}


def normalize_ai_model(model: str | None) -> str:
    """Return a usable model name, correcting common endpoint-field mixups."""
    value = str(model or "").strip()
    if value.lower() in _INVALID_MODEL_PLACEHOLDERS:
        return DEFAULT_AI_MODEL
    return value


def normalize_openai_base_url(base_url: str | None) -> str:
    """Normalize OpenAI-compatible base URLs to a /v1 API root."""
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        return ""
    lower = value.lower()
    if lower.endswith("/v1"):
        return value
    return f"{value}/v1"


def mask_secret(value: str, visible_prefix: int = 6, visible_suffix: int = 4) -> str:
    """Return a short, non-sensitive display form for keys."""
    text = str(value or "")
    if not text:
        return "<empty>"
    if len(text) <= visible_prefix + visible_suffix:
        return "<set>"
    return f"{text[:visible_prefix]}...{text[-visible_suffix:]}"
