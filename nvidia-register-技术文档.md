# NVIDIA BUILD 注册自动化 — 技术文档

> **项目**: nvidia-register
> **版本**: 基于 commit `3e2cd62`
> **最后更新**: 2026-06-30

---

## 目录

1. [项目概述](#1-项目概述)
2. [架构总览](#2-架构总览)
3. [环境配置](#3-环境配置)
4. [邮箱提供商体系](#4-邮箱提供商体系)
   - 4.1 [BaseMailProvider 抽象基类](#41-basemailprovider-抽象基类)
   - 4.2 [LegacyApiProvider — 自建临时邮箱 API](#42-legacyapiprovider--自建临时邮箱-api)
   - 4.3 [DuckMailProvider — DuckMail REST API](#43-duckmailprovider--duckmail-rest-api)
   - 4.4 [ImapMailProvider — DuckDuckGo 别名 + IMAP](#44-Imapmailprovider--duckduckgo-别名--imap)
5. [API 接口详细文档](#5-api-接口详细文档)
   - 5.1 [LegacyApi 自建邮箱 API](#51-legacyapi-自建邮箱-api)
   - 5.2 [DuckMail API](#52-duckmail-api)
   - 5.3 [DuckDuckGo Email Protection API](#53-duckduckgo-email-protection-api)
   - 5.4 [IMAP 协议接口](#54-imap-协议接口)
   - 5.5 [NVIDIA NGC API](#55-nvidia-ngc-api)
6. [验证码提取机制](#6-验证码提取机制)
7. [注册流程详解](#7-注册流程详解)
8. [API Key 创建流程](#8-api-key-创建流程)
9. [关键文件说明](#9-关键文件说明)
10. [依赖项](#10-依赖项)
11. [错误处理与容错机制](#11-错误处理与容错机制)
12. [安全性注意事项](#12-安全性注意事项)

---

## 1. 项目概述

本项目自动化完成 NVIDIA BUILD 平台 (`build.nvidia.com`) 的账号注册与 `AI_PLAYGROUNDS_KEY` API Key 的创建。整个流程无需人工干预（除了 hCaptcha 验证码需手动解决），实现从临时邮箱创建到 API Key 文件输出的端到端自动化。

**核心能力**:

| 能力 | 说明 |
|------|------|
| 临时邮箱创建 | 支持三种邮箱后端：自建API / DuckMail / DDG+IMAP |
| 浏览器自动化 | 基于 Playwright Chromium，含反检测措施 |
| 验证码提取 | 4级正则策略自动提取 6 位验证码 |
| hCaptcha 处理 | 等待用户手动完成，自动检测通过状态 |
| API Key 创建 | 注册完成后自动调用 NGC API 生成 Key |
| Key 文件输出 | 按 `keys/nvidia_api_key_N_时间戳.txt` 保存 |

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        nvidia_register.py (主入口)                    │
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐              │
│  │ load_env │──▶│validate_config│──▶│create_provider│              │
│  └──────────┘    └──────────────┘    └───────┬───────┘              │
│                                              │                      │
│  ┌───────────────────────────────────────────▼──────────────────┐  │
│  │                    main() 异步主流程                          │  │
│  │                                                              │  │
│  │  [1] create_mailbox()  ──▶  临时邮箱地址                      │  │
│  │  [2] Playwright 打开 build.nvidia.com                        │  │
│  │  [3] 点击 Login                                              │  │
│  │  [4] 填写邮箱                                                │  │
│  │  [5] 点击 Next                                               │  │
│  │  [6] register_account()                                      │  │
│  │      ├── [1/4] 填写密码 + 同意条款                            │  │
│  │      ├── [2/4] 等待 hCaptcha 手动完成                         │  │
│  │      ├── [3/4] poll_code() 提取验证码 + 填入                 │  │
│  │      └── [4/4] 处理后续页面 (consent / org / build)          │  │
│  │  [7] create_api_key()                                        │  │
│  │      ├── 处理残留页面                                        │  │
│  │      ├── GET /user-context → orgName                         │  │
│  │      └── POST /keys/type/AI_PLAYGROUNDS_KEY → apiKey         │  │
│  │  [8] 保存 Key 文件 + 关闭浏览器                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     mail_providers.py (邮箱模块)                     │
│                                                                     │
│  ┌──────────────────┐                                              │
│  │ BaseMailProvider  │  抽象基类: create_mailbox /                  │
│  │    (abstract)     │  fetch_latest_message / poll_code           │
│  └────────┬─────────┘                                              │
│           │                                                         │
│  ┌────────┼─────────────────────┐                                  │
│  │        │                     │                                   │
│  ▼        ▼                     ▼                                   │
│ DuckMail   ImapMail       LegacyApi                                │
│ Provider   Provider       Provider                                │
│            (nvidia_register.py 内)                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 环境配置

### 3.1 配置文件

使用 `.env` 文件管理环境变量，通过 `load_env()` 手工解析（非 python-dotenv）。**已存在的环境变量不会被 `.env` 覆盖**——系统环境变量优先级更高。

初始化模板:

```bash
python nvidia_register.py --init   # 生成 .env 模板
```

### 3.2 环境变量一览

| 变量名 | 默认值 | 必填 | 适用 MAIL_TYPE | 说明 |
|--------|--------|------|----------------|------|
| `MAIL_TYPE` | `api` | 是 | 通用 | 邮箱服务类型: `api` / `duckmail` / `imap` |
| `NV_PASSWORD` | — | 是 | 通用 | NVIDIA 账号密码 |
| `NV_KEY_FILE` | — | 否 | 通用 | API Key 自定义保存路径 |
| `EMAIL_API` | — | 是* | `api` | 自建邮箱服务 API 地址 |
| `EMAIL_AUTH` | — | 是* | `api` | 自建邮箱服务管理员密钥 |
| `EMAIL_DOMAIN` | — | 是* | `api` | 邮箱域名 |
| `DUCKMAIL_API_KEY` | — | 是* | `duckmail` | DuckMail API 密钥 (格式: `dk_xxxxx`) |
| `DUCKMAIL_DOMAIN` | `duckmail.sbs` | 否 | `duckmail` | 邮箱域名 |
| `DDG_TOKEN` | — | 是* | `imap` | DuckDuckGo Email Protection Token |
| `IMAP_EMAIL` | — | 是* | `imap` | IMAP 登录邮箱 |
| `IMAP_KEY` | — | 是* | `imap` | IMAP 授权码 (非邮箱密码) |
| `IMAP_HOST` | `imap.qq.com` | 否 | `imap` | IMAP 服务器地址 |
| `IMAP_PORT` | `993` | 否 | `imap` | IMAP SSL 端口 |
| `IMAP_INBOX` | `INBOX` | 否 | `imap` | 收件箱名称 |
| `ALIAS_DOMAIN` | `duck.com` | 否 | `imap` | DDG 别名域名 |

> \* 必填仅当 `MAIL_TYPE` 选中该类型时生效，由 `validate_config()` 校验。

### 3.3 配置校验逻辑

`validate_config()` 函数在启动时执行以下校验:

1. **通用字段**: `NV_PASSWORD` 必填
2. **按类型校验**:
   - `api` → `EMAIL_API`, `EMAIL_AUTH`, `EMAIL_DOMAIN` 必填
   - `duckmail` → `DUCKMAIL_API_KEY`, `DUCKMAIL_DOMAIN` 必填
   - `imap` → `DDG_TOKEN`, `IMAP_EMAIL`, `IMAP_KEY`, `IMAP_HOST` 必填
3. **非法类型**: 退出并提示有效值

---

## 4. 邮箱提供商体系

所有邮箱提供商继承自 `BaseMailProvider`，实现统一的三个接口方法。全局单例 `_provider` 由 `create_provider()` 根据 `MAIL_TYPE` 创建。

### 4.1 BaseMailProvider 抽象基类

**文件**: `mail_providers.py:26-106`

```python
class BaseMailProvider:
    name: str = "base"

    def create_mailbox(self, username: str | None = None) -> dict
    def fetch_latest_message(self, mailbox: dict) -> dict | None
    def poll_code(self, mailbox: dict, timeout: int = 180) -> str | None
    def _extract_code(self, message: dict) -> str | None
```

#### 接口规范

| 方法 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `create_mailbox` | `username` (可选) | `dict` — 至少含 `"address"` 键 | 创建邮箱，返回地址和凭证 |
| `fetch_latest_message` | `mailbox` (create_mailbox 返回的 dict) | `dict \| None` — 标准消息格式 | 获取最新邮件内容 |
| `poll_code` | `mailbox`, `timeout` (默认 180s) | `str \| None` — 6位验证码字符串 | 轮询提取验证码 |

#### 标准消息格式

```json
{
  "message_id": "唯一标识符 (用于去重)",
  "subject": "邮件主题",
  "sender": "发件人",
  "text_content": "纯文本内容",
  "html_content": "HTML 内容",
  "raw": "原始数据 (格式由提供商决定)"
}
```

#### poll_code 轮询算法

```
deadline = now + timeout
seen_ids = ∅
while now < deadline:
    msg = fetch_latest_message(mailbox)
    if msg && msg.message_id ∉ seen_ids:
        seen_ids.add(msg.message_id)
        code = _extract_code(msg)
        if code: return code
    sleep(2)
return None
```

- **轮询间隔**: 2 秒
- **去重机制**: 基于 `message_id` 集合，避免重复处理同一封邮件
- **超时时间**: 默认 180 秒 (3 分钟)

---

### 4.2 LegacyApiProvider — 自建临时邮箱 API

**文件**: `nvidia_register.py:241-301`

为兼容旧版自建邮箱 API 而设计的适配器。继承 `BaseMailProvider`，内嵌于 `nvidia_register.py`。

| 属性 | 值 |
|------|-----|
| `name` | `"legacy_api"` |
| 认证方式 | 管理员密钥 (`x-admin-auth` 请求头) + JWT (`Bearer` 请求头) |
| 邮箱创建 | `POST /admin/new_address` — 返回 `{address, jwt}` |
| 邮件读取 | `GET /api/mails` (列表) → `GET /api/mail/{id}` (详情) |
| 特殊行为 | `username` 默认为 `"nv" + 时间戳后8位` |

**返回的 mailbox 结构**:

```json
{
  "address": "nv12345678@domain.com",
  "jwt": "eyJhbGciOiJIUzI1NiJ9..."
}
```

**fetch_latest_message 特殊行为**:
- `text_content` 字段存储的是原始邮件源码 (`raw` 字段值)
- `subject` 通过逐行匹配 `"Subject:"` 头从原始源码中提取
- `html_content` 始终为空字符串

---

### 4.3 DuckMailProvider — DuckMail REST API

**文件**: `mail_providers.py:112-230`

基于 `api.duckmail.sbs` 的临时邮箱服务。

| 属性 | 值 |
|------|-----|
| `name` | `"duckmail"` |
| Base URL | `https://api.duckmail.sbs` |
| 认证方式 | API Key (创建/认证) + Account Token (邮件读取) |
| 邮箱创建 | `POST /accounts` → `POST /token` 两步式 |

**构造参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | `str` | — | DuckMail API 密钥 |
| `domain` | `str` | `duckmail.sbs` | 邮箱域名 |
| `timeout` | `int` | `30` | 请求超时 (秒) |

**内部 HTTP 方法**:

```python
def _request(self, method, path, *, use_api_key=False, token=None,
             payload=None, params=None) -> dict
```

- `use_api_key=True` → `Authorization: Bearer {api_key}` (用于 `/accounts` 和 `/token`)
- `token=xxx` → `Authorization: Bearer {token}` (用于 `/messages`)
- 状态码仅接受 `200` / `201`，否则抛出 `RuntimeError`

**响应格式兼容方法 `_items()`**:

DuckMail API 可能返回三种格式，`_items()` 自动处理:

| 响应格式 | 提取键 | 场景 |
|----------|--------|------|
| JSON-API | `hydra:member` | JSON-LD 兼容 API |
| 分页 | `results` | 分页返回 |
| 通用 | `data` | 通用 data 包装 |
| 原生 | 直接 list | 无包装列表 |

**create_mailbox 流程**:

```
1. 生成 12 位随机密码 (a-zA-Z0-9)
2. 生成 10 位随机用户名 (a-z0-9) (如未提供)
3. POST /accounts  →  账户注册
4. POST /token     →  获取 Bearer Token
5. 返回 {address, token, password, account_id}
```

**返回的 mailbox 结构**:

```json
{
  "address": "abc1234567@duckmail.sbs",
  "token": "eyJhbGciOiJIUzI1NiJ9...",
  "password": "aB3dE7fG9hK2",
  "account_id": "12345"
}
```

**fetch_latest_message 流程**:

```
1. GET /messages?page=1  (使用 account token)
2. 通过 _items() 提取消息列表
3. 取第一条消息的 id
4. GET /messages/{id}  (获取完整内容)
5. 返回标准消息格式
```

---

### 4.4 ImapMailProvider — DuckDuckGo 别名 + IMAP

**文件**: `mail_providers.py:237-397`

组合使用 DuckDuckGo Email Protection 创建临时别名 + IMAP 协议从真实邮箱中读取转发邮件。

| 属性 | 值 |
|------|-----|
| `name` | `"imap"` |
| 别名 API | `https://quack.duckduckgo.com/api/email/addresses` |
| 邮件读取 | IMAP4_SSL 协议 |
| 认证方式 | DDG: Bearer Token; IMAP: 授权码 (非密码) |

**架构原理**:

```
NVIDIA 发验证码 → xxx@duck.com (DDG 别名)
                               ↓
                        DDG 自动转发
                               ↓
                   真实邮箱 (如 QQ 邮箱)
                               ↓
                    IMAP4_SSL 读取
                               ↓
                      提取验证码
```

**构造参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ddg_token` | `str` | — | DuckDuckGo Email Protection Bearer Token |
| `imap_email` | `str` | — | IMAP 登录邮箱 |
| `imap_key` | `str` | — | IMAP 授权码 (邮箱设置中生成) |
| `imap_host` | `str` | `imap.qq.com` | IMAP 服务器 |
| `imap_port` | `int` | `993` | IMAP SSL 端口 |
| `inbox` | `str` | `INBOX` | 收件箱名称 |
| `alias_domain` | `str` | `duck.com` | DDG 别名域名 |
| `timeout` | `int` | `30` | 请求超时 (秒) |

**create_mailbox 流程**:

```
1. POST https://quack.duckduckgo.com/api/email/addresses  (空 JSON body)
2. 提取响应中的 address 字段 (如 "amulet-gas-smitten")
3. 拼接完整地址: address@{alias_domain}
4. 返回 {address, imap_email, imap_key, imap_host, imap_port, inbox}
```

**返回的 mailbox 结构**:

```json
{
  "address": "amulet-gas-smitten@duck.com",
  "imap_email": "user@qq.com",
  "imap_key": "authorization_code",
  "imap_host": "imap.qq.com",
  "imap_port": 993,
  "inbox": "INBOX"
}
```

**fetch_latest_message 流程 (IMAP)**:

```
1. 建立 IMAP4_SSL 连接
2. LOGIN (使用 imap_email + imap_key)
3. SELECT inbox
4. SEARCH (OR TO "alias@duck.com" CC "alias@duck.com")
5. 取最新一条消息的序号 (最后一个)
6. FETCH {序号} (RFC822)
7. 解析 MIME 消息:
   - 遍历 multipart 部分
   - 分离 text/plain 和 text/html
8. LOGOUT (保证在 finally 中执行)
9. 返回标准消息格式
```

**连接管理**:
- 每次调用 `fetch_latest_message` 建立新的 IMAP 连接
- 无论成功与否，`finally` 块保证执行 `mail.logout()`
- 无持久连接池，轮询期间反复连接/断开

---

## 5. API 接口详细文档

### 5.1 LegacyApi 自建邮箱 API

**Base URL**: 由 `EMAIL_API` 环境变量指定

#### 5.1.1 创建邮箱地址

```
POST {EMAIL_API}/admin/new_address
```

| 项 | 值 |
|----|-----|
| Content-Type | `application/json` |
| x-admin-auth | `{EMAIL_AUTH}` 管理员密钥 |

**请求体**:

```json
{
  "name": "nv12345678",
  "domain": "your-domain.com",
  "enablePrefix": false
}
```

**成功响应** (`200`):

```json
{
  "jwt": "eyJhbGciOiJIUzI1NiJ9...",
  "address": "nv12345678@your-domain.com"
}
```

**错误处理**: `jwt` 字段为空时抛出 `RuntimeError`

---

#### 5.1.2 获取邮件列表

```
GET {EMAIL_API}/api/mails?limit=5&offset=0
```

| 项 | 值 |
|----|-----|
| Authorization | `Bearer {jwt}` |

**成功响应** (`200`):

```json
{
  "results": [
    { "id": "msg_001", "_id": "msg_001", ... }
  ]
}
```

> 也兼容 `data` 键: `{"data": [...]}`

---

#### 5.1.3 获取单封邮件详情

```
GET {EMAIL_API}/api/mail/{id}
```

| 项 | 值 |
|----|-----|
| Authorization | `Bearer {jwt}` |

**成功响应** (`200`):

```json
{
  "raw": "From: noreply@nvidia.com\r\nSubject: Verify...\r\n\r\nYour code is 123-456..."
}
```

---

### 5.2 DuckMail API

**Base URL**: `https://api.duckmail.sbs`

#### 5.2.1 创建邮箱账户

```
POST /accounts
```

| 项 | 值 |
|----|-----|
| Content-Type | `application/json` |
| Authorization | `Bearer {DUCKMAIL_API_KEY}` |

**请求体**:

```json
{
  "address": "username@duckmail.sbs",
  "password": "randomPassword12"
}
```

**成功响应** (`200` / `201`):

```json
{
  "id": "12345",
  "address": "username@duckmail.sbs"
}
```

---

#### 5.2.2 获取访问令牌

```
POST /token
```

| 项 | 值 |
|----|-----|
| Content-Type | `application/json` |
| Authorization | `Bearer {DUCKMAIL_API_KEY}` |

**请求体**:

```json
{
  "address": "username@duckmail.sbs",
  "password": "randomPassword12"
}
```

**成功响应** (`200`):

```json
{
  "token": "eyJhbGciOiJIUzI1NiJ9...",
  ...
}
```

---

#### 5.2.3 获取邮件列表

```
GET /messages?page=1
```

| 项 | 值 |
|----|-----|
| Authorization | `Bearer {account_token}` |

**成功响应** (`200`):

可能为以下任一格式:

```json
// 格式 A: JSON-LD / Hydra
{
  "hydra:member": [
    { "id": "msg_001", "subject": "...", "from": "..." }
  ]
}

// 格式 B: 分页
{
  "results": [
    { "id": "msg_001", ... }
  ]
}

// 格式 C: 通用
{
  "data": [
    { "id": "msg_001", ... }
  ]
}
```

> `_items()` 方法自动兼容以上三种格式。

---

#### 5.2.4 获取邮件详情

```
GET /messages/{id}
```

| 项 | 值 |
|----|-----|
| Authorization | `Bearer {account_token}` |

**成功响应** (`200`):

```json
{
  "id": "msg_001",
  "subject": "NVIDIA - Verify your email",
  "from": "noreply@nvidia.com",
  "text": "Your verification code is 123-456",
  "html": "<p>Your verification code is <b>123-456</b></p>"
}
```

> 字段名也兼容 `text_content` (自动降级读取 `text`)。

---

### 5.3 DuckDuckGo Email Protection API

**Base URL**: `https://quack.duckduckgo.com`

#### 5.3.1 创建邮件别名

```
POST /api/email/addresses
```

| 项 | 值 |
|----|-----|
| Content-Type | `application/json` |
| Authorization | `Bearer {DDG_TOKEN}` |
| User-Agent | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...` |

**请求体**:

```json
{}
```

**成功响应** (`200` / `201`):

```json
{
  "address": "amulet-gas-smitten"
}
```

> 注意: 返回的 `address` **不含域名**，客户端需自行拼接 `@{alias_domain}`。

**前置要求**:
1. 在 `https://duckduckgo.com/email/` 注册 DuckDuckGo Email Protection
2. 获取 Bearer Token (从浏览器 DevTools 或官方 API)
3. 在 DDG 设置中配置转发目标为真实邮箱

---

### 5.4 IMAP 协议接口

用于 `ImapMailProvider.fetch_latest_message()` 的 IMAP 操作序列:

| 步骤 | 操作 | 参数 | 说明 |
|------|------|------|------|
| 1 | `IMAP4_SSL(host, port)` | `imap_host`, `imap_port` | 建立 SSL 加密连接 |
| 2 | `login(email, key)` | `imap_email`, `imap_key` | 使用授权码登录 (非邮箱密码) |
| 3 | `select(inbox)` | `IMAP_INBOX` (默认 INBOX) | 选择收件箱 |
| 4 | `search(None, criteria)` | `(OR TO "alias@duck.com" CC "alias@duck.com")` | 搜索发给别名的邮件 |
| 5 | `fetch(num, "(RFC822)")` | 最新消息序号 | 获取完整 RFC822 原始邮件 |
| 6 | `logout()` | — | 断开连接 (在 finally 中保证执行) |

**搜索条件详解**:

```
(OR TO "alias@duck.com" CC "alias@duck.com")
```

- 搜索 TO 或 CC 字段包含目标别名地址的邮件
- 使用 `msg_nums[-1]` 取搜索结果中**最后一条** (即最新邮件)
- 每次搜索覆盖整个收件箱，不依赖 UID 持久化

**MIME 解析**:
- 使用 Python 标准库 `email.message_from_bytes()` 解析
- 遍历 `msg.walk()` 处理 multipart 消息
- 分离 `text/plain` 和 `text/html` 两种内容类型
- 合并同类型的多个 part (如 multipart/alternative 中的多个纯文本部分)

---

### 5.5 NVIDIA NGC API

**Base URL**: `https://api.ngc.nvidia.com`

用于注册完成后自动创建 `AI_PLAYGROUNDS_KEY`。

#### 5.5.1 获取用户上下文 (orgName)

```
GET /user-context
```

| 项 | 值 |
|----|-----|
| accept | `application/json, text/plain, */*` |
| cookie | 浏览器全部 Cookie (从 Playwright context 提取) |
| user-agent | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36` |
| origin | `https://build.nvidia.com` |
| referer | `https://build.nvidia.com/` |

**成功响应** (`200`):

```json
{
  "orgName": "dev-org-c1a2b3",
  ...
}
```

> `orgName` 是后续创建 API Key 的必需参数。最多重试 3 次，每次间隔 2-3 秒。

**降级策略**: 若 3 次重试均未获取到 `orgName`，尝试在浏览器中访问 `/explore/account/manage-org` 创建组织后再请求。

---

#### 5.5.2 创建 AI_PLAYGROUNDS_KEY

```
POST /v3/orgs/{orgName}/keys/type/AI_PLAYGROUNDS_KEY
```

| 项 | 值 |
|----|-----|
| Content-Type | `application/json` |
| accept | `*/*` |
| cookie | 浏览器全部 Cookie |
| user-agent | 同上 |
| origin | `https://build.nvidia.com` |
| referer | `https://build.nvidia.com/` |

**请求体**:

```json
{
  "expiryDate": "2126-04-08T07:00:00Z",
  "name": "dev",
  "type": "AI_PLAYGROUNDS_KEY",
  "policies": [{
    "product": "nv-cloud-functions",
    "scopes": ["invoke_function"],
    "resources": [{
      "id": "*",
      "type": "account-functions"
    }]
  }]
}
```

**请求体字段说明**:

| 字段 | 值 | 说明 |
|------|-----|------|
| `expiryDate` | `2126-04-08T07:00:00Z` | 过期时间 (100 年后) |
| `name` | `dev` | Key 名称 |
| `type` | `AI_PLAYGROUNDS_KEY` | Key 类型标识 |
| `policies[].product` | `nv-cloud-functions` | 授权产品 |
| `policies[].scopes` | `["invoke_function"]` | 授权范围 |
| `policies[].resources[].id` | `*` | 通配所有资源 |
| `policies[].resources[].type` | `account-functions` | 资源类型 |

**成功响应** (`200` / `201`):

```json
{
  "apiKey": {
    "value": "nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}
```

> 也兼容 `result.apiKey.value` 嵌套格式:

```json
{
  "result": {
    "apiKey": {
      "value": "nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

---

## 6. 验证码提取机制

**文件**: `mail_providers.py:58-105`

`BaseMailProvider._extract_code()` 方法实现 4 级正则匹配策略，按优先级顺序尝试:

### 策略 1: OpenAI 特定 HTML 格式

```
正则: background-color:\s*#F3F3F3[^>]*>[\s\S]*?(\d{6})[\s\S]*?</p>
标志: re.IGNORECASE
```

匹配 OpenAI 风格验证码邮件中灰色背景 HTML 块内的 6 位数字。

### 策略 2: 通用验证码描述文本

```
正则: (?:Verification code|code is|代码为|验证码)[:\s]*(\d{6})
标志: re.IGNORECASE
排除: "177010" (误匹配防护)
```

匹配多种语言的验证码描述文本后的 6 位数字。

### 策略 3: NVIDIA XXX-XXX 格式 ⭐ (最常命中)

```
正则: (?<!\d)(\d{3})[-–](\d{3})(?!\d)
排除: "177-010" → "177010" (误匹配防护)
合并: group(1) + group(2) → "123456"
```

NVIDIA 验证码邮件中最常见的格式，如 `123-456` 或 `123–456` (支持短横线和长破折号)。

### 策略 4: 通用 6 位数字

```
正则: >\s*(\d{6})\s*<|(?<![#&])\b(\d{6})\b
排除: "177010" (误匹配防护)
```

两种匹配模式:
- `>\s*(\d{6})\s*<` — HTML 标签之间的 6 位数字
- `(?<![#&])\b(\d{6})\b` — 独立的 6 位数字 (排除 HTML entity 如 `&#177010;`)

### 提取内容来源

```python
parts = [subject, text_content, html_content]
# 若以上均为空，尝试 raw 字段
if not any(p.strip() for p in parts):
    raw = message.get("raw")
    # raw 为 dict → 转 str; raw 为 str → 直接用
content = "\n".join(parts)
```

### 误匹配防护

常量 `"177010"` 在策略 2/3/4 中被全局排除，因为该数字序列常见于邮件元数据或 HTML 实体编码中，不是有效的验证码。

---

## 7. 注册流程详解

### 7.1 流程全景

```
┌─[1]─┐   ┌─[2]─┐   ┌─[3]─┐   ┌─[4]─┐   ┌─[5]─┐   ┌────[6]──────────────┐   ┌─[7]─┐
│创建  │──▶│打开  │──▶│点击  │──▶│填写  │──▶│点击  │──▶│register_account()  │──▶│创建  │
│邮箱  │   │网站  │   │Login │   │邮箱  │   │Next  │   │  (4步子流程)       │   │Key   │
└─────┘   └─────┘   └─────┘   └─────┘   └─────┘   └───────────────────┘   └─────┘
```

### 7.2 步骤详解

#### [1] 创建临时邮箱

- 调用 `_provider.create_mailbox()`
- 根据 `MAIL_TYPE` 分发到对应的提供商实现
- 失败时立即关闭浏览器并退出

#### [2] 打开 build.nvidia.com

- Playwright 启动 Chromium，参数:
  - `headless=False` — 必须可见 (hCaptcha 需要人工交互)
  - `--no-sandbox` — 沙箱禁用
  - `--disable-blink-features=AutomationControlled` — 反浏览器自动化检测
- 视口: `1280 × 800`
- 等待 `networkidle`，超时 90 秒
- 自动点击 "Accept All" Cookie 同意按钮 (如有)

#### [3] 点击 Login

- 使用 `page.get_by_role("button", name="Login")` 定位
- 点击后等待 8 秒

#### [4] 填写邮箱

- 定位选择器: `input[placeholder="Enter your email ID"]`
- 先在顶层页面搜索，未找到则在所有 `<iframe>` 中搜索
- 使用 `fill()` 方法填入临时邮箱地址

#### [5] 点击 Next

- 优先使用 `get_by_role("button", name="Next")`
- 降级使用 JavaScript 查找包含 "Next" 文本的可见按钮
- 点击后等待 6 秒

#### [6] register_account() — 4 步注册子流程

##### [6.1] 填写密码 + 同意条款

```
等待: 最多 30 秒等待 #registration_password 字段出现
填写: #registration_password → PASSWORD
填写: #registration_passwordConfirm → PASSWORD
勾选: #terms_and_conditions-input (通过 JavaScript 设置 checked + 触发 change 事件)
```

**条款勾选技巧**: 使用 JavaScript `evaluate()` 直接操作 DOM:
```javascript
cb.checked = true;
cb.dispatchEvent(new Event('change', {bubbles: true}));
```

##### [6.2] hCaptcha — 手动验证

```
等待: 最多 120 秒 (2 分钟)
检测通过条件 (任一满足):
  a. 6 个 input[type="number"] 出现 → 说明已跳转到验证码输入页
  b. 页面文本包含 "验证您的电子邮件" / "Verify your email" / "Enter the 6-digit code"
  c. "Create Account" 按钮变为 enabled 状态
通过后: 若仍在注册页面，点击 "Create Account" 提交
```

##### [6.3] 验证码轮询 + 填入

```
1. _provider.poll_code(mailbox, timeout=180)
   → 每 2 秒调用一次 fetch_latest_message
   → 提取验证码 (如 "123456")

2. 隐藏 hCaptcha widget (设 display:none)

3. 填入 6 位验证码:
   - 定位 input[type="number"] (最多等 30 秒)
   - 使用 React 兼容的值设置方法:
     setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
     setter.call(input, code[i])
     input.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}))

4. 点击提交按钮 (按优先级尝试):
   Verify → Next → Continue → Submit → Confirm
```

**React 兼容输入**: 直接修改 `input.value` 不会触发 React 的合成事件系统，因此必须使用 `HTMLInputElement.prototype.value` 的原生 setter + `InputEvent` 来确保 React 组件正确响应输入。

##### [6.4] 注册后续页面

```
循环: 最多 60 秒
检测与处理:
  a. consent/developer agreement 页面 → 点击 "Accept" / "Agree" / 勾选 checkbox + accept
  b. select-account 页面 (URL 含 "select-account" 或 "cloudaccounts.nvidia.com")
     → 填写组织名为 "dev-org" (使用 React 兼容值设置)
     → 点击 "Create" / "Select" / "Confirm" / "Next"
  c. 到达 build.nvidia.com → 注册成功
  d. 仍在验证码页 → 等待
```

**组织名填写方式**: 与验证码填入类似，使用 `value.set` + `input` 事件 + `change` 事件 + `blur` 事件，确保表单验证通过。

---

## 8. API Key 创建流程

**文件**: `nvidia_register.py:521-665`

### 8.1 前置处理: 清理残留页面

```
循环: 最多 20 秒
  - 若在 select-account 页 → 填写组织名 + 点击确认按钮
  - 若在 consent 页 → 点击 Accept/Agree
  - 若在 build.nvidia.com → 跳出循环
  - 兜底: 直接导航到 https://build.nvidia.com/
```

### 8.2 提取浏览器 Cookie

```python
cookies = await page.context.cookies()
cookie_str = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
```

将所有 Cookie 拼接为 `name1=value1; name2=value2` 格式，用于后续 HTTP 请求的认证。

### 8.3 步骤 1: 获取 orgName

```
GET https://api.ngc.nvidia.com/user-context
Headers: cookie, user-agent, origin, referer

重试: 最多 3 次
  - 网络错误 → 等待 2 秒重试
  - HTTP 非 200 → 等待 2 秒重试
  - 响应无 orgName → 等待 3 秒重试

降级: 在浏览器中访问 /explore/account/manage-org
  → 点击 "Create" / "New" 按钮
  → 再次请求 /user-context
```

### 8.4 步骤 2: 创建 Key

```
POST https://api.ngc.nvidia.com/v3/orgs/{orgName}/keys/type/AI_PLAYGROUNDS_KEY
Body: { expiryDate, name, type, policies }
Headers: 同步骤 1 + Content-Type: application/json

成功: 提取 apiKey.value (或 result.apiKey.value)
失败: HTTP 非 200/201 → 打印错误信息
```

### 8.5 Key 保存

```
文件路径: keys/nvidia_api_key_{N}_{YYYYMMDD_HHMMSS}.txt
  - N: 自动递增序号 (扫描 keys/ 目录已有文件确定)
  - 时间戳: 运行时的本地时间

文件内容: nvapi-xxxxxxxxxxxx (纯文本，仅 Key 值)
自定义路径: 可通过 NV_KEY_FILE 环境变量指定
```

---

## 9. 关键文件说明

| 文件 | 行数 | 说明 |
|------|------|------|
| `nvidia_register.py` | 770 | 主入口 — 注册编排 + API Key 创建 + LegacyApiProvider |
| `mail_providers.py` | 398 | 邮箱提供商模块 — Base / DuckMail / IMAP |
| `run.bat` | ~20 | Windows 一键启动器 — 检查依赖 → 安装 → 运行 |
| `requirements.txt` | 2 | Python 依赖: `playwright>=1.40.0`, `requests>=2.28.0` |
| `.env.example` | 4 | 配置模板 (仅 LegacyApi 模式) |
| `.env` | 变量 | 实际运行配置 (gitignored) |
| `keys/` | — | API Key 输出目录 |

---

## 10. 依赖项

### Python 包

| 包 | 版本要求 | 用途 |
|----|----------|------|
| `playwright` | ≥ 1.40.0 | 浏览器自动化 (Chromium) |
| `requests` | ≥ 2.28.0 | HTTP 请求 (邮箱 API / NGC API) |

### 标准库

| 模块 | 用途 |
|------|------|
| `asyncio` | 异步主循环 |
| `time` | 超时/计时/时间戳 |
| `re` | 正则匹配 (验证码提取) |
| `sys` | 命令行参数 / 退出 |
| `os` | 环境变量 / 路径操作 |
| `imaplib` | IMAP4_SSL 协议客户端 |
| `email` | MIME 邮件解析 |
| `random` + `string` | 生成随机用户名/密码 |

### 浏览器

| 组件 | 说明 |
|------|------|
| Chromium | 需要 `playwright install chromium` 预安装 |

---

## 11. 错误处理与容错机制

### 11.1 邮箱相关

| 场景 | 处理方式 |
|------|----------|
| 邮箱创建失败 | 打印错误，关闭浏览器，退出 |
| 邮箱地址为空 | 打印错误，关闭浏览器，退出 |
| API 请求非 200/201 | 抛出 `RuntimeError` (含状态码和响应体前300字符) |
| 验证码轮询超时 (180s) | 返回 `None`，注册标记为失败 |
| 轮询中单次异常 | 打印 `poll error` 日志，不中断轮询 |
| IMAP 连接失败 | `finally` 块保证 `logout()` |
| DDG API 无 address 字段 | 抛出 `RuntimeError` |

### 11.2 注册相关

| 场景 | 处理方式 |
|------|----------|
| hCaptcha 超时 (120s) | 打印超时警告，注册失败 |
| 验证码输入框未出现 (30s) | 打印警告，不中断流程 |
| 提交按钮未找到 | 打印警告 "maybe auto-submitted" |
| 注册后续页面超时 (60s) | 打印当前 URL，不崩溃 |

### 11.3 API Key 相关

| 场景 | 处理方式 |
|------|----------|
| user-context 重试 3 次失败 | 尝试浏览器内创建组织 |
| 组织创建后仍无 orgName | 打印错误，返回 None |
| Key 创建网络错误 | 打印错误，返回 None |
| Key 创建 HTTP 非 200/201 | 打印状态码和响应体前300字符，返回 None |
| 响应中无 apiKey.value | 打印警告 |

---

## 12. 安全性注意事项

### 12.1 敏感信息处理

| 项目 | 处理方式 |
|------|----------|
| `.env` 文件 | 已加入 `.gitignore`，不会被提交 |
| API Key 文件 | 保存在 `keys/` 目录，已被 `.gitignore` 忽略 |
| Cookie | 仅在内存中使用，不持久化 |
| 密码打印 | 配置打印时用 `******` 遮蔽 |

### 12.2 浏览器反检测

```
--disable-blink-features=AutomationControlled
```

此参数移除 Chromium 的 `navigator.webdriver` 标志，防止网站检测到自动化浏览器。

### 12.3 IMAP 安全

- **强制 SSL**: 仅使用 `IMAP4_SSL`，不支持明文连接
- **授权码**: IMAP 登录使用授权码 (Authorization Code) 而非邮箱密码
- **每次断开**: 每次轮询重新建立连接，避免长时间保持认证状态

### 12.4 潜在风险

| 风险 | 说明 |
|------|------|
| API Key 有效期 | 过期时间设为 100 年 (`2126`)，泄露后影响巨大 |
| Cookie 泄露 | Cookie 拼接后通过 HTTP 明文传输 (HTTPS 传输层加密) |
| 组织名固定 | `dev-org` 为硬编码默认值 |
| hCaptcha 人工依赖 | 需要用户在场手动解决验证码 |

---

## 附录 A: 三种邮箱提供商对比

| 特性 | LegacyApi | DuckMail | IMAP |
|------|-----------|----------|------|
| **MAIL_TYPE** | `api` | `duckmail` | `imap` |
| **方式** | 自建 REST API | 托管 REST API | DDG 别名 + IMAP 读取 |
| **邮箱类型** | 临时 | 临时 | 转发别名 |
| **需要真实邮箱** | 否 | 否 | 是 |
| **需要自行部署** | 是 | 否 | 否 |
| **创建邮箱** | 1 次 POST | 2 次 POST | 1 次 POST |
| **读取邮件** | 2 次 GET | 2 次 GET | IMAP 连接 |
| **认证** | 管理员密钥 + JWT | API Key + Token | DDG Token + IMAP 授权码 |
| **代码位置** | nvidia_register.py | mail_providers.py | mail_providers.py |
| **HTML 解析** | 无 (用 raw) | 有 | 有 |
| **推荐场景** | 已有自建服务 | 开箱即用 | 中国大陆用户 (配合 QQ 邮箱) |

## 附录 B: 完整调用栈

```
main()
├── load_env()
├── validate_config()
├── create_provider()
│   ├── LegacyApiProvider(api, auth, domain)
│   ├── DuckMailProvider(api_key, domain)
│   └── ImapMailProvider(ddg_token, imap_email, ...)
│
├── [1] _provider.create_mailbox()
│   ├── LegacyApi: POST /admin/new_address
│   ├── DuckMail: POST /accounts + POST /token
│   └── IMAP: POST /api/email/addresses
│
├── [2-5] Playwright 浏览器操作
│
├── [6] register_account(page, email, mailbox)
│   ├── [1/4] DOM: fill password, check terms
│   ├── [2/4] 等待 hCaptcha (用户手动)
│   ├── [3/4] _provider.poll_code(mailbox)
│   │   └── 循环调用 fetch_latest_message
│   │       └── _extract_code(message)
│   │           └── 4 级正则策略
│   └── [4/4] 处理 consent / org / build 页面
│
├── [7] create_api_key(page)
│   ├── 处理残留页面
│   ├── GET /user-context → orgName
│   ├── (降级) 浏览器创建 org
│   └── POST /keys/type/AI_PLAYGROUNDS_KEY → apiKey
│
└── [8] 保存 Key + 关闭浏览器
```

---

*文档生成于 2026-06-30，基于项目 commit `3e2cd62` 代码分析。*
