"""Runtime path helpers for source and PyInstaller builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return True when running from a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> str:
    """Writable application directory.

    In source runs this is the repository root. In frozen runs this is the
    directory containing the executable, so .env, keys, and logs persist next
    to the exe instead of inside PyInstaller's temporary extraction folder.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_dir() -> str:
    """Read-only bundled resource directory."""
    return os.path.abspath(getattr(sys, "_MEIPASS", app_base_dir()))


def resource_path(relative_path: str) -> str:
    """Return a path to a bundled resource in source or PyInstaller builds."""
    return os.path.normpath(os.path.join(bundle_dir(), relative_path))


def configure_stdio_utf8() -> None:
    """Keep CLI/worker output safe when Windows pipes default to GBK."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
                write_through=True,
            )
        except Exception:
            pass


def configure_playwright_browsers() -> None:
    """Apply a user-provided Playwright browser directory, if configured."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return

    configured = os.environ.get("NV_PLAYWRIGHT_BROWSERS_PATH")
    if configured and os.path.isdir(configured):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = configured


def default_playwright_browsers_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "ms-playwright",
        )
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/ms-playwright")
    return os.path.expanduser("~/.cache/ms-playwright")


def _candidate_browsers_dirs(config: dict[str, str] | None = None) -> list[str]:
    config = config or {}
    dirs = [
        config.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        config.get("NV_PLAYWRIGHT_BROWSERS_PATH", ""),
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        os.environ.get("NV_PLAYWRIGHT_BROWSERS_PATH", ""),
        default_playwright_browsers_dir(),
    ]
    result = []
    for path in dirs:
        if path and path not in result:
            result.append(path)
    return result


def _chromium_from_browsers_dir(browsers_dir: str) -> str | None:
    root = Path(browsers_dir)
    if not root.is_dir():
        return None

    if sys.platform == "win32":
        pattern = ("chromium-*", "chrome-win64", "chrome.exe")
    elif sys.platform == "darwin":
        pattern = ("chromium-*", "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium")
    else:
        pattern = ("chromium-*", "chrome-linux", "chrome")

    matches = sorted(root.glob(os.path.join(*pattern)))
    for candidate in reversed(matches):
        if candidate.is_file():
            return str(candidate)
    return None


def _system_browser_candidates() -> list[str]:
    if sys.platform == "win32":
        roots = [
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        rels = [
            os.path.join("Google", "Chrome", "Application", "chrome.exe"),
            os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ]
        return [os.path.join(root, rel) for root in roots if root for rel in rels]
    if sys.platform == "darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    return [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/usr/bin/brave-browser",
    ]


def find_chromium_executable(config: dict[str, str] | None = None) -> dict[str, str] | None:
    """Find a usable Chromium-family executable without bundled browser data."""
    config = config or {}
    direct_keys = (
        "CHROMIUM_EXECUTABLE_PATH",
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "NV_CHROMIUM_EXECUTABLE_PATH",
    )
    for key in direct_keys:
        path = config.get(key) or os.environ.get(key)
        if path and os.path.isfile(path):
            return {"path": path, "source": key}

    for browsers_dir in _candidate_browsers_dirs(config):
        executable = _chromium_from_browsers_dir(browsers_dir)
        if executable:
            return {"path": executable, "source": "PLAYWRIGHT_BROWSERS_PATH"}

    for path in _system_browser_candidates():
        if path and os.path.isfile(path):
            return {"path": path, "source": "system browser"}

    return None
