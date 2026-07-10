"""运行器 — 在后台线程中编排注册流程，将输出定向到 UI。"""
import importlib
import os
import sys
import time
import threading
import subprocess
import queue as queue_mod

from core.proxy_config import PROXY_CONFIG_KEYS, apply_proxy_environment
from core.runtime_paths import app_base_dir, configure_playwright_browsers, is_frozen


# nvidia_register 模块变量名 → os.environ key 的映射
_ENV_TO_ATTR = {
    "MAIL_TYPE": "MAIL_TYPE",
    "NV_PASSWORD": "PASSWORD",
    "EMAIL_API": "EMAIL_API",
    "EMAIL_AUTH": "EMAIL_AUTH",
    "EMAIL_DOMAIN": "DOMAIN",
    "DUCKMAIL_API_KEY": "DUCKMAIL_API_KEY",
    "DUCKMAIL_DOMAIN": "DUCKMAIL_DOMAIN",
    "DUCKMAIL_API_BASE": "DUCKMAIL_API_BASE",
    "DDG_TOKEN": "DDG_TOKEN",
    "IMAP_EMAIL": "IMAP_EMAIL",
    "IMAP_KEY": "IMAP_KEY",
    "IMAP_HOST": "IMAP_HOST",
    "IMAP_PORT": "IMAP_PORT",
    "IMAP_INBOX": "IMAP_INBOX",
    "ALIAS_DOMAIN": "ALIAS_DOMAIN",
    "NV_KEY_FILE": "OUTPUT_FILE",
    # 导出模式
    "NV_EXPORT_KEY_ONLY": "EXPORT_KEY_ONLY",
    "NV_EXPORT_ACCOUNT_FULL": "EXPORT_ACCOUNT_FULL",
    # AI 验证码配置
    "CAPTCHA_AI_ENABLED": "CAPTCHA_AI_ENABLED",
    "AI_VISION_API_KEY": "AI_VISION_API_KEY",
    "AI_VISION_API_BASE": "AI_VISION_API_BASE",
    "AI_VISION_MODEL": "AI_VISION_MODEL",
    "CHROMIUM_EXECUTABLE_PATH": "CHROMIUM_EXECUTABLE_PATH",
    "PLAYWRIGHT_BROWSERS_PATH": "PLAYWRIGHT_BROWSERS_PATH",
}


def _load_register_module():
    """Import registration automation only when a run actually needs it."""
    return importlib.import_module("nvidia_register")


