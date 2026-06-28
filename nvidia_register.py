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
  NV_KEY_FILE      API Key 保存路径 (可选，默认: 脚本同目录)

  MAIL_TYPE=api (原有逻辑):
  EMAIL_API        邮箱服务 API 地址 (必填)
  EMAIL_AUTH       邮箱服务管理员密钥 (必填)
  EMAIL_DOMAIN     邮箱域名 (必填)

  MAIL_TYPE=duckmail (DuckMail API):
  DUCKMAIL_API_KEY DuckMail API 密钥 (必填)
  DUCKMAIL_DOMAIN  邮箱域名 (默认 duckmail.sbs)

  MAIL_TYPE=imap (DDG 别名 + IMAP):
  DDG_TOKEN        DuckDuckGo Email Protection Token (必填)
  IMAP_EMAIL       IMAP 登录邮箱 (必填)
  IMAP_KEY         IMAP 授权码 (必填)
  IMAP_HOST        IMAP 服务器 (必填, 如 imap.qq.com)
  IMAP_PORT        IMAP SSL 端口 (默认 993)
  IMAP_INBOX       收件箱名称 (默认 INBOX)
  ALIAS_DOMAIN     DDG 别名域名 (默认 duck.com)
"""

import asyncio, time, re, sys, os
import requests
from playwright.async_api import async_playwright
from mail_providers import BaseMailProvider, DuckMailProvider, ImapMailProvider

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")


def load_env():
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key not in os.environ:
                os.environ[key] = val


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

# --------------------------------------------------------------------------
# MAIL_TYPE=duckmail — DuckMail API (api.duckmail.sbs)
# --------------------------------------------------------------------------
# DUCKMAIL_API_KEY=
# DUCKMAIL_DOMAIN=duckmail.sbs

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
# 可选
# --------------------------------------------------------------------------
# NV_KEY_FILE=
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
DUCKMAIL_DOMAIN = os.environ.get("DUCKMAIL_DOMAIN", "duckmail.sbs")
DDG_TOKEN = os.environ.get("DDG_TOKEN")
IMAP_EMAIL = os.environ.get("IMAP_EMAIL")
IMAP_KEY = os.environ.get("IMAP_KEY")
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.qq.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_INBOX = os.environ.get("IMAP_INBOX", "INBOX")
ALIAS_DOMAIN = os.environ.get("ALIAS_DOMAIN", "duck.com")
PASSWORD = os.environ.get("NV_PASSWORD")
OUTPUT_FILE = os.environ.get("NV_KEY_FILE")
KEYS_DIR = os.path.join(SCRIPT_DIR, "keys")


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
            username = "nv" + str(int(time.time()))[-8:]
        resp = requests.post(
            f"{self.api_url}/admin/new_address",
            headers={"x-admin-auth": self.auth, "Content-Type": "application/json"},
            json={"name": username, "domain": self.domain, "enablePrefix": False},
            timeout=self.timeout,
        )
        d = resp.json()
        jwt = d.get("jwt", "")
        address = d.get("address", "")
        if not jwt:
            raise RuntimeError(f"Legacy API create failed: {d}")
        return {"address": address, "jwt": jwt}

    def fetch_latest_message(self, mailbox: dict) -> dict | None:
        jwt = str(mailbox.get("jwt") or "")
        try:
            r = requests.get(
                f"{self.api_url}/api/mails?limit=5&offset=0",
                headers={"Authorization": f"Bearer {jwt}"},
                timeout=self.timeout,
            )
            data = r.json()
            mails = data.get("results") or data.get("data") or []
            for mail in mails:
                mid = mail.get("id") or mail.get("_id")
                if mid:
                    r2 = requests.get(
                        f"{self.api_url}/api/mail/{mid}",
                        headers={"Authorization": f"Bearer {jwt}"},
                        timeout=self.timeout,
                    )
                    md = r2.json()
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

    print("\n[2/4] Please solve the hCaptcha manually...")
    for i in range(120):
        # 如果已经跳转到了验证码页面（6个数字输入框），说明 hCaptcha 已过，直接跳出
        code_inputs = await page.locator('input[type="number"]').count()
        if code_inputs >= 6:
            print(f"  already on verification page ({i}s)"); break

        # 检测页面文本是否已进入邮箱验证阶段
        has_verify = await page.evaluate('''() => {
            const t = document.body.innerText;
            return t.includes('验证您的电子邮件') ||
                   t.includes('Verify your email') ||
                   t.includes('Enter the 6-digit code');
        }''')
        if has_verify:
            print(f"  verification page detected ({i}s)"); break

        # 原有逻辑：检测 Create Account 按钮是否可用
        btn = await page.evaluate('''() => {
            const b = Array.from(document.querySelectorAll('button'))
                .find(b => b.innerText.includes('Create Account'));
            return b ? {disabled: b.disabled} : null;
        }''')
        if btn and not btn['disabled']:
            print(f"  hCaptcha ✅ ({i}s)"); break
        await asyncio.sleep(1)
    else:
        print("  ❌ hCaptcha timeout"); return False

    # 仅在还在注册页面时才点击 Submit
    on_register_page = await page.locator('#registration_password').count() > 0
    if on_register_page:
        print("\n[2/4] Submit registration...")
        await page.evaluate('''() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.innerText.includes('Create Account'));
            if (btn) btn.click();
        }''')
        await asyncio.sleep(3)
    else:
        print("  page already advanced, skip submit")

    print("\n[3/4] Waiting for verification code email...")
    code = _provider.poll_code(mailbox)
    if not code:
        print("  ❌ No verification code received"); return False
    print(f"  ✅ Code: {code}")
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

    # 尝试提交验证码：找 "Verify" / "Next" / "Continue" 按钮
    for text in ['Verify', 'Next', 'Continue', 'Submit', 'Confirm']:
        try:
            btn = page.locator(f'button:has-text("{text}")').first
            if await btn.count() > 0:
                await btn.click(timeout=5000)
                print(f"  clicked [{text}] ✅"); await asyncio.sleep(3); break
        except: pass
    else:
        print("  no submit button found, maybe auto-submitted")
    await asyncio.sleep(3)

    # Post-registration: select-account / consent / build.nvidia.com
    print("\n[4/4] Post-registration pages...")

    handled_consent = False
    handled_select = False

    for i in range(60):
        url_now = page.url or ""
        body_text = ""
        try:
            body_text = await page.evaluate("() => document.body?.innerText || ''")
        except: pass

        # 1. 检测 consent/developer 协议页面 (用文本而非URL)
        if not handled_consent and (
            'developer program' in body_text.lower() or
            'developer agreement' in body_text.lower() or
            'terms of service' in body_text.lower() or
            ('consent' in url_now.lower() and 'nvidia' in url_now.lower())
        ):
            print(f"  consent page detected ({i}s)")
            try:
                await page.locator('button:has-text("Accept")').first.click(timeout=5000)
                print("  ✅ accepted"); handled_consent = True; await asyncio.sleep(3)
            except:
                try:
                    await page.locator('button:has-text("Agree")').first.click(timeout=5000)
                    print("  ✅ agreed"); handled_consent = True; await asyncio.sleep(3)
                except:
                    try:
                        await page.locator('input[type="checkbox"]').first.check(timeout=3000)
                        await page.locator('button:has-text("Accept"),button:has-text("Agree"),button:has-text("Submit"),button:has-text("Continue")').first.click(timeout=5000)
                        print("  ✅ checkbox + accept"); handled_consent = True; await asyncio.sleep(3)
                    except: pass

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


async def create_api_key(page):
    print("\n[API Key] Post-registration setup...")

    # 0. 检查是否还在 select-account 或 consent 页面
    for i in range(20):
        url_now = page.url or ""
        body_text = ""
        try:
            body_text = await page.evaluate("() => document.body?.innerText || ''")
        except: pass

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
           'developer agreement' in body_text.lower():
            print(f"  handling consent page...")
            try:
                await page.locator('button:has-text("Accept")').first.click(timeout=5000)
                print("  ✅ accepted"); await asyncio.sleep(3)
            except:
                try:
                    await page.locator('button:has-text("Agree")').first.click(timeout=5000)
                    print("  ✅ agreed"); await asyncio.sleep(3)
                except: pass
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
    api_key = key_data.get("apiKey", {}).get("value", "") or key_data.get("result", {}).get("apiKey", {}).get("value", "")
    if api_key:
        print(f"\n🎉 AI_PLAYGROUNDS_KEY: {api_key}")
        save_path = OUTPUT_FILE if OUTPUT_FILE else get_output_path()
        with open(save_path, "w") as f:
            f.write(api_key)
        print(f"   saved to: {save_path}")
    else:
        print(f"  ⚠️ apiKey.value not found in response")

    return api_key or None


async def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--init":
            init_env()
            return
        if sys.argv[1] in ("--help", "-h"):
            print(__doc__.strip())
            return
    validate_config()
    create_provider()  # 初始化邮箱提供商
    print("=" * 60)
    print("NVIDIA Register + API Key Creator")
    print("-" * 60)
    print_config()
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # 1. Create temp email via provider
        print(f"\n[1] Creating email via [{MAIL_TYPE}]...")
        try:
            mailbox = _provider.create_mailbox()
        except Exception as e:
            print(f"  ❌ Email creation failed: {e}")
            await browser.close()
            return
        EMAIL = str(mailbox.get("address") or "")
        if not EMAIL:
            print("  ❌ Email creation failed (no address returned)")
            await browser.close()
            return
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
            await page.get_by_role("button", name="Next").click(timeout=5000)
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
            return

        # 7. Create API Key
        key_result = await create_api_key(page)

        print("\n" + "=" * 60)
        if key_result:
            print("✅ All done!")
        else:
            print("⚠️ Registration succeeded but API Key creation failed")
        print("=" * 60)
        print("\nBrowser will close in 10 seconds...")
        await asyncio.sleep(10)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
