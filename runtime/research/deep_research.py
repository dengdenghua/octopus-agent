"""Deep research planning primitives.

This module builds the job plan for a GPT-style deep research workflow:
user-provided files/sites/text are treated as first-class materials. The
planner may split larger work across role-specific subagents, but small runs
stay narrow instead of forcing a fixed swarm template.

The planner is deterministic on purpose. It gives the UI and API a stable
contract before any LLM-driven splitter or search backend is plugged in.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

ResearchDepth = Literal["quick", "standard", "deep"]
ResearchSourceProvider = Literal[
    "web_search",
    "fetch_url",
    "uploaded_file",
    "local_file",
    "manual_material",
]
ResearchSourceKind = Literal[
    "web",
    "news",
    "academic",
    "company_site",
    "ecommerce",
    "social",
    "forum",
    "uploaded_file",
    "provided_url",
    "local_file",
]
ResearchStepStatus = Literal["pending", "running", "completed", "failed"]
ResearchPrefetchStatus = Literal["completed", "failed", "skipped"]
ResearchPrefetchAction = Literal["search", "fetch", "material", "skip"]
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


class ResearchMaterial(BaseModel):
    """User-supplied research material."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"mat_{uuid4().hex[:10]}")
    kind: Literal["file", "url", "text", "site"] = "text"
    title: str = ""
    path: str | None = None
    url: str | None = None
    text: str | None = None
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        return value.strip()


class ResearchSource(BaseModel):
    """A source lane the research run should consult."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"src_{uuid4().hex[:10]}")
    kind: ResearchSourceKind
    label: str
    query_hint: str = ""
    provider: ResearchSourceProvider = "web_search"
    query_templates: list[str] = Field(default_factory=list)
    site_filters: list[str] = Field(default_factory=list)
    freshness_days: int | None = None
    url: str | None = None
    enabled: bool = True


class ResearchEvidence(BaseModel):
    """A traceable source supporting, contradicting, or contextualizing a claim."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"ev_{uuid4().hex[:10]}")
    job_id: str | None = None
    step_id: str | None = None
    role_id: str | None = None
    title: str = ""
    url: str | None = None
    source_kind: ResearchSourceKind | None = None
    published_at: str | None = None
    quote_or_summary: str = ""
    claim: str = ""
    stance: Literal["support", "contradict", "context"] = "context"
    confidence: float = Field(default=0.5, ge=0, le=1)


class ResearchRole(BaseModel):
    """One subagent role / angle in the research run."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    subagent_name: str = "virtual-researcher"
    focus: str
    deliverable: str
    search_angles: list[str] = Field(default_factory=list)


class ResearchRouteDecision(BaseModel):
    """Persisted subagent routing decision for a research lane."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    schema_: str = Field(
        default="octopus.subagent_route_decision.v1",
        alias="schema",
    )
    step_id: str | None = None
    task_id: str | None = None
    role: str = ""
    action: str = "allow"
    reason: str = ""
    risk_level: str = "low"
    verdict: str = "unknown"
    score: float | None = None
    confidence: float = 0.0
    evidence_item_ids: list[str] = Field(default_factory=list)
    phase: str | None = None
    created_at: str | None = None


class ResearchStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    role_id: str
    status: ResearchStepStatus = "pending"
    source_ids: list[str] = Field(default_factory=list)
    expected_searches: int = 0
    prompt: str = ""
    route_decision: ResearchRouteDecision | None = None


