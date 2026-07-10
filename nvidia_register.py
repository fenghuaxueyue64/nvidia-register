#!/usr/bin/env python3
"""
nvidia-register — 一键注册 build.nvidia.com 账号并创建 AI_PLAYGROUNDS_KEY

完整的注册流程自动化：创建临时邮箱 → 填写注册表单 → 接收验证码 →
接受开发者协议 → 选择组织 → 自动创建 API Key。

用法:
  pip install -r requirements.txt
  playwright install chromium

  python nvidia_register.py --init       # 生成 .env 配置文件
  # 编辑 .env 填入你的邮箱服务信息
  python nvidia_register.py              # 自动完成注册+API Key创建

环境变量 (或 .env 文件):

  通用:
  MAIL_TYPE        邮箱服务类型: api (默认) | duckmail | imap
  NV_PASSWORD      NVIDIA 账号密码 (必填)
  NV_KEY_FILE      API Key 保存目录或 .txt 文件 (可选，默认: keys/ 目录)
  CHROMIUM_EXECUTABLE_PATH  Chrome/Edge/Chromium 可执行文件路径 (可选)
  PLAYWRIGHT_BROWSERS_PATH  Playwright 浏览器目录 (可选)
  HTTP_PROXY       HTTP 代理 (可选，例如 http://127.0.0.1:7897)
  HTTPS_PROXY      HTTPS 代理 (可选，例如 http://127.0.0.1:7897)
  NO_PROXY         不走代理的主机列表 (可选)

  MAIL_TYPE=api (原有逻辑):
  EMAIL_API        邮箱服务 API 地址 (必填)
  EMAIL_AUTH       邮箱服务管理员密钥 (必填)
  EMAIL_DOMAIN     邮箱域名 (必填)
  EMAIL_CREATE_INTERVAL_SECONDS 并发创建邮箱缓冲间隔秒数 (可选, 默认 1)
  EMAIL_CREATE_RETRIES          邮箱创建重试次数 (可选, 默认 4)
  EMAIL_CREATE_RETRY_DELAY_SECONDS 邮箱创建重试基础等待秒数 (可选, 默认 1)

  MAIL_TYPE=duckmail (DuckMail API):
  DUCKMAIL_API_KEY DuckMail API 密钥 (必填)
  DUCKMAIL_DOMAIN  邮箱域名 (默认 duckmail.sbs)
  DUCKMAIL_API_BASE DuckMail API 地址 (可选，默认 https://api.duckmail.sbs)

  MAIL_TYPE=imap (DDG 别名 + IMAP):
  DDG_TOKEN        DuckDuckGo Email Protection Token (必填)
  IMAP_EMAIL       IMAP 登录邮箱 (必填)
  IMAP_KEY         IMAP 授权码 (必填)
  IMAP_HOST        IMAP 服务器 (必填, 如 imap.qq.com)
  IMAP_PORT        IMAP SSL 端口 (默认 993)
  IMAP_INBOX       收件箱名称 (默认 INBOX)
  ALIAS_DOMAIN     DDG 别名域名 (默认 duck.com)
"""

import asyncio, time, re, sys, os, json, hashlib, secrets, tempfile
import requests
from playwright.async_api import async_playwright
from mail_providers import (
    BaseMailProvider,
    DuckMailProvider,
    ImapMailProvider,
    normalize_api_base,
    normalize_mail_domain,
)
from core.runtime_paths import (
    app_base_dir,
    configure_playwright_browsers,
    configure_stdio_utf8,
    find_chromium_executable,
)
from core.key_paths import resolve_key_save_target
from core.proxy_config import apply_proxy_environment, build_playwright_proxy

configure_stdio_utf8()

# AI 验证码求解器（延迟导入，避免未安装依赖时报错）
_CAPTCHA_SOLVER_AVAILABLE = True
try:
    from core.captcha_solver import HCaptchaSolver
except ImportError:
    _CAPTCHA_SOLVER_AVAILABLE = False

configure_playwright_browsers()

SCRIPT_DIR = app_base_dir()
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")


def load_env():
    if not os.path.exists(ENV_FILE):
        return
    loaded: dict[str, str] = {}
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key not in os.environ:
                os.environ[key] = val
                loaded[key] = val
    apply_proxy_environment(loaded, os.environ)


def build_playwright_proxy_from_env(values: dict[str, str] | None = None) -> dict[str, str] | None:
    return build_playwright_proxy(values or os.environ)


def init_env():
    if os.path.exists(ENV_FILE):
        print(f"⚠️  {ENV_FILE} already exists. Delete it first to regenerate.")
        return
    template = """# NVIDIA Register — Configuration
# ==============================================================================
# 邮箱服务类型: api (原有API) | duckmail (DuckMail API) | imap (DDG+IMAP)
# ==============================================================================
MAIL_TYPE=

# --------------------------------------------------------------------------
# 通用配置 (所有类型都需要)
# --------------------------------------------------------------------------
NV_PASSWORD=

# --------------------------------------------------------------------------
# MAIL_TYPE=api — 原有自建临时邮箱API (默认)
# --------------------------------------------------------------------------
# EMAIL_API=
# EMAIL_AUTH=
# EMAIL_DOMAIN=
# EMAIL_CREATE_INTERVAL_SECONDS=1
# EMAIL_CREATE_RETRIES=4
# EMAIL_CREATE_RETRY_DELAY_SECONDS=1

# --------------------------------------------------------------------------
# MAIL_TYPE=duckmail — DuckMail API (api.duckmail.sbs)
# --------------------------------------------------------------------------
# DUCKMAIL_API_KEY=
# DUCKMAIL_DOMAIN=duckmail.sbs
# DUCKMAIL_API_BASE=https://api.duckmail.sbs

# --------------------------------------------------------------------------
# MAIL_TYPE=imap — DDG别名 + IMAP读取
# --------------------------------------------------------------------------
# DDG_TOKEN=
# IMAP_EMAIL=
# IMAP_KEY=
# IMAP_HOST=imap.qq.com
# IMAP_PORT=993
# IMAP_INBOX=INBOX
# ALIAS_DOMAIN=duck.com

# --------------------------------------------------------------------------
# AI 自动验证码 (可选) — 启用后自动破解 hCaptcha 图片验证码
# --------------------------------------------------------------------------
# CAPTCHA_AI_ENABLED=false
# AI_VISION_API_KEY=          # 视觉模型 API Key
# AI_VISION_API_BASE=         # OpenAI 兼容的视觉 API 基础 URL
# AI_VISION_MODEL=qwen-vl-max # 模型名称

# --------------------------------------------------------------------------
# 可选
# --------------------------------------------------------------------------
# NV_KEY_FILE=      # 可填目录；高级用法可填 .txt 文件
# CHROMIUM_EXECUTABLE_PATH=
# PLAYWRIGHT_BROWSERS_PATH=

# --------------------------------------------------------------------------
# 网络代理 (可选)
# --------------------------------------------------------------------------
# HTTP_PROXY=http://127.0.0.1:7897
# HTTPS_PROXY=http://127.0.0.1:7897
# NO_PROXY=localhost,127.0.0.1
"""
    with open(ENV_FILE, "w") as f:
        f.write(template)
    print(f"✅ Created {ENV_FILE}")
    print(f"   Edit it, then run: python nvidia_register.py")


