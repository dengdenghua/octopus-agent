"""Connection coordinates shared with engines without loading an MCP server."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HostMCPConnection:
    url: str
    token: str = field(repr=False)
