#!/usr/bin/env python3
"""
nvidia-register — 一键注册 build.nvidia.com 账号并创建 AI_PLAYGROUNDS_KEY

完整的注册流程自动化：创建临时邮箱 → 填写注册表单 → 接收验证码 →
接受开发者协议 → 选择组织 → 自动创建 API Key。

用法:
  pip install -r requirements.txt
  playwright install chromium

  python3 nvidia_register.py --init       # 生成 .env 配置文件
  # 编辑 .env 填入你的邮箱服务信息
  python3 nvidia_register.py              # 自动完成注册+API Key创建

环境变量 (或 .env 文件):
  EMAIL_API       邮箱服务 API 地址 (必填)
  EMAIL_AUTH      邮箱服务管理员密钥 (必填)
  EMAIL_DOMAIN    邮箱域名 (必填)
  NV_PASSWORD   NVIDIA 账号密码 (必填)
  NV_KEY_FILE   API Key 保存路径 (可选，默认: 脚本同目录)
"""

import asyncio, time, re, sys, os
import requests
from playwright.async_api import async_playwright

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
# Required (no defaults)
EMAIL_API=
EMAIL_AUTH=
EMAIL_DOMAIN=
NV_PASSWORD=

# Optional
# NV_KEY_FILE=
"""
    with open(ENV_FILE, "w") as f:
        f.write(template)
    print(f"✅ Created {ENV_FILE}")
    print(f"   Edit it, then run: python3 nvidia_register.py")


load_env()

EMAIL_API = os.environ.get("EMAIL_API")
EMAIL_AUTH = os.environ.get("EMAIL_AUTH")
DOMAIN = os.environ.get("EMAIL_DOMAIN")
PASSWORD = os.environ.get("NV_PASSWORD")
OUTPUT_FILE = os.environ.get("NV_KEY_FILE", os.path.join(SCRIPT_DIR, "nvidia_api_key.txt"))


def validate_config():
    missing = []
    if not EMAIL_API: missing.append("EMAIL_API")
    if not EMAIL_AUTH: missing.append("EMAIL_AUTH")
    if not DOMAIN: missing.append("EMAIL_DOMAIN")
    if not PASSWORD: missing.append("NV_PASSWORD")
    if missing:
        print("❌ Missing required config:")
        for m in missing:
            print(f"   {m}")
        print()
        print("Fix:")
        print(f"  1. python3 nvidia_register.py --init")
        print(f"  2. Edit {ENV_FILE} with your credentials")
        print(f"  3. python3 nvidia_register.py")
        print()
        print("Or pass via env:")
        print("  EMAIL_API=... EMAIL_AUTH=... EMAIL_DOMAIN=... NV_PASSWORD=... python3 nvidia_register.py")
        sys.exit(1)


def print_config():
    print(f"  EMAIL_API:     {EMAIL_API}")
    print(f"  DOMAIN:      {DOMAIN}")
    print(f"  PASSWORD:    {'*' * 6}")
    print(f"  OUTPUT_FILE: {OUTPUT_FILE}")
    print(f"  ENV_FILE:    {ENV_FILE}")


def poll_code(jwt, timeout=180):
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


async def register_account(page, email, jwt_token):
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

    print("\n[2/4] Submit registration...")
    await page.evaluate('''() => {
        const btn = Array.from(document.querySelectorAll('button'))
            .find(b => b.innerText.includes('Create Account'));
        if (btn) btn.click();
    }''')
    await asyncio.sleep(3)

    print("\n[3/4] Waiting for verification code email...")
    code = poll_code(jwt_token)
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

    for text in ['Continue', 'Submit', 'Create']:
        try:
            await page.locator(f'button:has-text("{text}")').first.click(timeout=5000)
            print(f"  clicked [{text}] ✅"); await asyncio.sleep(3)
        except:
            print(f"  clicked [{text}] — skipped")

    await asyncio.sleep(3)

    # Post-registration: select-account / consent / build.nvidia.com
    print("\n[4/4] Post-registration pages...")
    for i in range(30):
        url_now = page.url
        if 'consent' in url_now or 'static-login.nvidia.com' in url_now:
            print(f"  consent page ({i}s)")
            try:
                await page.locator('button:has-text("Accept"),button:has-text("Agree"),button:has-text("继续"),button:has-text("同意")').first.click(timeout=5000)
                print("  ✅ accepted"); await asyncio.sleep(3)
            except: pass
            break
        elif 'select-account' in url_now or 'cloudaccounts.nvidia.com' in url_now:
            print(f"  select-account page ({i}s)")
            await page.evaluate('''() => {
                const inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="number"])');
                for (const inp of inputs) {
                    if (inp.offsetParent !== null && inp.value !== undefined) {
                        inp.focus();
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, 'Alex Chen');
                        inp.dispatchEvent(new InputEvent('input', {bubbles: true}));
                        break;
                    }
                }
            }''')
            await asyncio.sleep(1)
            try:
                btn = page.locator('button:has-text("Create"),button:has-text("Select"),button:has-text("继续"),button:has-text("创建")').first
                await btn.click(timeout=5000)
                print("  ✅ account created"); await asyncio.sleep(3)
            except: print("  create button not found")
            break
        elif 'build.nvidia.com' in url_now:
            print(f"  already on build.nvidia.com ({i}s)"); break
        await asyncio.sleep(1)
    else:
        print(f"  unknown page: {page.url[:80]}")

    print("\n🎉 Registration complete!")
    return True


async def create_api_key(page):
    print("\n[API Key] Waiting for build.nvidia.com...")
    for i in range(30):
        if 'build.nvidia.com' in page.url:
            print(f"  ✅ on build.nvidia.com ({i}s)")
            break
        await asyncio.sleep(1)
    else:
        print(f"  current page: {page.url[:80]}")
        print("  navigating to build.nvidia.com...")
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
    try:
        r = requests.get("https://api.ngc.nvidia.com/user-context", headers=headers, timeout=30)
    except Exception as e:
        print(f"  ❌ Step 1 network error: {e}"); return None
    if r.status_code != 200:
        print(f"  ❌ Step 1 failed: {r.status_code}: {r.text[:200]}"); return None
    data = r.json()
    org_name = data.get("orgName")
    if not org_name:
        print(f"  ❌ no orgName in response: {data}"); return None
    print(f"  ✅ orgName: {org_name}")

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
        with open(OUTPUT_FILE, "w") as f:
            f.write(api_key)
        print(f"   saved to: {OUTPUT_FILE}")
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

        # 1. Create temp email
        name = "nv" + str(int(time.time()))[-8:]
        try:
            resp = requests.post(f"{EMAIL_API}/admin/new_address",
                headers={"x-admin-auth": EMAIL_AUTH, "Content-Type": "application/json"},
                json={"name": name, "domain": DOMAIN, "enablePrefix": False}, timeout=15)
        except Exception as e:
            print(f"  ❌ Email creation failed: {e}")
            print(f"     check EMAIL_API ({EMAIL_API}) and server connectivity")
            await browser.close()
            return
        d = resp.json()
        EMAIL, JWT = d.get("address", ""), d.get("jwt", "")
        if not JWT:
            print(f"  ❌ Email creation failed (check EMAIL_API / EMAIL_AUTH)")
            print(f"     response: {d}")
            await browser.close()
            return
        print(f"\n[1] Email: {EMAIL}")

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
        ok = await register_account(page, EMAIL, JWT)
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
