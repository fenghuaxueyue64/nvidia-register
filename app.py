#!/usr/bin/env python3
"""NVIDIA Register Control — 桌面应用入口。

启动逻辑：
1. 如果当前 Python 已在 nvidia conda env 中 → 直接启动
2. 如果检测到 nvidia conda env → 用该 env 的 Python 重启自己
3. 否则 → 使用当前 Python 继续启动（降级运行）
"""

import sys
import os
import subprocess

from core.runtime_paths import (
    app_base_dir,
    configure_playwright_browsers,
    configure_stdio_utf8,
    is_frozen,
)

configure_stdio_utf8()

SCRIPT_DIR = app_base_dir()


def _find_nvidia_env_python() -> str | None:
    """查找 nvidia conda 环境的 Python 路径。"""
    candidates = [
        os.path.expanduser("~/miniconda3/envs/nvidia/python.exe"),
        os.path.expanduser("~/anaconda3/envs/nvidia/python.exe"),
        os.path.expanduser("~/Miniconda3/envs/nvidia/python.exe"),
        os.path.expanduser("~/Anaconda3/envs/nvidia/python.exe"),
        "C:/ProgramData/miniconda3/envs/nvidia/python.exe",
        "C:/ProgramData/anaconda3/envs/nvidia/python.exe",
        "C:/miniconda3/envs/nvidia/python.exe",
        "C:/anaconda3/envs/nvidia/python.exe",
    ]
    for candidate in candidates:
        expanded = os.path.expandvars(candidate)
        if os.path.isfile(expanded):
            return expanded
    return None


def _is_nvidia_env() -> bool:
    """判断当前 Python 是否已在 nvidia conda 环境中。"""
    # 方法 1: CONDA_DEFAULT_ENV
    if os.environ.get("CONDA_DEFAULT_ENV", "") == "nvidia":
        return True
    # 方法 2: 可执行文件路径包含 envs/nvidia
    if "envs" in sys.executable and "nvidia" in sys.executable:
        return True
    # 方法 3: CONDA_PREFIX 包含 nvidia
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix and os.path.basename(conda_prefix) == "nvidia":
        return True
    return False


def _ensure_nvidia_env():
    """确保在 nvidia conda 环境中运行。如果不在，自动重启。"""
    if is_frozen():
        return

    if _is_nvidia_env():
        return  # 已经在 nvidia env 中

    nvidia_python = _find_nvidia_env_python()
    if not nvidia_python:
        print("[INFO] nvidia conda env not found, using current Python")
        return

    print(f"[OK] Found nvidia env: {nvidia_python}")
    print(f"[OK] Restarting with nvidia env Python...")

    # 用 nvidia env 的 Python 重启当前脚本
    os.execv(nvidia_python, [nvidia_python] + sys.argv)


def main():
    configure_playwright_browsers()

    if "--register-worker" in sys.argv:
        sys.argv = [sys.argv[0], *[a for a in sys.argv[1:] if a != "--register-worker"]]
        import nvidia_register
        nvidia_register.cli_main()
        return

    # 确保 SCRIPT_DIR 在 sys.path 中
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)

    # 尝试切换到 nvidia conda env
    _ensure_nvidia_env()

    # 在 nvidia env 中安装缺失的 UI 依赖
    _ensure_ui_deps()

    # 启动 UI
    import customtkinter as ctk
    from ui.app_window import NvidiaApp

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = NvidiaApp()
    app.mainloop()


def _ensure_ui_deps():
    """检查并安装 UI 运行所需的 pip 包（customtkinter, Pillow）。"""
    if is_frozen():
        return

    missing = []
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        missing.append("customtkinter")

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")

    if not missing:
        return

    print(f"[INFO] Installing missing UI dependencies: {', '.join(missing)}")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", *missing, "-q"],
            check=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        print(f"[OK] Installed: {', '.join(missing)}")
    except Exception as e:
        print(f"[WARN] Failed to auto-install: {e}")
        print(f"  Please manually run: pip install {' '.join(missing)}")


if __name__ == "__main__":
    main()