class ResearchPrefetchLog(BaseModel):
    """A visible trace item from the pre-dispatch source prefetch pass."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"pf_{uuid4().hex[:10]}")
    source_id: str | None = None
    source_kind: ResearchSourceKind | None = None
    source_label: str = ""
    provider: ResearchSourceProvider = "web_search"
    action: ResearchPrefetchAction = "search"
    query: str | None = None
    url: str | None = None
    status: ResearchPrefetchStatus = "completed"
    result_count: int = 0
    evidence_count: int = 0
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class DeepResearchRequest(BaseModel):
    """POST body for deep research planning / start."""

    model_config = ConfigDict(extra="ignore")

    topic: str
    thread_id: str | None = None
    lead_agent_name: str | None = None
    depth: ResearchDepth = "standard"
    locale: str = "zh-CN"
    materials: list[ResearchMaterial] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    source_kinds: list[ResearchSourceKind] = Field(
        default_factory=lambda: [
            "web",
            "news",
            "academic",
            "company_site",
            "ecommerce",
            "social",
            "forum",
            "uploaded_file",
            "provided_url",
        ],
    )
    roles: list[ResearchRole] = Field(default_factory=list)
    max_subagents: int | None = Field(default=None, ge=1, le=12)
    max_searches: int = Field(default=120, ge=1, le=1000)
    include_thread_uploads: bool = True
    prefetch_sources: bool = False
    task_risk_level: Literal["low", "medium", "high", "critical"] | None = None
    final_report_format: Literal["markdown", "brief", "slides_outline"] = "markdown"

    @field_validator("topic")
    @classmethod
    def _topic_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic is required")
        return value


class ResearchJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    thread_id: str | None = None
    lead_agent_name: str | None = None
    topic: str
    status: Literal["planned", "running", "completed", "failed", "cancelled"] = "planned"
    depth: ResearchDepth
    locale: str
    created_at: str
    materials: list[ResearchMaterial]
    sources: list[ResearchSource]
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    prefetch_logs: list[ResearchPrefetchLog] = Field(default_factory=list)
    route_decisions: list[ResearchRouteDecision] = Field(default_factory=list)
    roles: list[ResearchRole]
    steps: list[ResearchStep]
    max_searches: int
    dispatch_batch_id: str | None = None
    final_report_format: str = "markdown"
    final_report: str | None = None
    completed_at: str | None = None
    memory_entry: str | None = None
    memory_written_at: str | None = None
    memory_path: str | None = None


class DeepResearchPlanner:
    """Deterministic planner for GPT-style deep research jobs.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ deep_research.py · navigation map (1101 lines).                    ║
    ║                                                                    ║
    ║   §1 Pydantic models (Material/Source/Evidence/Role) ~L51-148      ║
    ║   §2 DeepResearchRequest + ResearchJob               ~L151-218     ║
    ║   §3 DeepResearchPlanner (the bulk, ~270 lines)      ~L219         ║
    ║       build_plan + _build_search_steps + ...                       ║
    ║   §4 material/evidence helpers                       ~L487-595     ║
    ║   §5 source routing (URL → kind)                     ~L597         ║
    ║   §6 query coercion + role normalization             ~L748         ║
    ║   §7 subagent budget + virtual naming                ~L807         ║
    ║   §8 default roles + search apportionment            ~L867         ║
    ║   §9 prompt rendering (sources + evidence pool)      ~L944         ║
    ╚════════════════════════════════════════════════════════════════════╝
    """

    def build_plan(
        self,
        request: DeepResearchRequest,
        *,
        thread_materials: list[ResearchMaterial] | None = None,
    ) -> ResearchJob:
        materials = list(request.materials)
        if request.include_thread_uploads and thread_materials:
            materials.extend(thread_materials)
        materials.extend(_url_materials(request.urls))
        materials = _dedupe_materials(materials)

        sources = _default_sources(request.topic, request.source_kinds, materials)
        subagent_budget = _resolve_subagent_budget(
            request,
            materials=materials,
            sources=sources,
        )
        roles = _normalize_roles(request.roles or _default_roles(request.topic, subagent_budget))[
            :subagent_budget
        ]
        steps = [
            _step_for_role(
                role,
                topic=request.topic,
                sources=sources,
                materials=materials,
                searches=_searches_for_role(
                    total=request.max_searches,
                    role_index=index,
                    role_count=len(roles),
                ),
            )
            for index, role in enumerate(roles)
        ]
        steps.append(_synthesis_step(request.topic, roles, sources, materials))

        return ResearchJob(
            job_id=f"research_{uuid4().hex[:12]}",
            thread_id=request.thread_id,
            lead_agent_name=request.lead_agent_name,
            topic=request.topic,
            depth=request.depth,
            locale=request.locale,
            created_at=datetime.now(UTC).isoformat(),
            materials=materials,
            sources=sources,
            evidence=_seed_evidence(request.topic, sources, materials),
            roles=roles,
            steps=steps,
            max_searches=request.max_searches,
            final_report_format=request.final_report_format,
        )

    def dispatch_tasks(self, job: ResearchJob) -> list[dict[str, Any]]:
        """Convert research steps into parallel-agent dispatch tasks."""
        tasks: list[dict[str, Any]] = []
        for step in job.steps:
            if step.role_id == "synthesis":
                continue
            role = next((r for r in job.roles if r.id == step.role_id), None)
            tasks.append(
                {
                    "task_id": step.id,
                    "description": step.prompt,
                    "subagent_name": role.subagent_name if role else "virtual-researcher",
                    "priority": 0,
                    "depends_on": [],
                }
            )
        return tasks

    def attach_evidence_pool(
        self,
        job: ResearchJob,
        evidence: list[ResearchEvidence],
        prefetch_logs: list[ResearchPrefetchLog] | None = None,
    ) -> ResearchJob:
        """Attach prefetch evidence and refresh worker prompts with an evidence pool."""
        if evidence:
            job.evidence = _dedupe_evidence([*job.evidence, *evidence])
        if prefetch_logs:
            job.prefetch_logs.extend(prefetch_logs)
        evidence_lines = _evidence_pool_lines(job.evidence)
        for step in job.steps:
            if step.role_id == "synthesis":
                continue
            step.prompt = _with_evidence_pool(step.prompt, evidence_lines)
        return job

    def synthesize_report(
        self,
        job: ResearchJob,
        *,
        aggregated_content: str,
    ) -> str:
        """Build a deterministic final report from completed role outputs.

        This is intentionally a stable baseline. A later LLM synthesis pass can
        replace this while keeping the same persisted `final_report` contract.
        """
        source_lines = _source_instruction_lines(job.sources)
        material_lines = _material_lines(job.materials)
        evidence_lines = _evidence_table(job.evidence)
        route_lines = _route_decision_audit_lines(job.route_decisions)
        lead = job.lead_agent_name or "current lead agent"
        return f"""# {job.topic} 深度研究报告

