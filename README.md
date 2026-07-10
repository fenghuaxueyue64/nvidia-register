# nvidia-register

半自动注册 NVIDIA BUILD 账号并自动创建 `AI_PLAYGROUNDS_KEY`。

## 原理

使用 Playwright 自动化浏览器完成注册全流程：

1. 通过邮箱服务创建邮箱（支持三种方式）
2. 打开 build.nvidia.com → Login → 填写邮箱
3. 填写密码 + 勾选协议 → **手动过 hCaptcha**
4. 自动接收验证码邮件 → 填入验证码
5. 自动点 Continue → Submit → 在 Select Account 页面填组织名 → 点创建
6. 回到 build.nvidia.com → 自动调 NGC API 创建 API Key
7. Key 保存到本地文件

## 前置条件

- Python 3.8+
- Chromium 浏览器（Playwright 会自动下载）
- **GUI 环境**（脚本会弹出浏览器窗口，不支持纯命令行服务器）

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 邮箱服务

支持三种邮箱服务类型，通过 `.env` 中的 `MAIL_TYPE` 切换：

| MAIL_TYPE | 说明 | 是否需要自建服务 |
|-----------|------|:---:|
| `api` | 原有自建临时邮箱 API | 是 |
| `duckmail` | DuckMail API (`api.duckmail.sbs`) | 否 |
| `imap` | DDG Email Protection 别名 + IMAP 读取 | 否 |

### 方式 1: `MAIL_TYPE=api` — 自建临时邮箱 API (默认)

兼容原有逻辑，需自行部署临时邮箱服务。

部署方式：实现 `POST /admin/new_address` + `GET /api/mails` + `GET /api/mail/{id}` 接口的临时邮箱服务。

```ini
MAIL_TYPE=api
EMAIL_API=https://mail.your-server.com
EMAIL_AUTH=your_admin_key
EMAIL_DOMAIN=your-domain.com
EMAIL_CREATE_INTERVAL_SECONDS=1
EMAIL_CREATE_RETRIES=4
EMAIL_CREATE_RETRY_DELAY_SECONDS=1
NV_PASSWORD=YourSecurePassword123
```

并发运行时，旧 `api` 模式会用 `EMAIL_CREATE_INTERVAL_SECONDS` 在多个进程之间错开创建邮箱请求，并对空响应、非 JSON 响应和网络抖动按 `EMAIL_CREATE_RETRIES` 重试。

### 方式 2: `MAIL_TYPE=duckmail` — DuckMail API

使用 `api.duckmail.sbs` 提供的 REST API，无需自建服务。

**配置：**

```ini
MAIL_TYPE=duckmail
DUCKMAIL_API_KEY=dk_xxxxxxxxxxxx
DUCKMAIL_DOMAIN=duckmail.sbs
DUCKMAIL_API_BASE=https://api.duckmail.sbs
NV_PASSWORD=YourSecurePassword123
```

| 变量 | 说明 |
|------|------|
| `DUCKMAIL_API_KEY` | DuckMail API 密钥 |
| `DUCKMAIL_DOMAIN` | 邮箱域名（默认 `duckmail.sbs`，也可填 `@duckmail.sbs`，程序会自动规范化） |
| `DUCKMAIL_API_BASE` | DuckMail API 地址（可选；本机代理/DNS 无法访问默认地址时可指定可达地址） |

如果 DuckMail 报 `UNEXPECTED_EOF_WHILE_READING`，先检查本机代理、VPN/TUN、DNS 或防火墙。若 DNS 解析到 `198.18.x.x`，通常说明请求被本地代理规则接管但没有成功转发。

**API 流程：**

1. `POST /accounts` — 创建临时邮箱账户
2. `POST /token` — 获取访问令牌
3. `GET /messages` — 轮询邮件列表
4. `GET /messages/{id}` — 获取邮件详情并提取验证码

### 方式 3: `MAIL_TYPE=imap` — DDG 别名 + IMAP

通过 DuckDuckGo Email Protection 创建 `@duck.com` 别名，邮件转发到真实邮箱后通过 IMAP 协议读取验证码。

**前置要求：**

