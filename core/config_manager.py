"""配置管理器 — .env 文件读写、验证、脱敏。"""

import os
import re
from dataclasses import dataclass, field

from core.ai_config import (
    AI_MODEL_OPTIONS,
    normalize_ai_model,
    normalize_openai_base_url,
)
from mail_providers import normalize_api_base, normalize_mail_domain


# ============================================================================
# 字段定义
# ============================================================================

@dataclass
class FieldDef:
    """单个配置字段的定义。"""
    key: str
    label: str
    type: str = "entry"           # entry | optionmenu
    options: list[str] = field(default_factory=list)
    secret: bool = False
    required: bool = False
    default: str = ""
    description: str = ""


ENV_FIELDS: dict[str, list[FieldDef]] = {
    "common": [
        FieldDef(key="MAIL_TYPE", label="邮箱类型", type="optionmenu",
                 options=["api", "duckmail", "imap"], required=True,
                 description="邮箱服务类型"),
        FieldDef(key="NV_PASSWORD", label="NVIDIA 密码", secret=True,
                 required=True, description="NVIDIA 账号密码"),
    ],
    "api": [
        FieldDef(key="EMAIL_API", label="Email API 地址", required=True),
        FieldDef(key="EMAIL_AUTH", label="Email Auth 密钥", secret=True,
                 required=True),
        FieldDef(key="EMAIL_DOMAIN", label="邮箱域名", required=True),
        FieldDef(key="EMAIL_CREATE_INTERVAL_SECONDS", label="邮箱创建间隔(秒)",
                 default="1", description="并发创建邮箱时的缓冲间隔，0 表示禁用"),
        FieldDef(key="EMAIL_CREATE_RETRIES", label="邮箱创建重试次数",
                 default="4", description="邮箱 API 空响应/非 JSON/网络错误重试次数"),
        FieldDef(key="EMAIL_CREATE_RETRY_DELAY_SECONDS", label="邮箱重试等待(秒)",
                 default="1", description="邮箱 API 重试基础等待时间"),
    ],
    "duckmail": [
        FieldDef(key="DUCKMAIL_API_KEY", label="DuckMail API Key",
                 secret=True, required=True),
        FieldDef(key="DUCKMAIL_DOMAIN", label="DuckMail 域名",
                 default="duckmail.sbs",
                 description="可填 duckmail.sbs 或 @duckmail.sbs"),
        FieldDef(key="DUCKMAIL_API_BASE", label="DuckMail API 地址",
                 default="https://api.duckmail.sbs",
                 description="默认 https://api.duckmail.sbs"),
        FieldDef(key="DUCKMAIL_ACCOUNTS", label="多账户 (key@域名,逗号分隔)",
                 default="",
                 description="可选: dk_xxx@a.com,dk_yyy@b.com"),
    ],
    "imap": [
        FieldDef(key="DDG_TOKEN", label="DDG Token", secret=True,
                 required=True),
        FieldDef(key="IMAP_EMAIL", label="IMAP 邮箱", required=True),
        FieldDef(key="IMAP_KEY", label="IMAP 授权码", secret=True,
                 required=True),
        FieldDef(key="IMAP_HOST", label="IMAP 服务器",
                 default="imap.qq.com", required=True),
        FieldDef(key="IMAP_PORT", label="IMAP 端口", default="993"),
        FieldDef(key="IMAP_INBOX", label="收件箱名称", default="INBOX"),
        FieldDef(key="ALIAS_DOMAIN", label="别名域名",
                 default="duck.com"),
    ],
    "optional": [
        FieldDef(key="NV_KEY_FILE", label="Key 保存目录",
                 description="可选: 目录；高级用法可填 .txt 文件"),
        FieldDef(key="NV_EXPORT_KEY_ONLY", label="导出 Key", type="optionmenu",
                 options=["true", "false"], default="true",
                 description="注册成功后自动保存纯 Key 文件"),
        FieldDef(key="NV_EXPORT_ACCOUNT_FULL", label="导出账号+密码+Key", type="optionmenu",
                 options=["true", "false"], default="false",
                 description="注册成功后自动保存邮箱+密码+Key 完整信息"),
        FieldDef(key="CHROMIUM_EXECUTABLE_PATH", label="Chrome/Edge 路径",
                 description="可选: chrome.exe/msedge.exe"),
        FieldDef(key="PLAYWRIGHT_BROWSERS_PATH", label="Playwright 浏览器目录",
                 description="可选: ms-playwright 目录"),
    ],
    "network": [
        FieldDef(key="HTTP_PROXY", label="HTTP 代理",
                 description="可选: http://127.0.0.1:7897"),
        FieldDef(key="HTTPS_PROXY", label="HTTPS 代理",
                 description="可选: http://127.0.0.1:7897"),
        FieldDef(key="NO_PROXY", label="不走代理",
                 description="可选: localhost,127.0.0.1"),
    ],
    "ai_captcha": [
        FieldDef(key="CAPTCHA_AI_ENABLED", label="AI自动验证码", type="optionmenu",
                 options=["true", "false"], default="false",
                 description="启用 AI 自动解决 hCaptcha 图片验证"),
        FieldDef(key="AI_VISION_API_KEY", label="Vision API Key", secret=True,
                 description="视觉模型 API 密钥 (Qwen/通义千问等)"),
        FieldDef(key="AI_VISION_API_BASE", label="Vision API 地址",
                 description="OpenAI 兼容的视觉 API 基础 URL"),
        FieldDef(key="AI_VISION_MODEL", label="Vision 模型", type="optionmenu",
                 options=AI_MODEL_OPTIONS,
                 default="qwen3.6-flash",
                 description="多模态视觉模型名称"),
    ],
}

