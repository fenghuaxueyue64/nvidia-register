# nvidia-register

半自动注册 NVIDIA BUILD 账号并自动创建 `AI_PLAYGROUNDS_KEY`。

## 原理

使用 Playwright 自动化浏览器完成注册全流程：

1. 通过临时邮箱服务创建邮箱
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
- **自建临时邮箱服务**（见下文说明）

## 邮箱服务

该脚本依赖一个临时邮箱 API 服务，须自行部署。

部署方式：实现 `POST /admin/new_address` + `GET /api/mails` + `GET /api/mail/{id}` 接口的临时邮箱服务。

部署完成后你会获得三样东西：
- `EMAIL_API`: 服务地址，如 `https://mail.your-server.com`
- `EMAIL_AUTH`: 管理员密钥（调用邮箱创建 API 用）
- `EMAIL_DOMAIN`: 邮箱域名，如 `your-domain.com`

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 配置

```bash
# 生成配置文件模板
python3 nvidia_register.py --init
```

编辑生成的 `.env` 文件：

```ini
EMAIL_API=https://mail.your-server.com
EMAIL_AUTH=your_admin_key
EMAIL_DOMAIN=your-domain.com
NV_PASSWORD=YourSecurePassword123
```

| 变量 | 说明 |
|------|------|
| `EMAIL_API` | 临时邮箱服务 API 地址 |
| `EMAIL_AUTH` | 临时邮箱管理员密钥 |
| `EMAIL_DOMAIN` | 邮箱域名 |
| `NV_PASSWORD` | NVIDIA 账号密码（注册用） |
| `NV_KEY_FILE` | [可选] API Key 保存路径，默认脚本同目录 |

## 使用

```bash
python3 nvidia_register.py
```

浏览器弹出后，**手动通过 hCaptcha 验证**，其余步骤全自动。

跑完后 Key 保存在脚本同目录的 `nvidia_api_key.txt`。

## 环境变量

优先级高于 `.env` 文件：

```bash
EMAIL_API=... EMAIL_AUTH=... EMAIL_DOMAIN=... NV_PASSWORD=... python3 nvidia_register.py
```

## 注意事项

- hCaptcha **必须手动完成**，脚本仅做等待检测
- 注册包含验证码轮询（最长 3 分钟），无需手动检查邮件
- 浏览器窗口会在完成后 10 秒自动关闭

## 免责声明

- 本项目仅用于**学习交流**，旨在研究 NVIDIA BUILD 平台注册流程的技术实现
- 请勿将本项目用于任何商业用途或批量注册等违反 NVIDIA 服务条款的行为
- 用户使用本项目产生的任何后果与责任，均与本仓库及维护者无关
- 使用者应自行承担使用风险，并遵守相关平台的使用协议
