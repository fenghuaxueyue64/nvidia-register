"""
邮件提供商模块 — 为 nvidia-register 提供多种邮箱服务支持。

支持的提供商:
  - DuckMailProvider:  基于 api.duckmail.sbs REST API 的临时邮箱
  - ImapMailProvider:  DuckDuckGo Email Protection 别名 + IMAP 协议读取真实邮箱

所有提供商实现统一的 BaseMailProvider 接口：create_mailbox / fetch_latest_message / poll_code
"""

import re
import time
import random
import string
import imaplib
import ipaddress
import socket
from email import message_from_bytes
from email import policy as email_policy
from urllib.parse import urlsplit

import requests


def normalize_mail_domain(domain: str | None, default: str = "duckmail.sbs") -> str:
    """Normalize user-entered mail domains such as '@duckmail.sbs'."""
    value = str(domain or "").strip()
    if not value:
        return default

    if "://" in value:
        parsed = urlsplit(value)
        value = parsed.netloc or parsed.path

    value = value.strip().strip("/")
    while value.startswith("@"):
        value = value[1:].strip()
    if "@" in value:
        value = value.rsplit("@", 1)[-1].strip()
    if "/" in value:
        value = value.split("/", 1)[0].strip()

    return value.lower() or default


def normalize_api_base(api_base: str | None, default: str = "https://api.duckmail.sbs") -> str:
    value = str(api_base or "").strip() or default
    if "://" not in value:
        value = "https://" + value
    return value.rstrip("/")


# ============================================================================
# 基类
# ============================================================================

class BaseMailProvider:
    """邮箱提供商抽象基类，定义统一接口。"""
    name: str = "base"

    def create_mailbox(self, username: str | None = None) -> dict:
        """创建邮箱，返回邮箱地址和访问凭证。"""
        raise NotImplementedError

    def fetch_latest_message(self, mailbox: dict) -> dict | None:
        """获取最新一封邮件的内容。"""
        raise NotImplementedError

    def poll_code(self, mailbox: dict, timeout: int = 180) -> str | None:
        """轮询等待验证码邮件，提取并返回 6 位验证码。"""
        deadline = time.time() + timeout
        seen_ids: set[str] = set()
        while time.time() < deadline:
            try:
                msg = self.fetch_latest_message(mailbox)
                if msg:
                    mid = msg.get("message_id", "")
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        code = self._extract_code(msg)
                        if code:
                            print(f"  ✅ Code: {code}")
                            return code
            except Exception as e:
                print(f"  poll error: {e}", flush=True)
            time.sleep(2)
        return None

    def _extract_code(self, message: dict) -> str | None:
        """从邮件内容中提取 6 位验证码，支持多种邮件格式。"""
        # 合并所有文本内容
        parts = [
            str(message.get("subject", "") or ""),
            str(message.get("text_content", "") or ""),
            str(message.get("html_content", "") or ""),
        ]
        # 若无结构化内容，尝试 raw 字段
        if not any(p.strip() for p in parts):
            raw = message.get("raw")
            if isinstance(raw, dict):
                parts.append(str(raw))
            elif isinstance(raw, str):
                parts.append(raw)

        content = "\n".join(parts)

        # 方式 1: OpenAI 特定 HTML 格式 (background-color: #F3F3F3)
        m = re.search(
            r'background-color:\s*#F3F3F3[^>]*>[\s\S]*?(\d{6})[\s\S]*?</p>',
            content, re.IGNORECASE,
        )
        if m:
            return m.group(1)

        # 方式 2: 通用验证码描述
        m = re.search(
            r'(?:Verification code|code is|代码为|验证码)[:\s]*(\d{6})',
            content, re.IGNORECASE,
        )
        if m and m.group(1) != "177010":
            return m.group(1)

        # 方式 3: XXX-XXX 格式（NVIDIA 验证码常见格式）
        m = re.search(r'(?<!\d)(\d{3})[-–](\d{3})(?!\d)', content)
        if m:
            code = m.group(1) + m.group(2)
            if code != "177010":
                return code

        # 方式 4: 6 位连续数字
        for code in re.findall(r">\s*(\d{6})\s*<|(?<![#&])\b(\d{6})\b", content):
            value = code[0] or code[1]
            if value and value != "177010":
                return value

        return None


# ============================================================================
# DuckMail Provider — 基于 api.duckmail.sbs 的临时邮箱
# ============================================================================

