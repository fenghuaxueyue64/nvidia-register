"""Shared proxy configuration helpers for UI, runner, and Playwright."""

from __future__ import annotations

import os
from typing import MutableMapping, Mapping
from urllib.parse import quote, unquote, urlsplit, urlunsplit


PROXY_CONFIG_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")

_ENV_ALIASES = {
    "HTTP_PROXY": ("HTTP_PROXY", "http_proxy"),
    "HTTPS_PROXY": ("HTTPS_PROXY", "https_proxy"),
    "NO_PROXY": ("NO_PROXY", "no_proxy"),
}


def apply_proxy_environment(
    values: Mapping[str, object],
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Apply user proxy settings to an environment mapping.

    Blank proxy values intentionally remove both upper and lower case variants,
    so users can disable a previously configured proxy by clearing the UI field.
    Missing keys are ignored to avoid clobbering externally supplied variables.
    """
    target = environ if environ is not None else os.environ

    for canonical_key, aliases in _ENV_ALIASES.items():
        if canonical_key not in values:
            continue

        value = str(values.get(canonical_key) or "").strip()
        if value:
            for alias in aliases:
                target[alias] = value
        else:
            for alias in aliases:
                target.pop(alias, None)


def build_playwright_proxy(values: Mapping[str, object] | None = None) -> dict[str, str] | None:
    """Build Playwright's proxy launch option from configured proxy values."""
    source = values if values is not None else os.environ
    server = _first_value(
        source,
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    )
    if not server:
        return None

    proxy: dict[str, str] = {"server": _server_without_credentials(server)}
    username, password = _credentials(server)
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password

    bypass = _first_value(source, "NO_PROXY", "no_proxy")
    if bypass:
        proxy["bypass"] = bypass

    return proxy


def _first_value(source: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return ""


def _credentials(server: str) -> tuple[str, str]:
    parsed = urlsplit(server)
    if not parsed.scheme or not parsed.netloc:
        return "", ""
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    return username, password


def _server_without_credentials(server: str) -> str:
    parsed = urlsplit(server)
    if not parsed.scheme or not parsed.netloc:
        return server
    if not parsed.username and not parsed.password:
        return server

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"

    netloc = quote(host, safe="[]:")
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
