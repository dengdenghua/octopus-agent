"""Typed provider HTTP failures with bounded, secret-free public messages."""

from __future__ import annotations

from .llm import LLMResponseFormatError

MODEL_UNAVAILABLE_MESSAGE = "当前模型服务已将所选模型标记为不可用，请切换模型后重试。"
PROVIDER_HTTP_MESSAGES = {
    400: "模型服务拒绝了请求，请检查模型配置或切换模型后重试（HTTP 400）。",
    401: "模型服务凭据无效，请在插件设置中重新连接（HTTP 401）。",
    402: "模型服务账户余额不足，请充值或切换模型（HTTP 402）。",
    403: "当前账号无权使用此模型，请检查模型权限或切换模型（HTTP 403）。",
    404: "模型服务地址或模型不存在，请检查模型配置（HTTP 404）。",
    422: "模型服务无法处理请求参数，请检查模型配置（HTTP 422）。",
    429: "模型服务请求受限，请稍后重试（HTTP 429）。",
}


class ModelProviderHTTPError(LLMResponseFormatError):
    """Keep the HTTP outcome separate from private diagnostic exception text."""

    def __init__(
        self, message: str, *, status_code: int | None = None, response_body: str = ""
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        # Inspect a bounded body only to classify known model-availability
        # errors. Never store or forward arbitrary provider response text.
        lowered = response_body[:16_384].casefold()
        self.model_unavailable = status_code in {400, 404} and any(
            marker in lowered
            for marker in ("model is unavailable", "model_unavailable", "model_not_found")
        )

    def public_failure(self) -> tuple[int, str]:
        if self.model_unavailable:
            return 400, MODEL_UNAVAILABLE_MESSAGE
        if self.status_code in PROVIDER_HTTP_MESSAGES:
            return self.status_code, PROVIDER_HTTP_MESSAGES[self.status_code]
        return 502, "Echo model request failed"