负责人: {lead}
研究任务: {job.job_id}
研究深度: {job.depth}

## 执行摘要
- 本报告汇总 {len(job.roles)} 个临时虚拟研究角色的并行结果，并由负责人统一收束。
- 临时虚拟角色只服务本次任务，不携带独立长期记忆；稳定结论只回写负责人记忆。
- 报告优先保留可追踪来源、冲突点和证据强弱，避免把未经验证的信息写成确定事实。

## 调研范围与方法
1. 围绕「{job.topic}」拆分市场、用户、产品价格、渠道销售、反方验证等角度。
2. 按来源类型分流搜索和材料读取，优先使用用户材料、官方资料、第三方报告、社区/评论等可复核来源。
3. 将各角色输出统一合并为结论、证据、缺口和建议，供后续二次验证或正式发布。

## 治理与路由审计
{route_lines}

## 研究来源
{source_lines}

## 用户材料
{material_lines}

## 关键发现与分角色结果
{aggregated_content.strip() or "- 暂无角色输出。"}

## 证据与来源 / Evidence Table
{evidence_lines}

## 不确定性与缺口
- 若证据表缺少发布日期、样本量或原始出处，对应结论应标记为初步判断。
- 市场规模、份额、销量、价格区间等量化信息需要至少两类来源交叉验证。
- 对社区评价、论坛讨论和电商评论要注意样本偏差，不能直接等同于总体用户需求。

## 结论与建议
1. 将高置信结论沉淀为负责人记忆，保留 job_id 方便追溯。
2. 对低置信或冲突结论追加二次搜索任务，优先补官方/行业/渠道三类来源。
3. 若要输出对外版报告，建议补充表格化竞品对比、价格区间、渠道证据和引用日期。
"""

    def extract_evidence_from_outputs(
        self,
        job: ResearchJob,
        *,
        aggregated_content: str,
    ) -> list[ResearchEvidence]:
        """Parse structured evidence hints from subagent output.

        Supported line format:
        EVIDENCE {"title":"...","url":"https://...","claim":"..."}
        """
        evidence = list(job.evidence)
        seen = {(ev.url or "", ev.claim or "", ev.title or "") for ev in evidence}
        for raw_line in aggregated_content.splitlines():
            line = raw_line.strip()
            if not line.upper().startswith("EVIDENCE"):
                continue
            payload = line[len("EVIDENCE") :].strip(" :-")
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            ev = ResearchEvidence(
                job_id=job.job_id,
                step_id=_coerce_str(data.get("step_id")),
                role_id=_coerce_str(data.get("role_id")),
                title=_coerce_str(data.get("title")) or "Evidence",
                url=_coerce_str(data.get("url")),
                source_kind=_coerce_source_kind(data.get("source_kind")),
                published_at=_coerce_str(data.get("published_at")),
                quote_or_summary=_coerce_str(data.get("quote_or_summary") or data.get("summary")),
                claim=_coerce_str(data.get("claim")),
                stance=_coerce_stance(data.get("stance")),
                confidence=_coerce_confidence(data.get("confidence")),
            )
            key = (ev.url or "", ev.claim or "", ev.title or "")
            if key in seen:
                continue
            seen.add(key)
            evidence.append(ev)
        for url in _URL_RE.findall(aggregated_content):
            key = (url, "", url)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                ResearchEvidence(
                    job_id=job.job_id,
                    title=url,
                    url=url,
                    source_kind="web",
                    quote_or_summary="URL mentioned by a virtual research worker.",
                    claim=job.topic,
                    stance="context",
                    confidence=0.4,
                )
            )
        return evidence

    def build_lead_memory_entry(self, job: ResearchJob) -> str:
        """Summarize a completed research job for the lead agent memory."""
        source_kinds = ", ".join(s.kind for s in job.sources if s.enabled) or "none"
        report_excerpt = (job.final_report or "").strip().replace("\n", " ")
        if len(report_excerpt) > 700:
            report_excerpt = report_excerpt[:700].rstrip() + "..."
        return (
            f"Deep research completed for topic '{job.topic}' "
            f"(job={job.job_id}, sources={source_kinds}, searches={job.max_searches}). "
            f"Final report summary: {report_excerpt}"
        )

    def write_lead_memory(
        self,
        job: ResearchJob,
        *,
        agents_root: Path | None = None,
    ) -> ResearchJob:
        """Persist the research memory to the selected lead agent only."""
        lead = (job.lead_agent_name or "").strip()
        if not lead or lead.startswith("virtual-research-"):
            return job
        if job.memory_written_at:
            return job
        if not job.final_report:
            return job
        if "/" in lead or "\\" in lead or lead in {".", ".."}:
            return job

        if agents_root is None:
            from runtime.platform.process.paths import project_root

            root = project_root() / "agents"
        else:
            root = agents_root
        core = root / lead / "agent-core"
        core.mkdir(parents=True, exist_ok=True)
        path = core / "MEMORY.md"
        entry = self.build_lead_memory_entry(job)
        now = datetime.now(UTC).isoformat()
        line = f"- [{now} · deep-research,{job.job_id}] {entry}\n"

        if path.exists():
            text = path.read_text(encoding="utf-8")
            if job.job_id in text:
                job.memory_entry = entry
                job.memory_written_at = now
                job.memory_path = str(path)
                return job
            if "_No memories yet._" in text:
                cleaned = (
                    "\n".join(
                        ln for ln in text.splitlines() if ln.strip() != "_No memories yet._"
                    ).rstrip()
                    + "\n"
                )
                path.write_text(cleaned, encoding="utf-8")

        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        job.memory_entry = entry
        job.memory_written_at = now
        job.memory_path = str(path)
        return job


def _url_materials(urls: list[str]) -> list[ResearchMaterial]:
    out: list[ResearchMaterial] = []
    for url in urls:
        clean = url.strip()
        if not clean:
            continue
        out.append(ResearchMaterial(kind="url", title=clean, url=clean))
    return out


def _dedupe_materials(materials: list[ResearchMaterial]) -> list[ResearchMaterial]:
    seen: set[tuple[str, str]] = set()
    out: list[ResearchMaterial] = []
    for material in materials:
        key_value = material.url or material.path or material.text or material.title or material.id
        key = (material.kind, key_value.strip() if isinstance(key_value, str) else str(key_value))
        if key in seen:
            continue
        seen.add(key)
        out.append(material)
    return out


def _seed_evidence(
    topic: str,
    sources: list[ResearchSource],
    materials: list[ResearchMaterial],
) -> list[ResearchEvidence]:
    evidence: list[ResearchEvidence] = []
    provided = next((s for s in sources if s.kind == "provided_url"), None)
    for mat in materials:
        if mat.kind not in ("url", "site") or not mat.url:
            continue
        evidence.append(
            ResearchEvidence(
                title=mat.title or mat.url,
                url=mat.url,
                source_kind="provided_url",
                quote_or_summary=mat.notes or "User-provided source for this research run.",
                claim=topic,
                stance="context",
                confidence=0.6,
                step_id=None,
                role_id=None,
            )
        )
    if not evidence and provided is not None:
        evidence.append(
            ResearchEvidence(
                title=provided.label,
                source_kind=provided.kind,
                quote_or_summary=provided.query_hint,
                claim=topic,
                stance="context",
                confidence=0.3,
            )
        )
    return evidence


def _dedupe_evidence(evidence: list[ResearchEvidence]) -> list[ResearchEvidence]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ResearchEvidence] = []
    for item in evidence:
        key = (item.url or "", item.claim or "", item.title or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _default_sources(
    topic: str,
    kinds: list[ResearchSourceKind],
    materials: list[ResearchMaterial],
) -> list[ResearchSource]:
    labels: dict[ResearchSourceKind, str] = {
        "web": "Web search",
        "news": "News and recent market signals",
        "academic": "Academic and standards literature",
        "company_site": "Official company/product sites",
        "ecommerce": "Retail/ecommerce listings",
        "social": "Social media and creator content",
        "forum": "Forums, communities, reviews",
        "uploaded_file": "Uploaded files",
        "provided_url": "User-provided sites",
        "local_file": "Local files",
    }
    sources: list[ResearchSource] = []
    for kind in dict.fromkeys(kinds):
        if kind == "uploaded_file" and not any(m.kind == "file" for m in materials):
            continue
        if kind == "provided_url" and not any(m.kind in ("url", "site") for m in materials):
            continue
        route = _source_route(topic, kind, materials)
        sources.append(
            ResearchSource(
                kind=kind,
                label=labels[kind],
                query_hint=_query_hint(topic, kind),
                provider=route["provider"],
                query_templates=route["query_templates"],
                site_filters=route["site_filters"],
                freshness_days=route["freshness_days"],
            )
        )
    return sources


def _source_route(
    topic: str,
    kind: ResearchSourceKind,
    materials: list[ResearchMaterial],
) -> dict[str, Any]:
    provided_hosts = _material_hosts(materials)
    routes: dict[ResearchSourceKind, dict[str, Any]] = {
        "web": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} market overview competitors trends",
                f"{topic} report analysis forecast",
            ],
            "site_filters": [],
            "freshness_days": None,
        },
        "news": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} latest news market report 2026",
                f"{topic} shipment revenue funding acquisition latest",
            ],
            "site_filters": [
                "Reuters",
                "Bloomberg",
                "PR Newswire",
                "company newsroom",
            ],
            "freshness_days": 365,
        },
        "academic": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} research paper benchmark methodology",
                f"{topic} standard whitepaper pdf",
            ],
            "site_filters": [
                "site:scholar.google.com",
                "site:arxiv.org",
                "site:ieee.org",
                "filetype:pdf",
            ],
            "freshness_days": None,
        },
        "company_site": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} official product specification pricing",
                f"{topic} datasheet release notes support lifecycle",
            ],
            "site_filters": ["official domains", *provided_hosts],
            "freshness_days": None,
        },
        "ecommerce": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} price best seller reviews",
                f"{topic} Amazon JD Tmall price ranking",
            ],
            "site_filters": [
                "site:amazon.com",
                "site:jd.com",
                "site:tmall.com",
                "site:newegg.com",
            ],
            "freshness_days": 180,
        },
        "social": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} YouTube review Reddit discussion",
                f"{topic} creator review sentiment complaints",
            ],
            "site_filters": [
                "site:youtube.com",
                "site:x.com",
                "site:bilibili.com",
                "site:zhihu.com",
            ],
            "freshness_days": 365,
        },
        "forum": {
            "provider": "web_search",
            "query_templates": [
                f"{topic} forum review complaint problem",
                f"{topic} reddit community user experience",
            ],
            "site_filters": [
                "site:reddit.com",
                "site:forums.servethehome.com",
                "site:community.synology.com",
                "site:forums.unraid.net",
            ],
            "freshness_days": 730,
        },
        "uploaded_file": {
            "provider": "uploaded_file",
            "query_templates": [
                "extract claims, tables, assumptions, and citations from uploaded files",
            ],
            "site_filters": [],
            "freshness_days": None,
        },
        "provided_url": {
            "provider": "fetch_url",
            "query_templates": [
                "open user-provided URLs directly, extract claims, dates, and source authority",
            ],
            "site_filters": provided_hosts,
            "freshness_days": None,
        },
        "local_file": {
            "provider": "local_file",
            "query_templates": [
                "read local files and extract facts, tables, assumptions, and citations",
            ],
            "site_filters": [],
            "freshness_days": None,
        },
    }
    return routes[kind]


def _material_hosts(materials: list[ResearchMaterial]) -> list[str]:
    hosts: list[str] = []
    for material in materials:
        if material.kind not in ("url", "site") or not material.url:
            continue
        parsed = urlparse(material.url)
        host = parsed.netloc.lower().removeprefix("www.")
        if host and host not in hosts:
            hosts.append(f"site:{host}")
    return hosts[:8]


def _query_hint(topic: str, kind: ResearchSourceKind) -> str:
    suffix = {
        "web": "market overview competitors trends",
        "news": "latest news funding shipment revenue report",
        "academic": "research paper standard benchmark methodology",
        "company_site": "official product specification pricing datasheet",
        "ecommerce": "price reviews ranking sales channels",
        "social": "user pain points creator reviews sentiment",
        "forum": "reddit forum community review problem complaint",
        "uploaded_file": "extract claims data tables assumptions",
        "provided_url": "extract facts claims pricing products",
        "local_file": "extract facts tables references",
    }[kind]
    return f"{topic} {suffix}"


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_source_kind(value: Any) -> ResearchSourceKind | None:
    value = _coerce_str(value)
    allowed = {
        "web",
        "news",
        "academic",
        "company_site",
        "ecommerce",
        "social",
        "forum",
        "uploaded_file",
        "provided_url",
        "local_file",
    }
    return value if value in allowed else None  # type: ignore[return-value]


def _coerce_stance(value: Any) -> Literal["support", "contradict", "context"]:
    value = _coerce_str(value)
    if value in {"support", "contradict", "context"}:
        return value  # type: ignore[return-value]
    return "context"


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _normalize_roles(roles: list[ResearchRole]) -> list[ResearchRole]:
    normalized: list[ResearchRole] = []
    seen_ids: set[str] = set()
    for index, role in enumerate(roles):
        fallback_id = f"role_{index + 1}"
        role_id = _slug_role_id(role.id or fallback_id) or fallback_id
        if role_id in seen_ids:
            role_id = f"{role_id}_{index + 1}"
        seen_ids.add(role_id)

        subagent_name = _virtual_subagent_name(role.subagent_name, role_id)
        normalized.append(
            role.model_copy(
                update={
                    "id": role_id,
                    "name": role.name.strip() or role_id.replace("_", " ").title(),
                    "subagent_name": subagent_name,
                    "focus": role.focus.strip() or "General research and source verification.",
                    "deliverable": role.deliverable.strip() or "Research findings with evidence.",
                    "search_angles": [
                        angle.strip() for angle in role.search_angles if angle.strip()
                    ],
                }
            )
        )
    return normalized


def _virtual_subagent_name(value: str, role_id: str) -> str:
    raw = (value or "").strip()
    suffix = raw[len("virtual-research-") :] if raw.startswith("virtual-research-") else role_id
    suffix = _slug_role_id(suffix) or role_id
    return f"virtual-research-{suffix}"


def _slug_role_id(value: str) -> str:
    value = _SAFE_ID_RE.sub("-", value.strip().lower()).strip("-_")
    value = re.sub(r"-{2,}", "-", value)
    return value[:64]


def _resolve_subagent_budget(
    request: DeepResearchRequest,
    *,
    materials: list[ResearchMaterial],
    sources: list[ResearchSource],
) -> int:
    if request.max_subagents is not None:
        return request.max_subagents
    if request.roles:
        return max(1, min(12, len(request.roles)))

    topic = request.topic.strip()
    topic_l = topic.lower()
    score = 0
    if request.depth == "deep":
        score += 1
    elif request.depth == "quick":
        score -= 1
    if request.max_searches >= 240:
        score += 1
    if request.max_searches >= 600:
        score += 1
    if len(materials) >= 3:
        score += 1
    if len(materials) >= 8:
        score += 1
    if len([source for source in sources if source.enabled]) >= 6:
        score += 1
    if len(re.findall(r"[\w\u4e00-\u9fff]+", topic)) >= 14:
        score += 1
    if re.search(
        r"market|competitor|research|report|architecture|migration|audit|"
        r"compare|strategy|roadmap|调研|研究|报告|竞品|市场|架构|迁移|审计|"
        r"对比|策略|路线图",
        topic_l,
    ):
        score += 1

    if score <= 0:
        return 1
    if score <= 2:
        return 2
    if score <= 4:
        return 3
    return 5


def _default_roles(topic: str, max_subagents: int) -> list[ResearchRole]:
    roles = [
        ResearchRole(
            id="market_landscape",
            name="市场格局研究员",
            subagent_name="virtual-research-market-landscape",
            focus="行业规模、主要玩家、产品线、区域差异和趋势",
            deliverable="市场格局摘要、主流厂商表、关键趋势和不确定性",
            search_angles=[
                "global and China market overview",
                "major vendors and product families",
                "recent launches and demand shifts",
            ],
        ),
        ResearchRole(
            id="user_needs",
            name="用户与场景分析师",
            subagent_name="virtual-research-user-needs",
            focus="目标用户、使用场景、购买动机、痛点和未满足需求",
            deliverable="用户分层、场景地图、痛点证据和机会假设",
            search_angles=[
                "buyer personas and jobs to be done",
                "reviews complaints forum discussions",
                "home prosumer SMB enterprise use cases",
            ],
        ),
        ResearchRole(
            id="product_pricing",
            name="产品与价格分析师",
            subagent_name="virtual-research-product-pricing",
            focus="价格区间、性能、功能、规格、套件和差异化",
            deliverable="价格/性能/功能对比表和关键选型标准",
            search_angles=[
                "pricing tiers and best sellers",
                "spec comparison performance benchmark",
                "feature gaps and buying criteria",
            ],
        ),
        ResearchRole(
            id="channel_sales",
            name="渠道与销售研究员",
            subagent_name="virtual-research-channel-sales",
            focus="销售渠道、分销模式、内容渠道、区域打法和市场份额线索",
            deliverable="渠道地图、销售模式、份额 proxy 和证据链接",
            search_angles=[
                "retail ecommerce distributors",
                "market share shipment proxy",
                "content channel and affiliate strategy",
            ],
        ),
        ResearchRole(
            id="skeptic",
            name="反方验证员",
            subagent_name="virtual-research-skeptic",
            focus="识别夸大、过时、样本偏差、证据不足和相互矛盾的信息",
            deliverable="风险清单、证据可信度评分、需要二次验证的问题",
            search_angles=[
                "contradictory evidence",
                "source reliability",
                "missing data and caveats",
            ],
        ),
    ]
    # Keep the defaults general but let small runs retain the core angles.
    if max_subagents <= 3:
        return [roles[0], roles[1], roles[2]]
    return roles


def _searches_for_role(*, total: int, role_index: int, role_count: int) -> int:
    if role_count <= 0:
        return total
    base = max(1, total // role_count)
    remainder = total % role_count
    return base + (1 if role_index < remainder else 0)


def _source_instruction_lines(sources: list[ResearchSource]) -> str:
    lines: list[str] = []
    for source in sources:
        if not source.enabled:
            continue
        queries = "; ".join(source.query_templates[:3]) or source.query_hint
        filters = ", ".join(source.site_filters[:6])
        freshness = f"; freshness <= {source.freshness_days} days" if source.freshness_days else ""
        suffix = f"; filters: {filters}" if filters else ""
        lines.append(
            f"- {source.label} [{source.provider}]: {source.query_hint}"
            f"\n  queries: {queries}{suffix}{freshness}"
        )
    return "\n".join(lines) or "- No enabled sources recorded."


def _evidence_pool_lines(evidence: list[ResearchEvidence]) -> str:
    if not evidence:
        return "- No pre-seeded evidence. Build evidence from source routes and materials."
    lines: list[str] = []
    for item in evidence[:20]:
        source = item.title or item.url or item.source_kind or "Evidence"
        url = f" ({item.url})" if item.url else ""
        summary = item.quote_or_summary or item.claim or "Context evidence"
        lines.append(
            f"- {source}{url}: {summary[:500]} "
            f"[{item.source_kind or 'source'}; confidence={item.confidence:.2f}]"
        )
    return "\n".join(lines)


def _with_evidence_pool(prompt: str, evidence_lines: str) -> str:
    marker = "\n\n初始证据池：\n"
    prompt = prompt.split(marker, 1)[0].rstrip()
    return (
        f"{prompt}{marker}{evidence_lines}\n\n"
        "请先核验初始证据池，再补充新的搜索结果；如果证据冲突，请明确标注。"
    )


def _step_for_role(
    role: ResearchRole,
    *,
    topic: str,
    sources: list[ResearchSource],
    materials: list[ResearchMaterial],
    searches: int,
) -> ResearchStep:
    source_ids = [s.id for s in sources if s.enabled]
    material_lines = _material_lines(materials)
    source_lines = _source_instruction_lines(sources)
    angle_lines = "\n".join(f"- {angle}" for angle in role.search_angles)
    prompt = f"""你是{role.name}。围绕主题「{topic}」做深度研究。

你的角度：
{role.focus}

优先搜索/核验这些方向：
{angle_lines}

可用来源：
{source_lines}

工具路由：优先按上面 provider 使用 web_search / fetch_url / uploaded_file 等渠道，并保留 query、url、发布日期和冲突信息。

用户提供材料：
{material_lines}

搜索预算：最多 {searches} 次搜索或页面读取。要求记录关键来源、日期、证据强弱和冲突点。

输出：
{role.deliverable}

证据要求：每个关键结论后至少给出 1 条 EVIDENCE JSON 行，格式如下：
EVIDENCE {{"title":"source title","url":"https://example.com","source_kind":"web","published_at":"YYYY-MM-DD or unknown","claim":"supported claim","stance":"support","confidence":0.7,"quote_or_summary":"short source summary"}}
"""
    return ResearchStep(
        id=f"step_{role.id}",
        title=role.deliverable,
        role_id=role.id,
        source_ids=source_ids,
        expected_searches=searches,
        prompt=prompt.strip(),
    )


def _synthesis_step(
    topic: str,
    roles: list[ResearchRole],
    sources: list[ResearchSource],
    materials: list[ResearchMaterial],
) -> ResearchStep:
    role_lines = "\n".join(f"- {r.name}: {r.deliverable}" for r in roles)
    source_lines = _source_instruction_lines(sources)
    prompt = f"""汇总主题「{topic}」的深度研究结果。

你将收到以下角色的研究结果：
{role_lines}

需要交叉核验的来源类型：
{source_lines}

用户提供材料：
{_material_lines(materials)}

最终报告结构：
1. 执行摘要
2. 关键结论和证据
3. 市场/用户/产品/渠道分章节
4. 对比表
5. 风险、冲突信息和证据等级
6. 机会建议和下一步验证清单
"""
    return ResearchStep(
        id="step_synthesis",
        title="汇总趋势、痛点与机会并形成结论建议",
        role_id="synthesis",
        source_ids=[s.id for s in sources if s.enabled],
        expected_searches=0,
        prompt=prompt.strip(),
    )


def _evidence_table(evidence: list[ResearchEvidence]) -> str:
    if not evidence:
        return "- No structured evidence recorded yet."
    lines = [
        "| Claim | Source | Stance | Confidence |",
        "| --- | --- | --- | --- |",
    ]
    for ev in evidence[:30]:
        claim = _escape_table(ev.claim or ev.quote_or_summary or "Context")
        source = _escape_table(ev.title or ev.url or ev.source_kind or "Source")
        if ev.url:
            source = f"[{source}]({ev.url})"
        lines.append(f"| {claim} | {source} | {ev.stance} | {ev.confidence:.2f} |")
    return "\n".join(lines)


def _route_decision_audit_lines(decisions: list[ResearchRouteDecision]) -> str:
    if not decisions:
        return "- 未记录子代理路由拦截或警告；本次研究未发现需要单独审计的路由风险。"
    lines: list[str] = []
    for decision in decisions:
        step = decision.step_id or decision.task_id or "unknown-step"
        role = decision.role or "unknown-role"
        reason = decision.reason or "no reason recorded"
        lines.append(
            f"- {step} · {role} · {decision.action} "
            f"({decision.verdict}, risk={decision.risk_level}): {reason}"
        )
    return "\n".join(lines)


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _material_lines(materials: list[ResearchMaterial]) -> str:
    if not materials:
        return "- 无用户材料；需要完全依赖外部搜索并标注来源。"
    lines: list[str] = []
    for mat in materials:
        target = mat.url or mat.path or (mat.text[:80] if mat.text else "")
        title = mat.title or target or mat.id
        lines.append(f"- [{mat.kind}] {title}: {target}")
    return "\n".join(lines)
