"""统一能力包(Capability)体系:连接器 + Codex 插件归一。"""

from runtime.platform.capabilities.capability_registry import (
    CapabilityRegistry,
    default_capability_registry,
)

__all__ = ["CapabilityRegistry", "default_capability_registry"]