class DuckMailProvider(BaseMailProvider):
    """
    使用 api.duckmail.sbs 提供的 REST API:

      POST /accounts     — 创建邮箱账户
      POST /token        — 获取访问令牌
      GET  /messages     — 获取邮件列表
      GET  /messages/{id} — 获取邮件详情

    配置环境变量:
      DUCKMAIL_API_KEY   — API 密钥 (dk_xxxxx)
      DUCKMAIL_DOMAIN    — 邮箱域名 (如 duckmail.sbs / babacaowo.ndjp.net)
    """
    name = "duckmail"

    def __init__(
        self,
        api_key: str,
        domain: str = "duckmail.sbs",
        api_base: str | None = None,
        timeout: int = 30,
        retries: int = 1,
    ):
        self.api_key = api_key
        self.domain = normalize_mail_domain(domain)
        self.base_url = normalize_api_base(api_base)
        self.timeout = timeout
        self.retries = max(0, int(retries))

    # ------ 内部 HTTP ------

    def _request(
        self,
        method: str,
        path: str,
        *,
        use_api_key: bool = False,
        token: str | None = None,
        payload: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if use_api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}{path}"
        for attempt in range(self.retries + 1):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    params=params,
                    timeout=self.timeout,
                )
                break
            except requests.exceptions.RequestException as exc:
                if attempt < self.retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise RuntimeError(self._format_network_error(url, exc)) from exc
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"DuckMail API error: {resp.status_code} {resp.text[:300]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(
                f"DuckMail API returned non-JSON response from {url}: {resp.text[:300]}"
            ) from exc

    def _format_network_error(self, url: str, exc: Exception) -> str:
        parsed = urlsplit(self.base_url)
        host = parsed.hostname or "api.duckmail.sbs"
        addresses = self._resolve_host(host)
        hint = (
            "Check proxy/VPN/TUN/DNS/firewall, or set DUCKMAIL_API_BASE to a "
            "reachable DuckMail API endpoint."
        )
        if self._has_reserved_proxy_address(addresses):
            hint = (
                "DNS resolved to a reserved 198.18.0.0/15 address, which is usually "
                "from a local proxy/TUN/DNS rule. Check that proxy/VPN route first, "
                "or set DUCKMAIL_API_BASE to a reachable DuckMail API endpoint."
            )
        dns_text = f"; DNS {host} -> {', '.join(addresses)}" if addresses else ""
        return f"DuckMail API connection failed: {url}{dns_text}; {exc}; {hint}"

    @staticmethod
    def _resolve_host(host: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, 443)
        except OSError:
            return []
        addresses: list[str] = []
        for info in infos:
            try:
                ip = str(info[4][0])
            except (IndexError, TypeError):
                continue
            if ip not in addresses:
                addresses.append(ip)
        return addresses

    @staticmethod
    def _has_reserved_proxy_address(addresses: list[str]) -> bool:
        proxy_net = ipaddress.ip_network("198.18.0.0/15")
        for address in addresses:
            try:
                if ipaddress.ip_address(address) in proxy_net:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _items(data: dict) -> list:
        """兼容多种 API 返回格式。"""
        if isinstance(data, list):
            return data
        return (
            data.get("hydra:member")
            or data.get("results")
            or data.get("data")
            or []
        )

    # ------ 接口实现 ------

    def create_mailbox(self, username: str | None = None) -> dict:
        """创建临时邮箱账户并获取访问令牌。"""
        password = "".join(
            random.choices(string.ascii_letters + string.digits, k=12)
        )
        if not username:
            username = "".join(
                random.choices(string.ascii_lowercase + string.digits, k=10)
            )
        address = f"{username}@{self.domain}"
        payload = {"address": address, "password": password}

        account = self._request("POST", "/accounts", use_api_key=True, payload=payload)
        token_data = self._request("POST", "/token", use_api_key=True, payload=payload)

        return {
            "address": address,
            "token": str(token_data.get("token") or ""),
            "password": password,
            "account_id": str(account.get("id") or ""),
        }

    def fetch_latest_message(self, mailbox: dict) -> dict | None:
        """获取收件箱中最新一封邮件。"""
        token = str(mailbox.get("token") or "")
        data = self._request("GET", "/messages", token=token, params={"page": 1})
        items = self._items(data)

        if not items:
            return None

        item = items[0]
        message_id = (
            str(item.get("id") or item.get("@id") or "")
            .replace("/messages/", "")
        )
        if message_id:
            item = self._request("GET", f"/messages/{message_id}", token=token)

        return {
            "message_id": message_id,
            "subject": str(item.get("subject") or ""),
            "sender": str(item.get("from") or ""),
            "text_content": str(item.get("text") or item.get("text_content") or ""),
            "html_content": str(item.get("html") or ""),
            "raw": item,
        }


# ============================================================================
# IMAP Provider — DuckDuckGo 别名 + IMAP 读取
# ============================================================================

