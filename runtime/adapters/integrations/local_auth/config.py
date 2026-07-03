from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def hash_password(plaintext: str) -> str:
    """Hash a password using bcrypt with a random salt.

    Returns a string in the format ``bcrypt:<hash>`` for forward
    compatibility and to distinguish from legacy sha256 hashes.
    """
    import bcrypt

    pw_bytes = plaintext.encode("utf-8")
    hashed = bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=12))
    return f"bcrypt:{hashed.decode('utf-8')}"


def verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt or legacy sha256 hash."""
    if hashed.startswith("bcrypt:"):
        import bcrypt

        stored = hashed[7:].encode("utf-8")
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored)
    # Legacy sha256 fallback for migration
    import hashlib

    legacy = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return hashed == legacy or hashed == f"sha256:{legacy}"


class LocalAuthConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description="总开关 · 生产环境慎开",
    )
    allow_any_username: bool = Field(
        default=False,
        description=(
            "True · 任何用户名都能登录 · dev 友好。False · 只认 allowed_usernames 或 users 里的键"
        ),
    )
    allowed_usernames: list[str] = Field(
        default_factory=list,
        description="白名单 · 仅 allow_any_username=False 且 users 空时生效",
    )
    users: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "用户名 → SHA-256 密码哈希。非空时 · 强制密码登录 · allow_any_username 被忽略"
        ),
    )
    jwt_secret: str | None = Field(
        default=None,
        description=(
            "登录成功时签发 JWT 用的 HS256 密钥。不设则返 actor_id 但不发 JWT · 客户端走 X-Actor"
        ),
    )

    @staticmethod
    def _validate_jwt_secret(secret: str | None) -> None:
        if secret is None:
            return
        if len(secret) < 32:
            raise ValueError(f"jwt_secret must be at least 32 characters long, got {len(secret)}")
        # Check entropy: reject secrets that are too predictable
        # (e.g. all lowercase, all digits, or common patterns)
        has_lower = any(c.islower() for c in secret)
        has_upper = any(c.isupper() for c in secret)
        has_digit = any(c.isdigit() for c in secret)
        has_special = any(not c.isalnum() for c in secret)
        score = sum([has_lower, has_upper, has_digit, has_special])
        if score < 3:
            raise ValueError(
                "jwt_secret must contain at least 3 of: lowercase, uppercase, digits, special characters"
            )

    jwt_expire_seconds: int = Field(
        default=7 * 24 * 3600,
        description="JWT exp 距 iat 多少秒 · 默认 7 天",
    )
    jwt_issuer: str | None = Field(
        default="octopus-agent",
        description="JWT iss claim",
    )
    jwt_audience: str | None = Field(
        default=None,
        description="JWT aud claim",
    )
    actor_prefix: str = Field(
        default="local:",
        description="actor_id 前缀 · 和 molili: 分命名空间",
    )
    default_roles: list[str] = Field(
        default_factory=lambda: ["user", "local"],
        description="新建 Identity 的默认 roles",
    )

    @property
    def password_required(self) -> bool:
        return bool(self.users)

    def model_post_init(self, __context: Any) -> None:
        self._validate_jwt_secret(self.jwt_secret)