load_env()

EMAIL_API = os.environ.get("EMAIL_API")
EMAIL_AUTH = os.environ.get("EMAIL_AUTH")
DOMAIN = os.environ.get("EMAIL_DOMAIN")
MAIL_TYPE = os.environ.get("MAIL_TYPE", "").strip().lower() or "api"  # api | duckmail | imap
DUCKMAIL_API_KEY = os.environ.get("DUCKMAIL_API_KEY")
DUCKMAIL_DOMAIN = normalize_mail_domain(os.environ.get("DUCKMAIL_DOMAIN", "duckmail.sbs"))
DUCKMAIL_API_BASE = normalize_api_base(os.environ.get("DUCKMAIL_API_BASE"))
DDG_TOKEN = os.environ.get("DDG_TOKEN")
IMAP_EMAIL = os.environ.get("IMAP_EMAIL")
IMAP_KEY = os.environ.get("IMAP_KEY")
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.qq.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT") or "993")
IMAP_INBOX = os.environ.get("IMAP_INBOX", "INBOX")
ALIAS_DOMAIN = os.environ.get("ALIAS_DOMAIN", "duck.com")
PASSWORD = os.environ.get("NV_PASSWORD")
OUTPUT_FILE = os.environ.get("NV_KEY_FILE")
KEYS_DIR = os.path.join(SCRIPT_DIR, "keys")
LAST_SAVE_PATH: str = ""  # 最近一次保存的路径（供 UI 读取）
LAST_ACCOUNT_SAVE_PATH: str = ""  # 最近一次账号文件保存路径

# ---- 导出模式 ----
EXPORT_KEY_ONLY = os.environ.get("NV_EXPORT_KEY_ONLY", "true").lower() in ("1", "true", "yes", "on")
EXPORT_ACCOUNT_FULL = os.environ.get("NV_EXPORT_ACCOUNT_FULL", "false").lower() in ("1", "true", "yes", "on")

# ---- AI 验证码求解配置 ----
CAPTCHA_AI_ENABLED = os.environ.get("CAPTCHA_AI_ENABLED", "").lower() in ("1", "true", "yes", "on")
AI_VISION_API_KEY = os.environ.get("AI_VISION_API_KEY", "")
AI_VISION_API_BASE = os.environ.get("AI_VISION_API_BASE", "auto")
AI_VISION_MODEL = os.environ.get("AI_VISION_MODEL", "qwen3.6-flash")
CHROMIUM_EXECUTABLE_PATH = os.environ.get("CHROMIUM_EXECUTABLE_PATH", "")
PLAYWRIGHT_BROWSERS_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")

# 自动发现 API 凭证
if AI_VISION_API_BASE in ("auto", "") and not AI_VISION_API_KEY:
    _qwen_api_path = os.path.join(SCRIPT_DIR, "..", "QWEN-PHOTO-API", "API.txt")
    try:
        with open(_qwen_api_path, "r") as _f:
            _lines = [l.strip() for l in _f.readlines() if l.strip() and not l.strip().startswith("#")]
        if len(_lines) >= 2:
            AI_VISION_API_KEY = _lines[0]
            AI_VISION_API_BASE = _lines[1]
            print(f"  📡 Auto-discovered QWEN API from: {_qwen_api_path}")
    except Exception:
        pass


def get_output_path() -> str:
    """生成输出路径: keys/nvidia_api_key_{序号}_{时间}.txt"""
    os.makedirs(KEYS_DIR, exist_ok=True)
    # 找下一个序号
    existing = [f for f in os.listdir(KEYS_DIR) if f.startswith("nvidia_api_key_") and f.endswith(".txt")]
    nums = []
    for f in existing:
        try:
            # nvidia_api_key_1_20260629_010800.txt → 1
            parts = f[len("nvidia_api_key_"):].split("_")
            nums.append(int(parts[0]))
        except: pass
    num = max(nums) + 1 if nums else 1
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(KEYS_DIR, f"nvidia_api_key_{num}_{ts}.txt")


def get_output_path_in_dir(directory: str) -> str:
    """在指定目录下生成输出路径: dir/nvidia_api_key_{序号}_{时间}.txt"""
    os.makedirs(directory, exist_ok=True)
    existing = [f for f in os.listdir(directory) if f.startswith("nvidia_api_key_") and f.endswith(".txt")]
    nums = []
    for f in existing:
        try:
            parts = f[len("nvidia_api_key_"):].split("_")
            nums.append(int(parts[0]))
        except (ValueError, IndexError):
            pass
    num = max(nums) + 1 if nums else 1
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(directory, f"nvidia_api_key_{num}_{ts}.txt")


def get_account_output_path_in_dir(directory: str) -> str:
    """在指定目录下生成账号导出路径: dir/nvidia_account_{序号}_{时间}.txt"""
    os.makedirs(directory, exist_ok=True)
    existing = [f for f in os.listdir(directory) if f.startswith("nvidia_account_") and f.endswith(".txt")]
    nums = []
    for f in existing:
        try:
            parts = f[len("nvidia_account_"):].split("_")
            nums.append(int(parts[0]))
        except (ValueError, IndexError):
            pass
    num = max(nums) + 1 if nums else 1
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(directory, f"nvidia_account_{num}_{ts}.txt")


