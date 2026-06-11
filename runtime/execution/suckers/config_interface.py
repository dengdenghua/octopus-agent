
from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConfigKeyType = Literal["env", "setting", "path"]


class ConfigRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(..., min_length=1)
    type: ConfigKeyType = "env"
    required: bool = True
    default: Any = None
    description: str = ""
    pattern: str | None = None


class ConfigMissingItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    type: ConfigKeyType
    description: str
    has_default: bool


class ConfigCheckReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_name: str
    satisfied: list[str] = Field(default_factory=list)
    missing: list[ConfigMissingItem] = Field(default_factory=list)
    all_required_satisfied: bool = True


class SkillConfigChecker:

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
    ) -> None:
        self._settings = settings or {}

    def check(
        self,
        skill_name: str,
        requirements: list[ConfigRequirement],
    ) -> ConfigCheckReport:
        satisfied: list[str] = []
        missing: list[ConfigMissingItem] = []

        for req in requirements:
            if self._is_satisfied(req):
                satisfied.append(req.key)
            elif req.required and req.default is None:
                missing.append(ConfigMissingItem(
                    key=req.key,
                    type=req.type,
                    description=req.description,
                    has_default=False,
                ))
            else:
                satisfied.append(req.key)

        return ConfigCheckReport(
            skill_name=skill_name,
            satisfied=satisfied,
            missing=missing,
            all_required_satisfied=len(missing) == 0,
        )

    def check_from_meta(
        self,
        skill_name: str,
        meta: dict[str, Any],
    ) -> ConfigCheckReport:
        raw = meta.get("config_requirements") or []
        requirements = [
            ConfigRequirement(**r) if isinstance(r, dict) else r
            for r in raw
        ]
        return self.check(skill_name, requirements)

    def provide_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    def _is_satisfied(self, req: ConfigRequirement) -> bool:
        if req.type == "env":
            return req.key in os.environ
        if req.type == "setting":
            return req.key in self._settings
        if req.type == "path":
            return os.path.exists(os.path.expanduser(req.key))
        return False


def parse_config_requirements(
    raw: list[dict[str, Any]] | None,
) -> list[ConfigRequirement]:
    if not raw:
        return []
    return [ConfigRequirement(**r) for r in raw]
