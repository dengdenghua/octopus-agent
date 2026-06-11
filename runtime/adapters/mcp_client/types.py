
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MCPServerConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)        # e.g. "npx" / "python"
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    trust_level: str = "public"                     # "public" | "custom" | "external"
    timeout_ms: int = Field(default=30_000, gt=0)

    @property
    def trusted_source_uri(self) -> str:
        return f"mcp://{self.name}/*"