def validate_config():
    missing = []
    if not PASSWORD:
        missing.append("NV_PASSWORD")

    if MAIL_TYPE == "api":
        if not EMAIL_API: missing.append("EMAIL_API")
        if not EMAIL_AUTH: missing.append("EMAIL_AUTH")
        if not DOMAIN: missing.append("EMAIL_DOMAIN")
    elif MAIL_TYPE == "duckmail":
        if not DUCKMAIL_API_KEY: missing.append("DUCKMAIL_API_KEY")
        if not DUCKMAIL_DOMAIN: missing.append("DUCKMAIL_DOMAIN")
    elif MAIL_TYPE == "imap":
        if not DDG_TOKEN: missing.append("DDG_TOKEN")
        if not IMAP_EMAIL: missing.append("IMAP_EMAIL")
        if not IMAP_KEY: missing.append("IMAP_KEY")
        if not IMAP_HOST: missing.append("IMAP_HOST")
    else:
        print(f"❌ Unknown MAIL_TYPE: {MAIL_TYPE}")
        print("   Valid: api | duckmail | imap")
        sys.exit(1)

    if missing:
        print("❌ Missing required config:")
        for m in missing:
            print(f"   {m}")
        print()
        print("Fix:")
        print(f"  1. python nvidia_register.py --init")
        print(f"  2. Edit {ENV_FILE} with your credentials")
        print(f"  3. python nvidia_register.py")
        print()
        print("Or pass via env:")
        print("  MAIL_TYPE=... NV_PASSWORD=... python nvidia_register.py")
        sys.exit(1)


def print_config():
    print(f"  MAIL_TYPE:    {MAIL_TYPE}")
    if MAIL_TYPE == "api":
        print(f"  EMAIL_API:    {EMAIL_API}")
        print(f"  DOMAIN:       {DOMAIN}")
    elif MAIL_TYPE == "duckmail":
        print(f"  DUCKMAIL_DOMAIN: {DUCKMAIL_DOMAIN}")
        print(f"  DUCKMAIL_API: {DUCKMAIL_API_BASE}")
    elif MAIL_TYPE == "imap":
        print(f"  IMAP_HOST:    {IMAP_HOST}:{IMAP_PORT}")
        print(f"  IMAP_EMAIL:   {IMAP_EMAIL}")
        print(f"  ALIAS_DOMAIN: {ALIAS_DOMAIN}")
    print(f"  PASSWORD:     {'*' * 6}")
    if OUTPUT_FILE:
        print(f"  OUTPUT_FILE:  {OUTPUT_FILE}")
    else:
        print(f"  KEYS_DIR:     {KEYS_DIR}")
    print(f"  ENV_FILE:     {ENV_FILE}")


_provider: BaseMailProvider | None = None  # 当前使用的邮箱提供商实例


def create_provider() -> BaseMailProvider:
    """根据 MAIL_TYPE 创建对应的邮箱提供商。"""
    global _provider
    if MAIL_TYPE == "api":
        # 原有 API 模式：包装为 LegacyApiProvider
        _provider = LegacyApiProvider(EMAIL_API, EMAIL_AUTH, DOMAIN)
    elif MAIL_TYPE == "duckmail":
        _provider = DuckMailProvider(
            api_key=DUCKMAIL_API_KEY,
            domain=DUCKMAIL_DOMAIN,
            api_base=DUCKMAIL_API_BASE,
        )
    elif MAIL_TYPE == "imap":
        _provider = ImapMailProvider(
            ddg_token=DDG_TOKEN,
            imap_email=IMAP_EMAIL,
            imap_key=IMAP_KEY,
            imap_host=IMAP_HOST,
            imap_port=IMAP_PORT,
            inbox=IMAP_INBOX,
            alias_domain=ALIAS_DOMAIN,
        )
    else:
        raise ValueError(f"Unknown MAIL_TYPE: {MAIL_TYPE}")
    return _provider


# ============================================================================
# 原有 API 模式适配器 — 包装旧的 EMAIL_API 接口到 BaseMailProvider
# ============================================================================


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