class ImapMailProvider(BaseMailProvider):
    """
    通过 DuckDuckGo Email Protection 创建 @duck.com 别名，
    邮件转发到真实邮箱后通过 IMAP 协议读取。

    流程:
      1. 调用 DDG API 创建邮件别名 (e.g., amulet-gas-smitten@duck.com)
      2. NVIDIA 发送验证码到该别名
      3. DDG 转发到配置的真实邮箱 (如 QQ 邮箱)
      4. 通过 IMAP 连接读取邮件并提取验证码

    配置环境变量:
      DDG_TOKEN       — DuckDuckGo Email Protection Bearer Token
      IMAP_EMAIL      — IMAP 登录邮箱
      IMAP_KEY        — IMAP 授权码 (非密码, 在邮箱设置中获取)
      IMAP_HOST       — IMAP 服务器地址 (如 imap.qq.com)
      IMAP_PORT       — IMAP SSL 端口 (默认 993)
      IMAP_INBOX      — 收件箱名称 (默认 INBOX)
      ALIAS_DOMAIN    — DDG 别名域名 (默认 duck.com)

    前置要求:
      1. 在 https://duckduckgo.com/email/ 注册并获取 DDG Token
      2. 在 DDG 设置中将转发目标设为你的真实邮箱
      3. 开启真实邮箱的 IMAP 服务并获取授权码
    """
    name = "imap"

    def __init__(
        self,
        ddg_token: str,
        imap_email: str,
        imap_key: str,
        imap_host: str,
        imap_port: int = 993,
        inbox: str = "INBOX",
        alias_domain: str = "duck.com",
        timeout: int = 30,
    ):
        self.ddg_token = ddg_token
        self.imap_email = imap_email
        self.imap_key = imap_key
        self.imap_host = imap_host
        self.imap_port = int(imap_port)
        self.inbox = inbox
        self.alias_domain = alias_domain
        self.timeout = timeout
        self.session = requests.Session()

    # ------ DDG API ------

    def _ddg_request(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict:
        resp = self.session.request(
            method.upper(),
            f"https://quack.duckduckgo.com{path}",
            headers={
                "Authorization": f"Bearer {self.ddg_token}",
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko)"
                ),
            },
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"DDG API error: {resp.status_code} {resp.text[:300]}"
            )
        return resp.json()

    # ------ 接口实现 ------

    def create_mailbox(self, username: str | None = None) -> dict:
        """调用 DDG API 创建邮件别名。"""
        ddg_data = self._ddg_request("POST", "/api/email/addresses", payload={})
        address_part = str(ddg_data.get("address") or "").strip()
        if not address_part:
            raise RuntimeError("DDG API 返回无 address 字段")

        ddg_address = f"{address_part}@{self.alias_domain}"

        return {
            "address": ddg_address,
            "imap_email": self.imap_email,
            "imap_key": self.imap_key,
            "imap_host": self.imap_host,
            "imap_port": self.imap_port,
            "inbox": self.inbox,
        }

    def fetch_latest_message(self, mailbox: dict) -> dict | None:
        """通过 IMAP 搜索发给目标别名的邮件，返回最新一封。"""
        address = str(mailbox.get("address") or "").strip().lower()
        if not address:
            return None

        mail = None
        try:
            mail = imaplib.IMAP4_SSL(
                str(mailbox["imap_host"]),
                int(mailbox["imap_port"]),
            )
            mail.login(
                str(mailbox["imap_email"]),
                str(mailbox["imap_key"]),
            )
            mail.select(str(mailbox.get("inbox") or "INBOX"))

            # IMAP 搜索: TO 或 CC 包含目标地址
            _, data = mail.search(
                None, f'(OR TO "{address}" CC "{address}")'
            )
            msg_nums = data[0].split()
            if not msg_nums:
                return None

            # 取最新一封
            latest_num = msg_nums[-1]
            _, msg_data = mail.fetch(latest_num, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = message_from_bytes(raw_email, policy=email_policy.default)

            subject = str(msg.get("Subject") or "")
            sender = str(msg.get("From") or "")

            plain_parts: list[str] = []
            html_parts: list[str] = []
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                try:
                    payload = part.get_content()
                except Exception:
                    payload = ""
                if not payload:
                    continue
                if part.get_content_type() == "text/html":
                    html_parts.append(str(payload))
                else:
                    plain_parts.append(str(payload))

            text_content = "\n".join(plain_parts).strip()
            html_content = "\n".join(html_parts).strip()

            return {
                "message_id": str(msg.get("Message-ID") or ""),
                "subject": subject,
                "sender": sender,
                "text_content": text_content,
                "html_content": html_content,
                "raw": {"subject": subject, "from": sender},
            }
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass
