"""进程管理器 — Conda 环境检测、Playwright 浏览器检测与自动安装。"""

import os
import sys
import shutil
import subprocess
import json

from core.proxy_config import apply_proxy_environment
from core.runtime_paths import (
    configure_playwright_browsers,
    default_playwright_browsers_dir,
    find_chromium_executable,
    is_frozen,
)


class ProcessManager:
    """检测 Conda 环境和依赖状态，并提供自动修复能力。"""

    # nvidia conda 环境名称
    NVIDIA_ENV_NAME = "nvidia"

    def __init__(self):
        self._conda_info: dict | None = None
        self._pw_info: dict | None = None
        self._browser_config: dict[str, str] = {}

    def set_browser_config(self, values: dict[str, str] | None):
        """Set optional browser path values read from .env or UI."""
        self._browser_config = values or {}
        self._pw_info = None

    # ====================================================================
    # Conda
    # ====================================================================

    def detect_conda(self, force: bool = False) -> dict:
        """检测 Conda 安装和可用环境。

        Returns:
            dict with keys: available, conda_path, envs, active_env,
                            nvidia_env_path, nvidia_python
        """
        if self._conda_info is not None and not force:
            return self._conda_info

        conda_path = shutil.which("conda")

        # 尝试常见 Windows 安装路径
        if not conda_path:
            candidates = [
                os.path.expanduser("~/miniconda3/Scripts/conda.exe"),
                os.path.expanduser("~/anaconda3/Scripts/conda.exe"),
                os.path.expanduser("~/Miniconda3/Scripts/conda.exe"),
                os.path.expanduser("~/Anaconda3/Scripts/conda.exe"),
                "C:/ProgramData/miniconda3/Scripts/conda.exe",
                "C:/ProgramData/anaconda3/Scripts/conda.exe",
                "C:/miniconda3/Scripts/conda.exe",
                "C:/anaconda3/Scripts/conda.exe",
            ]
            for candidate in candidates:
                expanded = os.path.expandvars(candidate)
                if os.path.exists(expanded):
                    conda_path = expanded
                    break

        if not conda_path:
            self._conda_info = {
                "available": False,
                "conda_path": None,
                "envs": [],
                "active_env": None,
                "nvidia_env_path": None,
                "nvidia_python": None,
            }
            return self._conda_info

        # 列出环境
        envs: list[dict] = []
        nvidia_env_path = None
        try:
            result = subprocess.run(
                [conda_path, "env", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for entry in data.get("envs", []):
                    name = os.path.basename(entry)
                    envs.append({"name": name, "path": entry})
                    if name == self.NVIDIA_ENV_NAME:
                        nvidia_env_path = entry
        except Exception:
            pass

        # 检查当前激活的环境
        active_env = None
        conda_prefix = os.environ.get("CONDA_PREFIX", "")
        if conda_prefix:
            active_env = os.path.basename(conda_prefix)
        conda_default_env = os.environ.get("CONDA_DEFAULT_ENV", "")
        if conda_default_env:
            active_env = conda_default_env

        # 查找 nvidia env Python
        nvidia_python = self._find_env_python(nvidia_env_path)

        self._conda_info = {
            "available": True,
            "conda_path": conda_path,
            "envs": envs,
            "active_env": active_env,
            "nvidia_env_path": nvidia_env_path,
            "nvidia_python": nvidia_python,
        }
        return self._conda_info

    @staticmethod
    def _find_env_python(env_path: str | None) -> str | None:
        """给定 conda env 路径，查找其 python 可执行文件。"""
        if not env_path:
            return None
        if sys.platform == "win32":
            py = os.path.join(env_path, "python.exe")
        else:
            py = os.path.join(env_path, "bin", "python")
        return py if os.path.isfile(py) else None

    # ====================================================================
    # Playwright — 真实校验 + 自动安装
    # ====================================================================

    def check_playwright(self, force: bool = False) -> dict:
        """检查 Playwright 库和浏览器是否真正可用。

        不再用 --dry-run（它返回 RC=0 即使浏览器不存在），
        而是直接检查 Playwright 期望的浏览器二进制文件是否存在。

        Returns:
            dict with keys:
                importable: bool       — 能否 import playwright
                browsers_installed: bool — chromium 二进制是否真存在
                chromium_path: str|None — chromium/chrome/edge 可执行文件路径
                required_version: str|None  — 需要的 chromium 目录版本号
                browser_source: str|None — 路径来源
                error: str|None        — 不可用时的错误信息
        """
        if self._pw_info is not None and not force:
            return self._pw_info

        configure_playwright_browsers()

        result = {
            "importable": False,
            "browsers_installed": False,
            "chromium_path": None,
            "required_version": None,
            "browser_source": None,
            "error": None,
        }

        # 1. 检查 import
        try:
            import playwright  # noqa: F401
            result["importable"] = True
        except ImportError:
            result["error"] = "Playwright 未安装，请运行: pip install playwright"
            self._pw_info = result
            return result

        # 2. 查找可用浏览器。冻结 exe 不内置 Chromium，优先使用用户路径。
        try:
            result.update(self._verify_browser_binary())
        except Exception as e:
            result["error"] = f"Playwright 浏览器验证失败: {e}"

        self._pw_info = result
        return result

    def _verify_browser_binary(self) -> dict:
        """通过 Playwright 内部注册表获取 chromium 路径，验证二进制存在。

        Returns:
            dict (subset of check_playwright result)
        """
        browser = find_chromium_executable(self._browser_config)
        if browser:
            return {
                "browsers_installed": True,
                "chromium_path": browser["path"],
                "required_version": None,
                "browser_source": browser["source"],
                "error": None,
            }

        if is_frozen():
            return {
                "browsers_installed": False,
                "chromium_path": None,
                "required_version": None,
                "browser_source": None,
                "error": (
                    "未找到可用 Chrome/Edge/Chromium。请在配置中指定 "
                    "CHROMIUM_EXECUTABLE_PATH，或设置 PLAYWRIGHT_BROWSERS_PATH。"
                ),
            }

        # Playwright 浏览器安装根目录
        browsers_dir = os.path.join(
            os.environ.get(
                "PLAYWRIGHT_BROWSERS_PATH",
                os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                             "ms-playwright") if sys.platform == "win32"
                else os.path.expanduser("~/.cache/ms-playwright"),
            )
        )

        chromium_path = None
        required_version = None

        # 用 playwright CLI 获取安装信息（最可靠）
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            output = proc.stdout + proc.stderr
            # 解析 "Install location: ..." 行
            for line in output.splitlines():
                if "Install location" in line:
                    install_dir = line.split(":", 1)[1].strip()
                    required_version = os.path.basename(install_dir)
                    # 构造平台对应的 chrome 路径
                    if sys.platform == "win32":
                        chromium_path = os.path.join(
                            install_dir, "chrome-win64", "chrome.exe"
                        )
                    elif sys.platform == "darwin":
                        chromium_path = os.path.join(
                            install_dir, "chrome-mac", "Chromium.app",
                            "Contents", "MacOS", "Chromium",
                        )
                    else:
                        chromium_path = os.path.join(
                            install_dir, "chrome-linux", "chrome"
                        )
                    break
        except Exception:
            pass

        if not chromium_path:
            return {
                "browsers_installed": False,
                "chromium_path": None,
                "required_version": required_version,
                "error": "无法确定 Chromium 安装路径",
            }

        # 3. 真正验证文件是否存在
        exists = os.path.isfile(chromium_path)

        if not exists:
            return {
                "browsers_installed": False,
                "chromium_path": chromium_path,
                "required_version": required_version,
                "error": (
                    f"Chromium 二进制不存在: {chromium_path}\n"
                    f"请运行: python -m playwright install chromium"
                ),
            }

        return {
            "browsers_installed": True,
            "chromium_path": chromium_path,
            "required_version": required_version,
            "browser_source": "playwright install",
            "error": None,
        }

    def install_browsers(self, on_output=None) -> bool:
        """运行 playwright install chromium，安装浏览器。

        Args:
            on_output: callable(text: str) — 实时输出回调

        Returns:
            True if install succeeded
        """
        if is_frozen():
            if on_output:
                on_output(
                    "当前是打包后的 exe，不能自动安装 Playwright 浏览器。\n"
                    "请安装 Chrome/Edge，或在配置中填写 CHROMIUM_EXECUTABLE_PATH。\n"
                )
            return False

        try:
            env = os.environ.copy()
            apply_proxy_environment(self._browser_config, env)
            proc = subprocess.Popen(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for line in proc.stdout:
                if on_output:
                    try:
                        on_output(line)
                    except Exception:
                        pass
            proc.wait(timeout=120)
            success = proc.returncode == 0
            # 安装后清除缓存，强制下次重新检测
            if success:
                self._pw_info = None
            return success
        except Exception as e:
            if on_output:
                on_output(f"Install failed: {e}\n")
            return False

    # ====================================================================
    # 综合状态
    # ====================================================================

    @staticmethod
    def get_activate_command(env_name: str) -> str:
        """返回激活指定 Conda 环境的命令字符串。"""
        return f"conda activate {env_name}"

    def get_status_text(self) -> str:
        """返回适合显示的综合状态文本。"""
        conda_info = self.detect_conda()
        pw_info = self.check_playwright()

        parts = []

        if is_frozen():
            parts.append("Runtime: bundled exe")
        elif conda_info["available"]:
            active = conda_info.get("active_env")
            nvidia_path = conda_info.get("nvidia_env_path")
            if active == self.NVIDIA_ENV_NAME:
                parts.append(f"Conda: nvidia [active]")
            elif nvidia_path:
                parts.append(f"Conda: nvidia [available]")
            elif active:
                parts.append(f"Conda: {active}")
            else:
                parts.append("Conda: [installed] (no active env)")
        else:
            parts.append("Conda: [not found]")

        if pw_info["importable"]:
            if pw_info["browsers_installed"]:
                source = pw_info.get("browser_source") or "OK"
                parts.append(f"Browser: {source}")
            else:
                parts.append("Browser: missing")
        else:
            parts.append("Playwright: not installed")

        return " | ".join(parts)

    def get_detailed_status(self) -> dict:
        """返回详细状态，供 UI 展示和决策。"""
        conda_info = self.detect_conda()
        pw_info = self.check_playwright()

        return {
            "conda": conda_info,
            "playwright": pw_info,
            "ready": pw_info["browsers_installed"],
            "missing": self._get_missing_items(conda_info, pw_info),
        }

    @staticmethod
    def _get_missing_items(conda_info: dict, pw_info: dict) -> list[str]:
        """返回缺失项列表。"""
        missing = []
        if not pw_info["importable"]:
            missing.append("playwright-pip")         # pip install playwright
        elif not pw_info["browsers_installed"]:
            missing.append("playwright-browser")      # playwright install chromium
        return missing