class LegacyApiProvider(BaseMailProvider):
    """兼容原有自建临时邮箱 API 的适配器。"""
    name = "legacy_api"

    def __init__(self, api_url: str, auth: str, domain: str, timeout: int = 15):
        self.api_url = api_url.rstrip("/")
        self.auth = auth
        self.domain = domain
        self.timeout = timeout

    def create_mailbox(self, username: str | None = None) -> dict:
        if not username:
            username = self._default_username()

        self._wait_for_create_slot()
        d = self._post_json(
            "/admin/new_address",
            headers={"x-admin-auth": self.auth, "Content-Type": "application/json"},
            json={"name": username, "domain": self.domain, "enablePrefix": False},
        )
        jwt = d.get("jwt", "")
        address = d.get("address", "")
        if not jwt:
            raise RuntimeError(f"Legacy API create failed: {d}")
        return {"address": address, "jwt": jwt}

    def fetch_latest_message(self, mailbox: dict) -> dict | None:
        jwt = str(mailbox.get("jwt") or "")
        try:
            data = self._get_json(
                "/api/mails?limit=5&offset=0",
                headers={"Authorization": f"Bearer {jwt}"},
            )
            mails = data.get("results") or data.get("data") or []
            for mail in mails:
                mid = mail.get("id") or mail.get("_id")
                if mid:
                    md = self._get_json(
                        f"/api/mail/{mid}",
                        headers={"Authorization": f"Bearer {jwt}"},
                    )
                    raw_str = md.get("raw", "")
                    subject = ""
                    for line in raw_str.split("\n"):
                        if line.startswith("Subject:"):
                            subject = line.strip()
                    return {
                        "message_id": str(mid),
                        "subject": subject,
                        "sender": "",
                        "text_content": raw_str,
                        "html_content": "",
                        "raw": md,
                    }
        except Exception as e:
            print(f"  poll: {e}", flush=True)
        return None

    def _default_username(self) -> str:
        millis = int(time.time() * 1000) % 100_000_000
        pid = os.getpid() % 10_000
        suffix = secrets.token_hex(2)
        return f"nv{millis:08d}{pid:04d}{suffix}"

    def _post_json(self, path: str, **kwargs) -> dict:
        url = f"{self.api_url}{path}"
        return self._request_json("POST", url, **kwargs)

    def _get_json(self, path: str, **kwargs) -> dict:
        url = f"{self.api_url}{path}"
        return self._request_json("GET", url, **kwargs)

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        retries = max(0, _env_int("EMAIL_CREATE_RETRIES", 4))
        retry_delay = max(0.0, _env_float("EMAIL_CREATE_RETRY_DELAY_SECONDS", 1.0))
        for attempt in range(retries + 1):
            try:
                if method.upper() == "POST":
                    resp = requests.post(url, timeout=self.timeout, **kwargs)
                else:
                    resp = requests.get(url, timeout=self.timeout, **kwargs)

                if resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"Legacy API HTTP {resp.status_code}: {resp.text[:300]}"
                    )

                try:
                    data = resp.json()
                except ValueError as exc:
                    body = (getattr(resp, "text", "") or "").strip() or "<empty body>"
                    raise RuntimeError(
                        f"Legacy API returned non-JSON response from {url}: {body[:300]}"
                    ) from exc

                if not isinstance(data, dict):
                    raise RuntimeError(
                        f"Legacy API returned {type(data).__name__}, expected object"
                    )
                return data
            except (requests.exceptions.RequestException, RuntimeError) as exc:
                if attempt >= retries:
                    raise
                print(f"  mail API retry {attempt + 1}/{retries}: {exc}", flush=True)
                if retry_delay > 0:
                    time.sleep(retry_delay * (attempt + 1))

        raise RuntimeError("Legacy API request failed")

    def _wait_for_create_slot(self) -> None:
        interval = max(0.0, _env_float("EMAIL_CREATE_INTERVAL_SECONDS", 1.0))
        if interval <= 0:
            return

        base_dir = os.environ.get("NV_EMAIL_BUFFER_DIR") or os.path.join(
            tempfile.gettempdir(), "nvidia-register-mail-buffer"
        )
        os.makedirs(base_dir, exist_ok=True)
        key = hashlib.sha1(
            f"{self.api_url}|{self.domain}".encode("utf-8")
        ).hexdigest()[:16]
        lock_dir = os.path.join(base_dir, f"{key}.lock")
        state_file = os.path.join(base_dir, f"{key}.last")

        lock_timeout = max(0.1, _env_float("EMAIL_CREATE_LOCK_TIMEOUT_SECONDS", 30.0))
        stale_after = max(lock_timeout, _env_float("EMAIL_CREATE_LOCK_STALE_SECONDS", 60.0))
        deadline = time.time() + lock_timeout

        while True:
            try:
                os.mkdir(lock_dir)
                break
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(lock_dir) > stale_after:
                        os.rmdir(lock_dir)
                        continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    print("  ⚠️ Email API buffer lock timeout, continuing...", flush=True)
                    return
                time.sleep(0.05)

        try:
            last_started = None
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    last_started = float(f.read().strip() or "0")
            except (OSError, ValueError):
                pass

            if last_started is not None:
                wait_seconds = interval - (time.time() - last_started)
                if wait_seconds > 0:
                    print(
                        f"  ⏳ Email API buffer: waiting {wait_seconds:.1f}s...",
                        flush=True,
                    )
                    time.sleep(wait_seconds)

            with open(state_file, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        finally:
            try:
                os.rmdir(lock_dir)
            except OSError:
                pass


def poll_code_via_legacy(jwt, timeout=180):
    """[已废弃] 原有轮询函数，保留向后兼容。请使用 _provider.poll_code()。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{EMAIL_API}/api/mails?limit=5&offset=0",
                headers={"Authorization": f"Bearer {jwt}"}, timeout=15)
            data = r.json()
            mails = data.get("results") or data.get("data") or []
            for mail in mails:
                mid = mail.get("id") or mail.get("_id")
                if mid:
                    r2 = requests.get(f"{EMAIL_API}/api/mail/{mid}",
                        headers={"Authorization": f"Bearer {jwt}"}, timeout=15)
                    md = r2.json()
                    raw_str = md.get("raw", "")
                    for line in raw_str.split("\n"):
                        if line.startswith("Subject:"): print(f"  Subject: {line.strip()}", flush=True)
                    clean = re.sub(r'=\r?\n', '', raw_str)
                    idx = clean.lower().find("verification code")
                    if idx >= 0:
                        snip = clean[idx:idx+500]
                        match = re.search(r'(\d{3})\s*[-–]\s*(\d{3})', snip)
                        if match: return match.group(1) + match.group(2)
                    match = re.search(r'(?<!\d)(\d{3})[-–](\d{3})(?!\d)', clean)
                    if match: return match.group(1) + match.group(2)
        except Exception as e: print(f"  poll: {e}", flush=True)
        time.sleep(2)
    return None


async def _manual_captcha_fallback(page):
    """手动完成 hCaptcha 的回退逻辑。增强版：等待验证后自动点击提交按钮。"""
    # 点击 checkbox
    vp = await page.evaluate('''() => ({w: window.innerWidth, h: window.innerHeight})''')
    vp_w, vp_h = vp["w"], vp["h"]
    x, y = int(0.353 * vp_w), int(0.773 * vp_h)
    print(f"  viewport: {vp_w}x{vp_h}, clicking checkbox at ({x}, {y})")
    await page.mouse.click(x, y)
    await asyncio.sleep(0.5)
    await page.mouse.click(x, y)

    # 等待用户手动完成
    print("  ⏳ Please solve image challenge manually...")
    captcha_solved = False
    for i in range(180):
        await asyncio.sleep(1)
        code_inputs = await page.locator('input[type="number"]').count()
        if code_inputs >= 6:
            print(f"  ✅ verification page reached ({i}s)"); return True
        has_verify = await page.evaluate('''() => {
            const t = document.body.innerText;
            return t.includes('验证您的电子邮件') ||
                   t.includes('Verify your email') ||
                   t.includes('Enter the 6-digit code');
        }''')
        if has_verify:
            print(f"  ✅ verification page detected ({i}s)"); return True

        # 检测 hCaptcha 是否已显示绿色勾号但页面未跳转
        if not captcha_solved:
            token_filled = await page.evaluate('''() => {
                const ta = document.querySelector('textarea[data-hcaptcha-response]');
                return ta && ta.value && ta.value.length > 100;
            }''')
            if token_filled:
                captcha_solved = True
                print(f"  ✅ hCaptcha solved ({i}s), clicking submit button...")
                await page.evaluate('''() => {
                    const btns = document.querySelectorAll('button[type="submit"], button');
                    const keywords = ['create account', '创建账户', '创建账号',
                                      'sign up', '注册', 'continue', '继续',
                                      'next', '下一步', 'submit', '提交'];
                    for (const btn of btns) {
                        if (!btn.offsetParent || btn.disabled) continue;
                        const t = (btn.innerText || btn.textContent || btn.value || '').toLowerCase().trim();
                        if (keywords.some(k => t.includes(k))) { btn.click(); return; }
                    }
                }''')

        if i > 0 and i % 30 == 0:
            print(f"  still waiting... ({i}s)")
    else:
        print("  ❌ hCaptcha timeout (3min)"); return False
    return True


async def register_account(page, email, mailbox):
    print("\n[1/4] Fill password...")
    for i in range(30):
        if await page.locator('#registration_password').count() > 0:
            print(f"  password field appeared ({i}s)"); break
        await asyncio.sleep(1)

    await page.fill('#registration_password', PASSWORD)
    await asyncio.sleep(0.5)
    await page.fill('#registration_passwordConfirm', PASSWORD)
    await asyncio.sleep(1)
    await page.evaluate('''() => {
        const cb = document.querySelector('#terms_and_conditions-input');
        if (cb && !cb.checked) {
            cb.checked = true;
            cb.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }''')
    print("  password + terms ✅")

    # ---- 处理 hCaptcha 验证码 ----
    print("\n[2/4] Processing hCaptcha...")
    await asyncio.sleep(3)

    if CAPTCHA_AI_ENABLED and _CAPTCHA_SOLVER_AVAILABLE and AI_VISION_API_BASE:
        # ====== AI 自动求解模式 (v2) ======
        print("  🤖 Using AI Captcha Solver v2...")
        print(f"     Backend: {AI_VISION_API_BASE}")
        try:
            solver = HCaptchaSolver(api_key=AI_VISION_API_KEY, base_url=AI_VISION_API_BASE,
                                     model=AI_VISION_MODEL)
            success = await solver.solve(page)

            if not success:
                print("  ❌ AI solver failed, falling back to manual mode...")
                await _manual_captcha_fallback(page)
            else:
                print("  ✅ AI Captcha solved!")
                # v2 solver automatically clicked form submit button
                # Wait a bit for page to advance to verification code page
                print("  ⏳ Waiting for page to advance...")
                for i in range(15):
                    await asyncio.sleep(1)
                    code_inputs = await page.locator('input[type="number"]').count()
                    if code_inputs >= 6:
                        print(f"  ✅ Verification page reached ({i+1}s)")
                        break
                    has_verify = await page.evaluate('''() => {
                        const t = document.body.innerText;
                        return t.includes('验证您的电子邮件') ||
                               t.includes('Verify your email') ||
                               t.includes('Enter the 6-digit code');
                    }''')
                    if has_verify:
                        print(f"  ✅ Verification page detected ({i+1}s)")
                        break
        except Exception as e:
            print(f"  ❌ AI solver error: {e}, falling back to manual mode...")
            await _manual_captcha_fallback(page)
    else:
        # ====== 手动求解模式（原有逻辑） ======
        if CAPTCHA_AI_ENABLED and not _CAPTCHA_SOLVER_AVAILABLE:
            print("  ⚠️ AI solver requested but core.captcha_solver not available")
        elif CAPTCHA_AI_ENABLED and not AI_VISION_API_BASE:
            print("  ⚠️ AI solver enabled but no API endpoint configured")
        print("  ⏳ Please solve image challenge manually...")
        await _manual_captcha_fallback(page)

    print("\n[3/4] Waiting for verification code email...")

    # 验证码错误重试循环
    max_retries = 3
    for attempt in range(max_retries):
        # 1) 获取新验证码（删除旧的避免错位）
        if attempt > 0:
            print(f"  🔄 Retry {attempt + 1}/{max_retries}...")
            # 标记旧的为无效，触发 provider 重新拉
            _provider._latest_code = None
            _provider._latest_message = None
            # 点击页面"重新请求新验证码"链接
            clicked_resend = await page.evaluate('''() => {
                const links = Array.from(document.querySelectorAll('a, button, span, p'));
                const resend = links.find(el => {
                    const t = (el.innerText || '').toLowerCase();
                    return t.includes('重新请求新验证码') ||
                           t.includes('请求新验证码') ||
                           t.includes('resend') ||
                           t.includes('request a new code');
                });
                if (resend) { resend.click(); return true; }
                return false;
            }''')
            print(f"  📩 resend link clicked: {clicked_resend}")
            await asyncio.sleep(5)  # 等待新邮件到达

        code = _provider.poll_code(mailbox)
        if not code:
            print(f"  ❌ No code received (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                continue
            return False
        print(f"  ✅ Code: {code}")

        # 2) 填入验证码
        await page.evaluate('''() => {
            const el = document.querySelector('[data-hcaptcha-widget-id]')?.closest('div');
            if (el) el.style.display = 'none';
        }''')
        await asyncio.sleep(1)
        for i in range(30):
            inputs = page.locator('input[type="number"]')
            if await inputs.count() >= 6:
                await page.evaluate('''(code) => {
                    const inputs = document.querySelectorAll('input[type="number"]');
                    for (let i = 0; i < 6 && i < inputs.length; i++) {
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        setter.call(inputs[i], code[i]);
                        inputs[i].dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
                    }
                }''', code)
                print("  code filled"); break
            await asyncio.sleep(1)
        else:
            print("  ⚠️ number inputs not found")
        await asyncio.sleep(2)

        # 3) 点击提交
        for text in ['Verify', 'Next', 'Continue', 'Submit', 'Confirm', '继续']:
            try:
                btn = page.locator(f'button:has-text("{text}")').first
                if await btn.count() > 0:
                    await btn.click(timeout=5000, no_wait_after=True)
                    print(f"  clicked [{text}] ✅"); break
            except: pass
        else:
            print("  no submit button found")
        # 等待页面跳转完成
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except:
            await asyncio.sleep(5)

        # 4) 检查是否进入下一步（"选择账户"/"consent"/build.nvidia.com）
        on_next = await page.evaluate('''() => {
            const t = document.body.innerText;
            return t.includes('选择账户') || t.includes('Select an account') ||
                   t.includes('I agree') || t.includes('Consent') ||
                   t.includes('Welcome') || location.href.includes('build.nvidia.com');
        }''')
        if on_next:
            print(f"  ✅ moved past verification")
            break

        # 5) 检测是否显示"验证码无效"
        invalid = await page.evaluate('''() => {
            const t = document.body.innerText;
            return t.includes('验证码无效') ||
                   t.includes('Verification code is invalid') ||
                   t.includes('invalid code') ||
                   t.includes('请尝试再次输入验证码');
        }''')
        if invalid:
            print(f"  ⚠️ Code invalid, will retry...")
            await asyncio.sleep(2)
            continue
        else:
            print(f"  ✅ verification successful")
            break
    else:
        print(f"  ❌ Failed after {max_retries} retries")
        return False

    # Post-registration: select-account / consent / build.nvidia.com
    print("\n[4/4] Post-registration pages...")

    handled_consent = False
    handled_select = False
    handled_passkey = False

    for i in range(60):
        url_now = page.url or ""
        body_text = ""
        try:
            body_text = await page.evaluate("() => document.body?.innerText || ''")
        except: pass

        # 0.5 检测 passkey 提示页 (/v1/passkey/prompt-setup)
        if not handled_passkey and ('passkey/prompt-setup' in url_now.lower() or
                                     ('创建通行密钥' in body_text and '稍后再说' in body_text)):
            print(f"  passkey prompt detected ({i}s)")
            # 第一步：点击"稍后再说"
            for t in ['稍后再说', '稍后', '稍后创建', 'Later', 'Skip', 'Not now']:
                try:
                    btn = page.locator(f'button:has-text("{t}")').first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        print(f"  ✅ clicked [{t}]")
                        await asyncio.sleep(2)
                        break
                except: pass
            # 第二步：弹窗点"确定"
            for _ in range(5):
                try:
                    for t in ['确定', 'Confirm', 'OK']:
                        btn = page.locator(f'button:has-text("{t}")').last
                        if await btn.count() > 0:
                            await btn.click(timeout=5000)
                            print(f"  ✅ clicked [{t}]")
                            handled_passkey = True
                            await asyncio.sleep(2)
                            break
                    if handled_passkey:
                        break
                except: pass
                await asyncio.sleep(1)
            continue

        # 1. 检测 consent/developer 协议页面
        if not handled_consent and (
            'developer program' in body_text.lower() or
            'developer agreement' in body_text.lower() or
            'terms of service' in body_text.lower() or
            ('consent' in url_now.lower() and 'nvidia' in url_now.lower()) or
            'noir/consent/developer' in url_now.lower()
        ):
            print(f"  consent page detected ({i}s), waiting 3s to stabilize...")
            await asyncio.sleep(3)

            # 重试提交 — 优先找绿色/提交按钮元素位置
            for retry in range(5):
                try:
                    rect = await page.evaluate(r"""() => {
                        const all = Array.from(document.querySelectorAll('button, input[type="submit"], div[role="button"], span, a'));
                        // 1) 优先找 NVIDIA 绿色按钮
                        for (const el of all) {
                            if (!el.offsetParent) continue;
                            const bg = window.getComputedStyle(el).backgroundColor;
                            if (/rgb\(\s*(1[01][0-9])\s*,\s*(1[89][0-9])\s*,\s*[0-4][0-9]\s*\)/.test(bg)) {
                                const r = el.getBoundingClientRect();
                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                            }
                        }
                        // 2) 其次找文字"提交"
                        for (const el of all) {
                            if (!el.offsetParent) continue;
                            if ((el.innerText || '').trim() === '提交') {
                                const r = el.getBoundingClientRect();
                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                            }
                        }
                        return null;
                    }""")
                except:
                    rect = None

                if rect:
                    cx, cy = int(rect["x"]), int(rect["y"])
                    print(f"  found submit at ({cx}, {cy}), clicking (attempt {retry + 1})")
                else:
                    # fallback: 硬坐标
                    cx, cy = 666, 524
                    print(f"  fallback click at ({cx}, {cy}) (attempt {retry + 1})")

                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.5)
                await page.mouse.click(cx, cy)

                # 等 5s 判断是否离开
                for wait_i in range(5):
                    await asyncio.sleep(1)
                    try:
                        url_check = page.url or ""
                    except:
                        break
                    if 'select-account' in url_check or \
                       'cloudaccounts' in url_check or \
                       'build.nvidia.com' in url_check:
                        print(f"  ✅ advanced to next page")
                        handled_consent = True
                        break
                    if 'noir/consent' not in url_check and 'consent' not in url_check.lower():
                        print(f"  ✅ left consent page")
                        handled_consent = True
                        break
                if handled_consent:
                    break
            else:
                print(f"  ⚠️ consent submit retries exhausted")
                handled_consent = True  # 不再重试

        # 2. 检测 select-account 页面
        if not handled_select and ('select-account' in url_now or 'cloudaccounts.nvidia.com' in url_now):
            print(f"  select-account page ({i}s)")
            # 尝试多种方式填写组织名
            try:
                await page.locator('input:not([type="hidden"]):not([type="number"])').first.fill("dev-org")
                await asyncio.sleep(1)
            except: pass
            await page.evaluate('''() => {
                const inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="number"])');
                for (const inp of inputs) {
                    if (inp.offsetParent !== null) {
                        inp.focus();
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, 'dev-org');
                        inp.dispatchEvent(new InputEvent('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                        inp.dispatchEvent(new Event('blur', {bubbles: true}));
                        break;
                    }
                }
            }''')
            await asyncio.sleep(1)
            try:
                for t in ['Create', 'Select', 'Confirm', 'Next', '继续', '创建']:
                    btn = page.locator(f'button:has-text("{t}")').first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        print(f"  ✅ clicked [{t}]"); handled_select = True; await asyncio.sleep(3)
                        break
            except: pass
            break

        # 3. 到达目标
        if 'build.nvidia.com' in url_now:
            print(f"  ✅ on build.nvidia.com ({i}s)"); break

        # 4. 还在验证码页 → 可能验证码不对，等待重新发送
        code_inputs = await page.locator('input[type="number"]').count()
        if code_inputs >= 6:
            print(f"  still on verification page ({i}s)...")

        await asyncio.sleep(1)
    else:
        print(f"  ⚠️ page loop ended at: {page.url[:100]}")

    print("\n🎉 Registration complete!")
    return True


async def create_api_key(page, email=None):
    global LAST_SAVE_PATH
    global LAST_ACCOUNT_SAVE_PATH
    print("\n[API Key] Post-registration setup...")

    # 0. 检查是否还在 select-account 或 consent 页面
    handled_passkey = False
    for i in range(30):
        url_now = page.url or ""
        body_text = ""
        try:
            body_text = await page.evaluate("() => document.body?.innerText || ''")
        except: pass

        # 0.5 处理 passkey 提示页 (/v1/passkey/prompt-setup)
        # 第一步：点"稍后再说"，第二步：弹窗点"确定"
        if not handled_passkey and ('passkey/prompt-setup' in url_now.lower() or
                                     ('创建通行密钥' in body_text and '稍后再说' in body_text)):
            print(f"  passkey prompt detected ({i}s)")
            # 第一步：点击"稍后再说"
            for t in ['稍后再说', '稍后', '稍后创建', 'Later', 'Skip', 'Not now']:
                try:
                    btn = page.locator(f'button:has-text("{t}")').first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        print(f"  ✅ clicked [{t}]")
                        await asyncio.sleep(2)
                        break
                except: pass
            # 第二步：弹窗点"确定"
            try:
                # 等弹窗出现
                for _ in range(5):
                    confirm_btn = page.locator('button:has-text("确定")').last
                    if await confirm_btn.count() > 0:
                        await confirm_btn.click(timeout=5000)
                        print(f"  ✅ clicked [确定] on passkey confirm dialog")
                        handled_passkey = True
                        await asyncio.sleep(2)
                        break
                    await asyncio.sleep(1)
            except: pass
            # 也尝试英文 Confirm
            if not handled_passkey:
                for t in ['Confirm', 'OK', '确定']:
                    try:
                        btn = page.locator(f'button:has-text("{t}")').last
                        if await btn.count() > 0:
                            await btn.click(timeout=5000)
                            print(f"  ✅ clicked [{t}] on passkey confirm dialog")
                            handled_passkey = True
                            await asyncio.sleep(2)
                            break
                    except: pass
            continue

        if 'select-account' in url_now or 'cloudaccounts.nvidia.com' in url_now:
            print(f"  handling select-account page...")
            try:
                await page.locator('input:not([type="hidden"]):not([type="number"])').first.fill("dev-org")
                await asyncio.sleep(1)
            except: pass
            await page.evaluate('''() => {
                const inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="number"])');
                for (const inp of inputs) {
                    if (inp.offsetParent !== null) {
                        inp.focus();
                        const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        s.call(inp, 'dev-org');
                        inp.dispatchEvent(new InputEvent('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                        break;
                    }
                }
            }''')
            await asyncio.sleep(1)
            for t in ['Create', 'Select', 'Confirm', 'Next', '继续', '创建', 'Submit']:
                try:
                    btn = page.locator(f'button:has-text("{t}")').first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        print(f"  ✅ clicked [{t}]"); await asyncio.sleep(3); break
                except: pass
            continue

        if ('consent' in url_now.lower() and 'nvidia' in url_now.lower()) or \
           'developer program' in body_text.lower() or \
           'developer agreement' in body_text.lower() or \
           '提交' in body_text or \
           'noir/consent/developer' in url_now.lower():
            print(f"  consent page detected, auto-submitting...")
            # 坐标点击"提交"按钮: 0.521 * w, 0.656 * h
            vp = await page.evaluate('''() => ({w: window.innerWidth, h: window.innerHeight})''')
            cx, cy = int(0.521 * vp["w"]), int(0.656 * vp["h"])
            print(f"  clicking submit at ({cx}, {cy})")
            await page.mouse.click(cx, cy)
            await asyncio.sleep(0.5)
            await page.mouse.click(cx, cy)
            await asyncio.sleep(3)
            continue

        if 'build.nvidia.com' in url_now:
            print(f"  ✅ on build.nvidia.com"); break
        await asyncio.sleep(1)
    else:
        # 兜底：直接导航
        print(f"  navigating to build.nvidia.com...")
        await page.goto("https://build.nvidia.com/", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)

    cookies = await page.context.cookies()
    cookie_str = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
    print(f"  cookies: {len(cookies)} items")

    print("  Step 1: GET /user-context...")
    headers = {
        "accept": "application/json, text/plain, */*",
        "cookie": cookie_str,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "origin": "https://build.nvidia.com",
        "referer": "https://build.nvidia.com/",
    }

    org_name = None
    for attempt in range(3):
        try:
            r = requests.get("https://api.ngc.nvidia.com/user-context", headers=headers, timeout=30)
        except Exception as e:
            print(f"    attempt {attempt+1}: network error {e}")
            await asyncio.sleep(2); continue
        if r.status_code != 200:
            print(f"    attempt {attempt+1}: HTTP {r.status_code}")
            await asyncio.sleep(2); continue
        data = r.json()
        org_name = data.get("orgName")
        if org_name:
            print(f"  ✅ orgName: {org_name}")
            break
        else:
            print(f"    attempt {attempt+1}: no orgName, retrying...")
            await asyncio.sleep(3)
    else:
        # 没有 orgName，尝试在浏览器中创建 org
        print("  ⚠️ no orgName from API, trying in-browser org creation...")
        try:
            await page.goto("https://build.nvidia.com/explore/account/manage-org", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            await page.locator('button:has-text("Create"),button:has-text("New")').first.click(timeout=5000)
            await asyncio.sleep(2)
            # 再次尝试
            r = requests.get("https://api.ngc.nvidia.com/user-context", headers=headers, timeout=30)
            data = r.json()
            org_name = data.get("orgName")
        except: pass

    if not org_name:
        print(f"  ❌ failed to get orgName, cannot create API Key")
        return None

    print("  Step 2: POST /keys/type/AI_PLAYGROUNDS_KEY...")
    payload = {
        "expiryDate": "2126-04-08T07:00:00Z",
        "name": "dev",
        "type": "AI_PLAYGROUNDS_KEY",
        "policies": [{
            "product": "nv-cloud-functions",
            "scopes": ["invoke_function"],
            "resources": [{"id": "*", "type": "account-functions"}],
        }],
    }
    headers["content-type"] = "application/json"
    headers["accept"] = "*/*"
    try:
        r = requests.post(f"https://api.ngc.nvidia.com/v3/orgs/{org_name}/keys/type/AI_PLAYGROUNDS_KEY",
                          json=payload, headers=headers, timeout=30)
    except Exception as e:
        print(f"  ❌ Step 2 network error: {e}"); return None
    if r.status_code not in (200, 201):
        print(f"  ❌ Step 2 failed: {r.status_code}: {r.text[:300]}"); return None

    key_data = r.json()
    api_key = (key_data.get("apiKey", {}).get("value", "") or
               key_data.get("result", {}).get("apiKey", {}).get("value", "") or
               key_data.get("keyValue", "") or
               key_data.get("key_value", ""))
    if api_key:
        print(f"\n🎉 AI_PLAYGROUNDS_KEY: {api_key}")
        save_target = resolve_key_save_target(OUTPUT_FILE, KEYS_DIR, SCRIPT_DIR)
        save_dir = save_target.path if save_target.is_directory else os.path.dirname(save_target.path)

        # ---- 模式 1: 导出纯 Key 文件 ----
        if EXPORT_KEY_ONLY:
            save_path = (
                get_output_path_in_dir(save_target.path)
                if save_target.is_directory
                else save_target.path
            )
            parent = os.path.dirname(save_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            try:
                with open(save_path, "w") as f:
                    f.write(api_key)
                print(f"   ✅ [Key] saved to: {save_path}")
                LAST_SAVE_PATH = save_path
            except PermissionError:
                fallback = get_output_path()
                with open(fallback, "w") as f:
                    f.write(api_key)
                print(f"   ⚠️ [Key] permission denied, saved to: {fallback}")
                LAST_SAVE_PATH = fallback
            except OSError as e:
                fallback = get_output_path()
                with open(fallback, "w") as f:
                    f.write(api_key)
                print(f"   ⚠️ [Key] {save_path}: {e}")
                print(f"   💾 [Key] fallback saved to: {fallback}")
                LAST_SAVE_PATH = fallback
        else:
            print(f"   ℹ️ [Key] export disabled (NV_EXPORT_KEY_ONLY=false)")

        # ---- 模式 2: 导出账号+密码+Key 完整文件 ----
        if EXPORT_ACCOUNT_FULL and email:
            account_save_path = get_account_output_path_in_dir(save_dir)
            os.makedirs(os.path.dirname(account_save_path), exist_ok=True)
            account_content = f"email: {email}\npassword: {PASSWORD}\nkey: {api_key}\n"
            try:
                with open(account_save_path, "w") as f:
                    f.write(account_content)
                print(f"   ✅ [Account] saved to: {account_save_path}")
                LAST_ACCOUNT_SAVE_PATH = account_save_path
            except PermissionError:
                fallback = os.path.join(KEYS_DIR, os.path.basename(account_save_path))
                with open(fallback, "w") as f:
                    f.write(account_content)
                print(f"   ⚠️ [Account] permission denied, saved to: {fallback}")
                LAST_ACCOUNT_SAVE_PATH = fallback
            except OSError as e:
                fallback = os.path.join(KEYS_DIR, os.path.basename(account_save_path))
                with open(fallback, "w") as f:
                    f.write(account_content)
                print(f"   ⚠️ [Account] {account_save_path}: {e}")
                print(f"   💾 [Account] fallback saved to: {fallback}")
                LAST_ACCOUNT_SAVE_PATH = fallback
        elif EXPORT_ACCOUNT_FULL and not email:
            print(f"   ⚠️ [Account] export enabled but email not available, skipped")
    else:
        print(f"  ⚠️ Key not found in response. Raw: {json.dumps(key_data, indent=2)[:500]}")

    return api_key or None


async def main():
    global CAPTCHA_AI_ENABLED

    # CLI flags (set via os.environ by subprocess launcher)
    run_index = int(os.environ.get("NV_RUN_INDEX", "1"))
    no_delay = os.environ.get("NV_NO_DELAY", "") == "1"

    if len(sys.argv) > 1:
        if sys.argv[1] == "--init":
            init_env()
            return True
        if sys.argv[1] in ("--help", "-h"):
            print(__doc__.strip())
            return True
        # 检查 --no-ai 标志（显式禁用 AI 验证码）
        for a in sys.argv[1:]:
            if a == "--no-ai":
                CAPTCHA_AI_ENABLED = False
                os.environ["CAPTCHA_AI_ENABLED"] = "false"
            if a == "--ai":
                CAPTCHA_AI_ENABLED = True
                os.environ["CAPTCHA_AI_ENABLED"] = "true"
    validate_config()
    create_provider()  # 初始化邮箱提供商
    print(f"[Run #{run_index}] 开始注册")
    print("=" * 60)
    print("NVIDIA Register + API Key Creator")
    print("-" * 60)
    print_config()
    print("=" * 60)

    async with async_playwright() as p:
        browser_info = find_chromium_executable({
            "CHROMIUM_EXECUTABLE_PATH": os.environ.get("CHROMIUM_EXECUTABLE_PATH", CHROMIUM_EXECUTABLE_PATH),
            "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", PLAYWRIGHT_BROWSERS_PATH),
            "NV_PLAYWRIGHT_BROWSERS_PATH": os.environ.get("NV_PLAYWRIGHT_BROWSERS_PATH", ""),
        })
        launch_options = {
            "headless": os.environ.get("HEADLESS", "") == "1",
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        proxy = build_playwright_proxy_from_env()
        if proxy:
            launch_options["proxy"] = proxy
            print(f"  Proxy: {proxy['server']}")
        if browser_info:
            launch_options["executable_path"] = browser_info["path"]
            print(f"  Browser: {browser_info['path']} ({browser_info['source']})")
        browser = await p.chromium.launch(**launch_options)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # 1. Create temp email via provider
        print(f"\n[1] Creating email via [{MAIL_TYPE}]...")
        try:
            mailbox = _provider.create_mailbox()
        except Exception as e:
            print(f"  ❌ Email creation failed: {e}")
            await browser.close()
            return False
        EMAIL = str(mailbox.get("address") or "")
        if not EMAIL:
            print("  ❌ Email creation failed (no address returned)")
            await browser.close()
            return False
        print(f"  ✅ Email: {EMAIL}")

        # 2. Open build.nvidia.com
        print("[2] Opening build.nvidia.com...")
        await page.goto("https://build.nvidia.com/", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(5)
        try:
            await page.locator('button:has-text("Accept All")').click(timeout=3000)
            await asyncio.sleep(2)
        except: pass
        await asyncio.sleep(3)

        # 3. Click Login
        print("[3] Click Login...")
        await page.get_by_role("button", name="Login").click(timeout=15000)
        await asyncio.sleep(8)
        print(f"  URL: {page.url[:100]}")

        # 4. Fill email
        print("[4] Fill email...")
        email_input = page.locator('input[placeholder="Enter your email ID"]')
        if await email_input.count() > 0:
            await email_input.fill(EMAIL)
        else:
            for f in page.frames:
                el = f.locator('input[placeholder="Enter your email ID"]')
                if await el.count() > 0:
                    await el.fill(EMAIL); break
        await asyncio.sleep(1)

        # 5. Click Next
        print("[5] Click Next...")
        if await page.get_by_role("button", name="Next").count() > 0:
            await page.get_by_role("button", name="Next").click(timeout=5000, no_wait_after=True)
        else:
            await page.evaluate('''() => {
                Array.from(document.querySelectorAll('button'))
                    .find(b => b.innerText.includes('Next') && b.offsetParent !== null)?.click();
            }''')
        await asyncio.sleep(6)
        print(f"  URL: {page.url[:100]}")

        # 6. Register
        ok = await register_account(page, EMAIL, mailbox)
        if not ok:
            print("\n❌ Registration failed")
            await asyncio.sleep(5)
            await browser.close()
            return False

        # 7. Create API Key
        key_result = await create_api_key(page, email=EMAIL)

        print(f"\n[Run #{run_index}] {'✅ 成功' if key_result else '⚠️ 注册成功但 Key 创建失败'}")
        if not no_delay:
            print("\nBrowser will close in 3 seconds...")
            await asyncio.sleep(3)
        await browser.close()
        return bool(key_result)


def cli_main():
    run_index = 1
    headless = False
    for a in sys.argv[1:]:
        if a.startswith("--index="):
            run_index = int(a.split("=", 1)[1])
        elif a == "--headless":
            headless = True

    os.environ["NV_RUN_INDEX"] = str(run_index)
    if headless:
        os.environ["HEADLESS"] = "1"

    try:
        success = asyncio.run(main())
        if success is False:
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
