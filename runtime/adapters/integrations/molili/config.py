
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class MoliliAuthConfig(BaseModel):

    mock_mode: bool = Field(
        default=False,
        description=(
            "开发/演示模式 · 不调真 Molili · 本地生成 6 位码 + 打 log · "
            "登录成功后建一个假 link（molili_user_id='mock-<phone>'）"
        ),
    )
    mock_code: str | None = Field(
        default=None,
        description="mock_mode 下 · 若设则所有手机号都用这个码验证（测试用）",
    )
    sms_send_url: str | None = Field(
        default=None,
        description="POST URL · 要求 JSON body 含 phone 字段 · mock_mode=True 时忽略",
    )
    sms_verify_url: str | None = Field(
        default=None,
        description="POST URL · 验码成功返回 (userId, token) · mock_mode=True 时忽略",
    )
    send_phone_field: str = Field(
        default="mobile",
        description=(
            "sendSms 请求 body 里手机号字段名。Molili Swagger 写 phone · "
            "但线上实际是 mobile · 除非你换租户否则保持 mobile。"
        ),
    )
    verify_phone_field: str = Field(
        default="mobile",
        description="loginByMobile 请求 body 里手机号字段名（MobileLoginCmd 用 mobile）",
    )
    sms_type: str | None = Field(
        default=None,
        description=(
            "SendSmsCmd 的 smsType · Swagger 说必填 · 实际可省 · "
            "确认你租户的枚举值（如 LOGIN）再填"
        ),
    )
    phone_field: str | None = Field(
        default=None,
        description=(
            "已废弃 · 旧 config.yaml 只有一个 phone_field · 设了后兼容映射到 "
            "verify_phone_field · 新配置请用 send_phone_field / verify_phone_field"
        ),
    )
    code_field: str = Field(
        default="verifyCode",
        description="loginByMobile 请求 body 里验证码字段名 · Swagger 写 code 但实际要 verifyCode",
    )
    user_id_path: str = Field(
        default="data.userId",
        description="verify 响应体里 Molili userId 的 dotted path",
    )
    token_path: str = Field(
        default="data.token",
        description="verify 响应体里 session token 的 dotted path",
    )
    mobile_path: str | None = Field(
        default="data.userInfo.mobile",
        description="可选 · 从 userInfo 里抓脱敏手机号供展示",
    )
    credits_path: str | None = Field(
        default="data.userInfo",
        description="可选 · 抓整个 userInfo 当 credits snapshot 缓存",
    )

    @model_validator(mode="after")
    def _apply_legacy_phone_field(self) -> MoliliAuthConfig:
        if self.phone_field and self.verify_phone_field == "mobile":
            object.__setattr__(self, "verify_phone_field", self.phone_field)
        return self


class MoliliConfig(BaseModel):

    enabled: bool = Field(
        default=False,
        description="总开关 · false 时所有 /api/*/molili 返 503",
    )
    base_url: str = Field(
        default="https://molili.8kbl.com/molili-agi/chatApi/v1",
        description="Molili OpenAI 兼容 LLM 端点",
    )
    info_url: str | None = Field(
        default=None,
        description=(
            "可选 · Molili userInfo/credits 探测端点。"
            "未设置时 /refresh 为 no-op · 只返已缓存的 snapshot"
        ),
    )
    default_model: str = Field(
        default="molili",
        description="默认模型 id · Molili 代理会映到用户账号里选中的上游",
    )
    request_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=600.0,
        description="非流式调用超时 · 登录保持短 timeout 快失败",
    )
    auth: MoliliAuthConfig = Field(
        default_factory=MoliliAuthConfig,
        description="SMS 登录配置 · sms_send_url/sms_verify_url 留空即禁用 auth 路由",
    )

    jwt_secret: str | None = Field(
        default=None,
        description=(
            "SMS 登录成功时签发 JWT 用的 HS256 密钥。"
            "不设则 /sms/verify 返 actor_id 但不发 JWT（客户端自己用 X-Actor）"
        ),
    )
    jwt_expire_seconds: int = Field(
        default=30 * 24 * 3600,
        description="JWT exp 距 iat 多少秒 · 默认 30 天",
    )
    jwt_issuer: str | None = Field(
        default="octopus-agent",
        description="JWT iss claim",
    )


def load_molili_config_from_dict(data: dict | None) -> MoliliConfig:
    return MoliliConfig(**(data or {}))
