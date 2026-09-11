"""Budget host tools separately from the complete Codex Responses catalog."""

MAX_RESPONSES_TOOLS = 256
# Codex adds built-in tools after receiving the host's dynamic catalog. Keep
# half the total budget available for those tools instead of filling it here.
MAX_DYNAMIC_TOOLS = 128
TOOL_CATALOG_ERROR = "Responses tool catalog is too large"
TOOL_CATALOG_MESSAGE = "当前任务加载的工具过多，已超过执行接口上限。请减少启用的插件或工具后重试。"