# 所有字段平铺查找表
_ALL_FIELDS: dict[str, FieldDef] = {}
for _section_fields in ENV_FIELDS.values():
    for _f in _section_fields:
        _ALL_FIELDS[_f.key] = _f

# 密钥字段集合
SECRET_KEYS = frozenset(k for k, f in _ALL_FIELDS.items() if f.secret)

# 各 MAIL_TYPE 必填字段（排除有默认值的字段）
REQUIRED_BY_MODE = {
    "common": ["MAIL_TYPE", "NV_PASSWORD"],
    "api": ["EMAIL_API", "EMAIL_AUTH", "EMAIL_DOMAIN"],
    "duckmail": ["DUCKMAIL_API_KEY"],
    "imap": ["DDG_TOKEN", "IMAP_EMAIL", "IMAP_KEY", "IMAP_HOST"],
}


class ConfigManager:
    """管理 .env 配置文件的读取、写入、验证和脱敏。"""

    def __init__(self, env_path: str):
        self.env_path = env_path

    # ------ 读取 ------

    def read(self) -> dict[str, str]:
        """读取 .env 文件，返回 key→value 字典。"""
        values: dict[str, str] = {}
        if not os.path.exists(self.env_path):
            return values

        encodings = ["utf-8", "utf-8-sig", "gbk", "latin-1"]
        for encoding in encodings:
            try:
                with open(self.env_path, "r", encoding=encoding) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip("\"'")
                        if key:
                            values[key] = val
                return values
            except (UnicodeDecodeError, UnicodeError):
                continue
        return values

    # ------ 写入 ------

    def write(self, values: dict[str, str]):
        """将 values 写入 .env，保留注释和分隔符行。

        逻辑:
        - 已有的 KEY=VAL 行 → 替换值
        - 注释掉的 KEY=VAL 行 (# KEY=VAL) → 若 values 中有对应值则取消注释并设值
        - 纯注释/分隔符/空行 → 保留不变
        - values 中新增的 key → 追加到文件末尾
        """
        values = self.normalize_values(values)

        # 读取时尝试多种编码
        lines: list[str] = []
        if os.path.exists(self.env_path):
            for encoding in ["utf-8", "utf-8-sig", "gbk", "latin-1"]:
                try:
                    with open(self.env_path, "r", encoding=encoding) as f:
                        lines = f.readlines()
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

        written_keys: set[str] = set()
        new_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # 空行或纯分隔符 → 保留
            if not stripped or (stripped.startswith("#") and "=" not in stripped):
                new_lines.append(line)
                continue

            # 注释掉的 key=value
            if stripped.startswith("#") and "=" in stripped:
                bare = stripped[1:].strip()
                key, _, _ = bare.partition("=")
                key = key.strip()
                if key in values and values[key]:
                    new_lines.append(f"{key}={values[key]}\n")
                    written_keys.add(key)
                else:
                    new_lines.append(line)
                continue

            # 活跃的 key=value
            if "=" in stripped:
                key, _, _ = stripped.partition("=")
                key = key.strip()
                if key in values:
                    new_lines.append(f"{key}={values[key]}\n")
                    written_keys.add(key)
                else:
                    new_lines.append(line)
                continue

            # 其他行
            new_lines.append(line)

        # 追加 values 中新增的 key
        for key, value in values.items():
            if key not in written_keys and value:
                new_lines.append(f"{key}={value}\n")

        with open(self.env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    @staticmethod
    def normalize_values(values: dict[str, str]) -> dict[str, str]:
        normalized = dict(values)
        if "DUCKMAIL_DOMAIN" in normalized:
            normalized["DUCKMAIL_DOMAIN"] = normalize_mail_domain(
                normalized.get("DUCKMAIL_DOMAIN")
            )
        if "DUCKMAIL_API_BASE" in normalized and normalized.get("DUCKMAIL_API_BASE"):
            normalized["DUCKMAIL_API_BASE"] = normalize_api_base(
                normalized.get("DUCKMAIL_API_BASE")
            )
        if "AI_VISION_API_BASE" in normalized and normalized.get("AI_VISION_API_BASE"):
            normalized["AI_VISION_API_BASE"] = normalize_openai_base_url(
                normalized.get("AI_VISION_API_BASE")
            )
        if "AI_VISION_MODEL" in normalized:
            normalized["AI_VISION_MODEL"] = normalize_ai_model(
                normalized.get("AI_VISION_MODEL")
            )
        return normalized

    # ------ 验证 ------

    def validate(self, values: dict[str, str] | None = None) -> list[str]:
        """验证配置完整性，返回缺失字段列表。"""
        if values is None:
            values = self.read()

        missing: list[str] = []

        # 通用必填
        for key in REQUIRED_BY_MODE.get("common", []):
            if not values.get(key, "").strip():
                missing.append(key)

        # 按 MAIL_TYPE 检查
        mail_type = values.get("MAIL_TYPE", "").strip().lower()
        for key in REQUIRED_BY_MODE.get(mail_type, []):
            if not values.get(key, "").strip():
                missing.append(key)

        return missing

    # ------ 脱敏 ------

    @staticmethod
    def desensitize(values: dict[str, str]) -> dict[str, str]:
        """返回脱敏后的配置副本（密钥字段隐藏中间部分）。"""
        result = {}
        for key, value in values.items():
            if key in SECRET_KEYS and value:
                if len(value) <= 8:
                    result[key] = "****"
                else:
                    result[key] = value[:4] + "****" + value[-4:]
            else:
                result[key] = value
        return result

    # ------ 字段信息 ------

    @staticmethod
    def get_all_fields() -> dict[str, FieldDef]:
        """返回所有字段的定义。"""
        return dict(_ALL_FIELDS)

    @staticmethod
    def get_field(key: str) -> FieldDef | None:
        """获取单个字段定义。"""
        return _ALL_FIELDS.get(key)

    @staticmethod
    def default_value(key: str) -> str:
        """返回字段默认值；选项控件使用自己的第一个选项作为兜底。"""
        field_def = _ALL_FIELDS.get(key)
        if not field_def:
            return ""
        if field_def.default:
            return field_def.default
        if field_def.type == "optionmenu" and field_def.options:
            return field_def.options[0]
        return ""

    @staticmethod
    def parse_duckmail_accounts(accounts_str: str) -> list[dict[str, str]]:
        """解析 DuckMail 多账户配置字符串。

        格式: "key1@domain1,key2@domain2" → [{"key": "key1", "domain": "domain1"}, ...]
        """
        if not accounts_str or not accounts_str.strip():
            return []
        result = []
        for item in accounts_str.split(","):
            item = item.strip()
            if not item:
                continue
            if "@" in item:
                key, _, domain = item.partition("@")
                result.append({"key": key.strip(), "domain": domain.strip()})
        return result