1. 在 [DuckDuckGo Email Protection](https://duckduckgo.com/email/) 注册并获取 DDG Token
2. 在 DDG 设置中将转发目标设为你的真实邮箱
3. 开启真实邮箱的 IMAP 服务并获取授权码
   - QQ 邮箱：设置 → 账户 → IMAP/SMTP 服务 → 开启并生成授权码

**配置：**

```ini
MAIL_TYPE=imap
DDG_TOKEN=your_ddg_token
IMAP_EMAIL=your_email@example.com
IMAP_KEY=your_imap_auth_code
IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_INBOX=INBOX
ALIAS_DOMAIN=duck.com
NV_PASSWORD=YourSecurePassword123
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DDG_TOKEN` | DuckDuckGo Email Protection Bearer Token | 必填 |
| `IMAP_EMAIL` | IMAP 登录邮箱地址 | 必填 |
| `IMAP_KEY` | IMAP 授权码（非密码） | 必填 |
| `IMAP_HOST` | IMAP 服务器地址 | `imap.qq.com` |
| `IMAP_PORT` | IMAP SSL 端口 | `993` |
| `IMAP_INBOX` | 收件箱名称 | `INBOX` |
| `ALIAS_DOMAIN` | DDG 别名域名 | `duck.com` |

**数据流：**

```
NVIDIA 发送验证码到 DDG 别名
    ↓
DDG 转发到真实邮箱 (QQ/Gmail/Outlook)
    ↓
IMAP 连接读取收件箱
    ↓
搜索 TO/CC 包含别名的邮件
    ↓
提取 6 位验证码
```

## 配置

```bash
# 生成配置文件模板
python3 nvidia_register.py --init
```

编辑生成的 `.env` 文件，选择一种邮箱服务类型填入对应参数。

## 使用

```bash
python3 nvidia_register.py
```

浏览器弹出后，**手动通过 hCaptcha 验证**，其余步骤全自动。

跑完后 Key 默认保存在软件目录下的 `keys/` 文件夹，文件名类似 `nvidia_api_key_1_20260707_000001.txt`。也可以在 UI 的“Key 保存目录”里选择目录，或在 `.env` 中设置 `NV_KEY_FILE`；填目录会自动生成带时间戳的文件，填 `.txt` 文件则写入固定文件。

## Windows exe

可用 `build_exe.bat` 生成单文件版 `dist\NVIDIARegister.exe`。exe 会内置 Python 运行依赖，但不内置 Chromium 浏览器；运行时会自动查找本机 Playwright 浏览器、Chrome、Edge 或 Brave。

如果更在意启动速度，可用 `build_fast.bat` 生成快速版目录 `dist\NVIDIARegister-Fast\`，双击其中的 `NVIDIARegister.exe`。快速版 EXE 本体更小，启动时不需要先解压单文件包，但需要保留同目录下的 `_internal` 依赖目录。

如果自动检测不到浏览器，可在 UI 中点击“选择浏览器”，或在 `.env` 中填写：

```ini
CHROMIUM_EXECUTABLE_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
# 或:
PLAYWRIGHT_BROWSERS_PATH=C:\Users\YourName\AppData\Local\ms-playwright
```

### 用户代理设置

exe 的“配置”页包含“网络代理 (可选)”分区。需要代理时填写：

```ini
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
NO_PROXY=localhost,127.0.0.1
```

保存后，后端 HTTP 请求和注册浏览器都会使用该代理。清空代理字段并保存即可关闭代理。

## 环境变量

优先级高于 `.env` 文件：

```bash
# api 模式
MAIL_TYPE=api EMAIL_API=... EMAIL_AUTH=... EMAIL_DOMAIN=... NV_PASSWORD=... python3 nvidia_register.py

# duckmail 模式
MAIL_TYPE=duckmail DUCKMAIL_API_KEY=... DUCKMAIL_DOMAIN=duckmail.sbs NV_PASSWORD=... python3 nvidia_register.py

# imap 模式
MAIL_TYPE=imap DDG_TOKEN=... IMAP_EMAIL=... IMAP_KEY=... IMAP_HOST=... NV_PASSWORD=... python3 nvidia_register.py
```

## 项目结构

```
nvidia-register/
├── nvidia_register.py      # 主入口：注册 + API Key 创建
├── mail_providers.py       # 邮箱提供商模块
│   ├── BaseMailProvider    # 抽象基类
│   ├── LegacyApiProvider   # 原有 API 适配器
│   ├── DuckMailProvider    # DuckMail API
│   └── ImapMailProvider    # DDG 别名 + IMAP
├── requirements.txt        # Python 依赖
└── README.md
```

## 注意事项

- hCaptcha **必须手动完成**，脚本仅做等待检测
- 注册包含验证码轮询（最长 3 分钟），无需手动检查邮件
- 浏览器窗口会在完成后 10 秒自动关闭
- **IMAP 模式**需要 DDG 转发目标正确配置，邮件转发可能有轻微延迟（通常 < 1 分钟）

## 免责声明

- 本项目仅用于**学习交流**，旨在研究 NVIDIA BUILD 平台注册流程的技术实现
- 请勿将本项目用于任何商业用途或批量注册等违反 NVIDIA 服务条款的行为
- 用户使用本项目产生的任何后果与责任，均与本仓库及维护者无关
- 使用者应自行承担使用风险，并遵守相关平台的使用协议

## 致谢

感谢 [Linux Do](https://linux.do) 社区
