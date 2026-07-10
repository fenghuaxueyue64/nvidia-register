"""Helpers for resolving API key output and scan locations."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class KeySaveTarget:
    path: str
    is_directory: bool


def normalize_config_path(path: str | None, base_dir: str | None = None) -> str:
    """Expand env/user markers and make relative configured paths app-local."""
    raw = str(path or "").strip().strip("\"'")
    if not raw:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if base_dir and not os.path.isabs(expanded):
        expanded = os.path.join(base_dir, expanded)
    return os.path.normpath(expanded)


def resolve_key_scan_dir(
    configured_path: str | None,
    default_dir: str,
    base_dir: str | None = None,
) -> str:
    """Return the directory the UI should scan/open for saved API keys."""
    target = normalize_config_path(configured_path, base_dir)
    fallback = normalize_config_path(default_dir, base_dir) or default_dir
    if not target:
        return fallback
    if os.path.isfile(target):
        return os.path.dirname(target) or fallback
    if _path_looks_like_file(target, configured_path):
        return os.path.dirname(target) or fallback
    return target


def resolve_key_save_target(
    configured_path: str | None,
    default_dir: str,
    base_dir: str | None = None,
) -> KeySaveTarget:
    """Resolve NV_KEY_FILE as either a directory target or explicit file target."""
    target = normalize_config_path(configured_path, base_dir)
    fallback = normalize_config_path(default_dir, base_dir) or default_dir
    if not target:
        return KeySaveTarget(fallback, True)
    if os.path.isdir(target):
        return KeySaveTarget(target, True)
    if _path_looks_like_file(target, configured_path):
        return KeySaveTarget(target, False)
    return KeySaveTarget(target, True)


def shorten_display_path(path: str, max_chars: int = 56) -> str:
    normalized = str(path or "").replace("\\", "/")
    if len(normalized) <= max_chars:
        return normalized
    return "..." + normalized[-(max_chars - 3):]


def _path_looks_like_file(path: str, original: str | None = None) -> bool:
    raw = str(original or "").strip()
    if raw.endswith(("/", "\\")):
        return False
    name = os.path.basename(path.rstrip("\\/"))
    _root, ext = os.path.splitext(name)
    return bool(ext)