class RegisterRunner:
    """在后台线程中编排多次注册运行（多进程并发）。"""

    def __init__(self, app):
        self._app = app
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None

        # 回调（由 UI 设置）
        self.on_log = None
        self.on_progress = None
        self.on_complete = None
        self.on_error = None
        self.on_state_changed = None

        # DuckMail 多账户选择
        self._duckmail_key: str | None = None
        self._duckmail_domain: str | None = None

        # 输出队列（供 TerminalWidget 轮询）
        self._output_queue: queue_mod.Queue = queue_mod.Queue()

        # 运行结果
        self._results: list[dict] = []
        self._run_metadata: dict[int, dict[str, str]] = {}
        self._results_lock = threading.Lock()

        # 当前运行的子进程
        self._processes: list[subprocess.Popen] = []

    # ------ 公共接口 ------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def results(self) -> list[dict]:
        with self._results_lock:
            return list(self._results)

    @property
    def output_queue(self) -> queue_mod.Queue:
        return self._output_queue

    def apply_config(self, config_dict: dict[str, str]):
        """将 UI 配置值推送到 os.environ（子进程继承）。"""
        nvidia_register = _load_register_module()
        apply_proxy_environment(config_dict, os.environ)
        for env_key, value in config_dict.items():
            if env_key in PROXY_CONFIG_KEYS:
                continue
            if value is not None:
                os.environ[env_key] = str(value)
            elif env_key in os.environ:
                del os.environ[env_key]

            attr_name = _ENV_TO_ATTR.get(env_key)
            if attr_name:
                try:
                    if env_key == "IMAP_PORT":
                        setattr(nvidia_register, attr_name,
                                int(value) if value else 993)
                    elif env_key == "CAPTCHA_AI_ENABLED":
                        setattr(nvidia_register, attr_name,
                                str(value).lower() in ("1", "true", "yes", "on"))
                    elif env_key in ("NV_EXPORT_KEY_ONLY", "NV_EXPORT_ACCOUNT_FULL"):
                        setattr(nvidia_register, attr_name,
                                str(value).lower() in ("1", "true", "yes", "on"))
                    else:
                        setattr(nvidia_register, attr_name, value)
                except Exception:
                    pass

        script_dir = app_base_dir()
        setattr(nvidia_register, "SCRIPT_DIR", script_dir)
        setattr(nvidia_register, "KEYS_DIR", os.path.join(script_dir, "keys"))
        setattr(nvidia_register, "ENV_FILE", os.path.join(script_dir, ".env"))

        if self._duckmail_key and self._duckmail_domain:
            os.environ["DUCKMAIL_API_KEY"] = self._duckmail_key
            os.environ["DUCKMAIL_DOMAIN"] = self._duckmail_domain
            setattr(nvidia_register, "DUCKMAIL_API_KEY", self._duckmail_key)
            setattr(nvidia_register, "DUCKMAIL_DOMAIN", self._duckmail_domain)

    def start(self, count: int = 1, concurrency: int = 1):
        """启动 N 次注册运行（多进程并发）。"""
        if self.is_running:
            return
        concurrency = max(1, min(concurrency, 10))
        self._stop_requested.clear()
        self._results = []
        self._run_metadata = {}
        self._processes = []
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(count, concurrency),
            daemon=True,
        )
        if self.is_running:
            self._thread = None
            return
        self._thread.start()
        self._notify_state_changed()

    def stop(self):
        """停止：终止所有正在运行的子进程。"""
        self._stop_requested.set()
        for p in self._processes:
            try:
                p.terminate()
            except Exception:
                pass
        self._notify_state_changed()

    def set_duckmail_account(self, api_key: str, domain: str):
        self._duckmail_key = api_key
        self._duckmail_domain = domain

    def clear_duckmail_account(self):
        self._duckmail_key = None
        self._duckmail_domain = None

    # ------ 内部实现 ------

    def _run_loop(self, count: int, concurrency: int):
        """轮询调度：直接管理子进程，每 300ms 检查状态。"""
        frozen = is_frozen()
        script = os.path.join(app_base_dir(), "nvidia_register.py")

        python = sys.executable
        if not frozen:
            for candidate in [
                os.path.expanduser("~/miniconda3/envs/nvidia/python.exe"),
                os.path.expanduser("~/anaconda3/envs/nvidia/python.exe"),
                os.path.expanduser("~/Miniconda3/envs/nvidia/python.exe"),
                os.path.expanduser("~/Anaconda3/envs/nvidia/python.exe"),
                "C:/ProgramData/miniconda3/envs/nvidia/python.exe",
                "C:/ProgramData/anaconda3/envs/nvidia/python.exe",
                "C:/miniconda3/envs/nvidia/python.exe",
                "C:/anaconda3/envs/nvidia/python.exe",
            ]:
                if os.path.isfile(candidate):
                    python = candidate
                    break

        env = os.environ.copy()
        apply_proxy_environment(os.environ, env)
        configure_playwright_browsers()
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        for key in (
            "NV_PLAYWRIGHT_BROWSERS_PATH",
            "CHROMIUM_EXECUTABLE_PATH",
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
            "NV_CHROMIUM_EXECUTABLE_PATH",
        ):
            if os.environ.get(key):
                env[key] = os.environ[key]
        env["NV_NO_DELAY"] = "1"
        env["PYTHONIOENCODING"] = "utf-8:replace"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        total_runs = max(1, count) * max(1, concurrency)
        self._output_queue.put(
            (f"\n调度: {count}轮 x 并发{concurrency} = {total_runs}个任务 | Python={python}\n", "stdout"))

        try:
            pending = list(range(1, total_runs + 1))
            running: dict[int, subprocess.Popen] = {}

            def _reader(p: subprocess.Popen, idx: int):
                try:
                    for line in p.stdout:
                        self._record_process_output(idx, line)
                        self._output_queue.put((f"[{idx}] {line}", "stdout"))
                except Exception:
                    pass

            while pending or running:
                # 启动新进程
                while pending and len(running) < concurrency:
                    if self._stop_requested.is_set():
                        pending.clear()
                        break
                    idx = pending.pop(0)
                    self._notify_progress(idx, total_runs, "running")
                    self._output_queue.put((f"\n[Run #{idx}] 启动子进程\n", "stdout"))

                    args = (
                        [python, "--register-worker", f"--index={idx}"]
                        if frozen else [python, script, f"--index={idx}"]
                    )
                    p = subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        bufsize=1,
                        text=True, encoding="utf-8", errors="replace",
                        env=env,
                    )
                    running[idx] = p
                    self._processes.append(p)

                    t = threading.Thread(
                        target=_reader, args=(p, idx), daemon=True)
                    t.start()

                # 检查完成的进程
                done = []
                for idx, p in list(running.items()):
                    rc = p.poll()
                    if rc is not None:
                        done.append(idx)
                        success = rc == 0
                        metadata = dict(self._run_metadata.get(idx, {}))
                        with self._results_lock:
                            self._results.append(
                                {
                                    "success": success,
                                    "index": idx,
                                    "exit_code": rc,
                                    **metadata,
                                })
                        status = "✅ 成功" if success else f"❌ 失败 (exit={rc})"
                        self._output_queue.put(
                            (f"[Run #{idx}] {status}\n", "stdout"))

                for idx in done:
                    p = running.pop(idx, None)
                    try:
                        self._processes.remove(p)
                    except ValueError:
                        pass

                if running:
                    time.sleep(0.3)

        except Exception as e:
            self._output_queue.put((f"\n调度错误: {e}\n", "stderr"))
        finally:
            for p in self._processes:
                try:
                    p.kill()
                except Exception:
                    pass
            self._processes.clear()
            self._results.sort(key=lambda r: r.get("index", 0))
            self._notify_complete()
            self._notify_state_changed()

    def _record_process_output(self, idx: int, line: str):
        """Extract useful result metadata from child process output."""
        text = line.strip()
        if not text:
            return
        metadata = self._run_metadata.setdefault(idx, {})
        if "AI_PLAYGROUNDS_KEY:" in text:
            _, _, value = text.partition("AI_PLAYGROUNDS_KEY:")
            if value.strip():
                metadata["api_key"] = value.strip()
        for marker in ("saved to:", "fallback saved to:"):
            if marker in text:
                _, _, value = text.partition(marker)
                if value.strip():
                    # 区分 Key 保存路径和 Account 保存路径
                    if "[Account]" in text:
                        metadata["account_save_path"] = value.strip()
                    else:
                        metadata["save_path"] = value.strip()
                break

    # ------ UI 回调 ------

    def _notify_progress(self, current, total, step):
        if self.on_progress and self._app:
            try:
                self._app.after(0, lambda: self.on_progress(current, total, step))
            except Exception:
                pass

    def _notify_complete(self):
        if self.on_complete and self._app:
            try:
                with self._results_lock:
                    results_copy = list(self._results)
                self._app.after(0, lambda: self.on_complete(results_copy))
            except Exception:
                pass

    def _notify_error(self, error_str):
        if self.on_error and self._app:
            try:
                self._app.after(0, lambda: self.on_error(error_str))
            except Exception:
                pass

    def _notify_state_changed(self):
        if self.on_state_changed and self._app:
            try:
                self._app.after(0, self.on_state_changed)
            except Exception:
                pass
