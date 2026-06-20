from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlannerConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    type: Literal["static", "llm"] = "static"
    model: str = "mock/planner"           # Implementation note.
    mock_response: str | None = None       # Implementation note.
    anthropic_api_key: str | None = None  # Implementation note.
    base_url: str | None = None
    max_nodes: int = Field(default=10, gt=0, le=50)


class BudgetConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    max_tokens: int = Field(default=50_000, gt=0)
    max_usd: float = Field(default=0.50, gt=0.0)
    max_latency_ms: int = Field(default=600_000, gt=0)


class ImmunityConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    # SECURITY: keep this in EXACT sync with the TrustEngine in-process
    # default (runtime/safety/auth/trust_engine.py). ``mcp://*`` is
    # deliberately absent — a malicious MCP server must not be trusted
    # out of the box; operators whitelist specific ``mcp://<server>/*``
    # entries in config (see config.example.yaml). Previously this
    # default DID include ``mcp://*`` while TrustEngine's did not, so
    # the yaml-driven path silently trusted every MCP server — the
    # opposite of the documented posture.
    trusted_sources: list[str] = Field(
        default_factory=lambda: ["skill://public/*"]
    )
    self_whitelist: list[str] = Field(
        default_factory=lambda: [
            "cerebrum", "ganglia", "arms/*",
            "react_loop", "react_arm",
            "intel_collector/*",
        ]
    )
    unknown_policy: Literal["quarantine", "reject", "allow"] = "quarantine"
    # Memory tier (antibody memory). ``attack_memory_path`` enables
    # persistence across restarts; None keeps antibodies in-process.
    attack_memory_path: str | None = None
    attack_threshold: int = 3
    attack_window_seconds: int = 3600
    # Adaptive tier (behavioural anomaly z-score). Off by default —
    # needs a per-sucker cost-baseline history to be meaningful.
    enable_adaptive: bool = False
    adaptive_window_size: int = 200
    adaptive_quarantine_threshold: float = 0.7


class IntelSourceConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    max_results: int = 5
    fetch_top_n: int = 0
    frequency_seconds: int = 3600
    tags: list[str] = Field(default_factory=list)


class MCPServerConfigEntry(BaseModel):

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    # stdio transport (local subprocess server)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # http/sse transport (remote/hosted server)
    transport: Literal["stdio", "http", "sse"] = "stdio"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    name_prefix: str | None = None       # Implementation note.


class SafetyConfig(BaseModel):
    """Typed backing for the ``safety:`` config block.

    Without this, the whole ``safety:`` section was dropped by Pydantic
    (AgentConfig had no field for it), so a typo like ``enabled_llm_judge``
    silently disabled the constitution judge with zero feedback, and a
    judge flag in a ``--config`` file outside cwd was ignored entirely
    (the bootstrap re-read cwd yaml). Reading it off the loaded config
    fixes both.
    """

    model_config = ConfigDict(frozen=True)

    # None = "not set in config" (defer to env var / legacy yaml).
    # True/False = an explicit choice in the loaded --config file.
    enable_llm_judge: bool | None = None
    llm_judge_model: str | None = None
    # Other safety knobs (enable_trust_signal, disabled_guards, …) are
    # still read via their own paths; declared here so a populated
    # ``safety:`` block validates instead of being silently dropped.
    enable_trust_signal: bool | None = None
    # Whether a realtime client may set ``approvalPolicy="never"`` to
    # skip the human approval gate. Default (None / False) is SECURE:
    # the gateway downgrades ``never`` → ``on-request`` so an untrusted
    # client can't silently disable approvals. Operators on a trusted
    # single-user host opt in with ``safety.allow_client_approval_bypass:
    # true``.
    allow_client_approval_bypass: bool | None = None


class LearnConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    learn_from_journal: str | None = None     # Implementation note.
    min_hits: int = 3
    max_rules: int = 30
    learn_memories_from_journal: str | None = None  # Implementation note.
    learn_kg_from_journal: str | None = None         # Implementation note.
    kg_max_triples: int = 15
    rewrite_from_journal: str | None = None          # Implementation note.
    rewrite_min_confidence: float = 0.7
    rewrite_min_severity: Literal["low", "mid", "high"] = "mid"
    assess_recipe_from_journal: str | None = None    # Implementation note.

    rules_persist_path: str | None = None        # Implementation note.
    memories_persist_path: str | None = None     # Implementation note.
    static_rules_persist_path: str | None = None  # Implementation note.

    @field_validator(
        "learn_from_journal",
        "learn_memories_from_journal",
        "learn_kg_from_journal",
        "rewrite_from_journal",
        "assess_recipe_from_journal",
        "rules_persist_path",
        "memories_persist_path",
        "static_rules_persist_path",
    )
    @classmethod
    def _validate_local_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = value.strip()
        if not path:
            raise ValueError("path must not be empty")
        if any(ord(ch) < 32 for ch in path):
            raise ValueError("path must not contain control characters")
        if "://" in path:
            raise ValueError("path must be a local filesystem path, not a URI")
        try:
            Path(path)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid filesystem path") from exc
        return path


class CredentialPoolConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    keys: list[str] = Field(default_factory=list)
    strategy: Literal["round_robin", "least_used", "random"] = "round_robin"
    cooldown_seconds: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=3, gt=0)


class HotCacheConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    path: str = "~/.octopus/hot_cache"
    max_words: int = Field(default=500, gt=0)
    ttl_hours: float = Field(default=24.0, gt=0.0)


_CHEAPER_MAP: dict[str, str] = {
    "mimo-v2.5-pro": "mimo-v2-flash",
    "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
    "claude-opus-4-7": "claude-sonnet-4-6",
    "gpt-4o": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4o-mini",
}


def _pick_cheaper(model: str) -> str:
    return _CHEAPER_MAP.get(model, model)


class EvolveConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    strategy: Literal["inherit", "cheaper_same_provider", "explicit"] = "inherit"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None

    def resolve(self, planner: PlannerConfig) -> tuple[str, str | None]:
        if self.strategy == "inherit":
            return planner.model, planner.base_url
        if self.strategy == "cheaper_same_provider":
            return _pick_cheaper(planner.model), planner.base_url
        return self.model or planner.model, self.base_url or planner.base_url


class MoliliAuthConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    mock_mode: bool = False
    mock_code: str | None = None
    sms_send_url: str | None = None
    sms_verify_url: str | None = None
    send_phone_field: str = "mobile"
    verify_phone_field: str = "mobile"
    code_field: str = "verifyCode"
    sms_type: str | None = None
    user_id_path: str = "data.userId"
    token_path: str = "data.token"
    mobile_path: str = "data.userInfo.mobile"
    credits_path: str = "data.userInfo"


class MoliliConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    base_url: str = "https://molili.8kbl.com/molili-agi/chatApi/v1"
    info_url: str | None = None
    request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=600.0)
    jwt_secret: str | None = Field(default=None, min_length=32)
    jwt_expire_seconds: int = Field(default=2_592_000, gt=0)
    jwt_issuer: str = "octopus-agent"
    auth: MoliliAuthConfig = Field(default_factory=MoliliAuthConfig)


class LocalAuthConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    allow_any_username: bool = False
    allowed_usernames: list[str] = Field(default_factory=list)
    jwt_secret: str | None = Field(default=None, min_length=32)
    jwt_expire_seconds: int = Field(default=604_800, gt=0)
    jwt_issuer: str = "octopus-agent"
    actor_prefix: str = "local:"
    default_roles: list[str] = Field(default_factory=lambda: ["user", "local"])



class CanaryConfig(BaseModel):
    stages: list[str] = Field(default_factory=lambda: ["shadow", "5pct", "25pct", "50pct", "full"])
    sample_sizes: dict[str, int] = Field(default_factory=lambda: {
        "shadow": 0, "5pct": 5, "25pct": 25, "50pct": 50, "full": 100,
    })
    auto_promote: bool = True
    rollback_on_failure: bool = True
    max_duration_hours: float = 72.0


class DriftConfig(BaseModel):
    check_soul: bool = True
    check_genome: bool = True
    check_score: bool = True
    score_window: int = 10
    score_threshold: float = 0.15
    critical_auto_rollback: bool = True


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Background scheduler worker pool. Default 1 matches BackgroundRunner's
    # own default (single-threaded, no pool) — raise to run periodic ticks
    # concurrently.
    max_workers: int = Field(default=1, ge=1, le=128)


class AgentConfig(BaseModel):

    model_config = ConfigDict(frozen=True)

    name: str = "octopus-agent"
    version_compat: str = "0.2"
    preset: str | None = None

    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    immunity: ImmunityConfig = Field(default_factory=ImmunityConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    learn: LearnConfig = Field(default_factory=LearnConfig)
    credential_pool: CredentialPoolConfig = Field(default_factory=CredentialPoolConfig)
    hot_cache: HotCacheConfig = Field(default_factory=HotCacheConfig)
    evolve: EvolveConfig = Field(default_factory=EvolveConfig)
    canary: CanaryConfig = Field(default_factory=CanaryConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    molili: MoliliConfig = Field(default_factory=MoliliConfig)
    local_auth: LocalAuthConfig = Field(default_factory=LocalAuthConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    intel_sources: list[IntelSourceConfig] = Field(default_factory=list)
    mcp_servers: list[MCPServerConfigEntry] = Field(default_factory=list)

    journal_file: str | None = None        # Implementation note.
    enable_web_skills: bool = True         # Implementation note.
    default_arm_id: str = "code_arm"
