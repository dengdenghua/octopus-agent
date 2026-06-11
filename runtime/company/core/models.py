from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


ProjectStage = Literal["idea", "validation", "prototype", "pilot", "commercial"]
ProjectStatus = Literal["active", "paused", "completed", "cancelled"]
MilestoneStatus = Literal[
    "not_started",
    "in_progress",
    "blocked",
    "done",
    "cancelled",
]
TaskStatus = Literal["todo", "doing", "blocked", "done", "cancelled"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
TaskSource = Literal["manual", "meeting", "risk", "milestone", "agent", "dingtalk"]
ProjectInsightKind = Literal["risk", "next_action", "decision"]
DependencyType = Literal[
    "finish_to_start",
    "start_to_start",
    "finish_to_finish",
    "start_to_finish",
]
ProjectBudgetTier = Literal["lean", "standard", "premium", "enterprise"]
ActorType = Literal["human", "agent", "digital_twin", "system"]
ProgressEventType = Literal[
    "status_changed",
    "progress_updated",
    "blocked",
    "unblocked",
    "risk_added",
    "artifact_added",
    "comment",
    "agent_run_started",
    "agent_run_completed",
]


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Project(_WireModel):
    id: str = Field(default_factory=lambda: new_id("proj"))
    name: str
    description: str = ""
    industry: str = ""
    stage: ProjectStage = "idea"
    owner_id: str | None = None
    team_room_id: str | None = None
    ding_talk_group_id: str | None = None
    start_date: str | None = None
    target_end_date: str | None = None
    status: ProjectStatus = "active"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("project name is required")
        return value


class ProjectMilestone(_WireModel):
    id: str = Field(default_factory=lambda: new_id("mile"))
    project_id: str
    title: str
    description: str = ""
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    actual_start_at: str | None = None
    actual_end_at: str | None = None
    target_date: str | None = None
    status: MilestoneStatus = "not_started"
    progress: int = 0
    owner_id: str | None = None
    sort_order: int = 0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("milestone title is required")
        return value

    @field_validator("progress")
    @classmethod
    def _progress_bounds(cls, value: int) -> int:
        return max(0, min(100, int(value)))


class TaskAssignee(_WireModel):
    kind: Literal["human", "agent", "digital_twin", "participant"] = "human"
    ref: str
    display_name: str | None = None


class ProjectTask(_WireModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    project_id: str
    milestone_id: str | None = None
    parent_task_id: str | None = None
    title: str
    description: str = ""
    source: TaskSource = "manual"
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    actual_start_at: str | None = None
    actual_end_at: str | None = None
    due_at: str | None = None
    progress: int = 0
    estimate_hours: float | None = None
    actual_hours: float | None = None
    owner_name: str | None = None
    owner_user_id: str | None = None
    assignees: list[TaskAssignee] = Field(default_factory=list)
    ding_todo_id: str | None = None
    team_task_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task title is required")
        return value

    @field_validator("progress")
    @classmethod
    def _task_progress_bounds(cls, value: int) -> int:
        return max(0, min(100, int(value)))


class ProjectTaskDependency(_WireModel):
    id: str = Field(default_factory=lambda: new_id("dep"))
    project_id: str
    from_task_id: str
    to_task_id: str
    type: DependencyType = "finish_to_start"
    lag_days: int = 0
    created_at: str = Field(default_factory=now_iso)


class ProjectProgressEvent(_WireModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    project_id: str
    task_id: str | None = None
    milestone_id: str | None = None
    type: ProgressEventType
    actor_type: ActorType = "system"
    actor_id: str | None = None
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class GanttTaskView(_WireModel):
    id: str
    name: str
    milestone_id: str | None = None
    start: str | None = None
    end: str | None = None
    progress: int = 0
    status: str
    assignee: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    is_milestone: bool = False
    critical: bool = False


class ProjectArtifactView(_WireModel):
    id: str
    project_id: str
    task_id: str
    team_task_id: str | None = None
    source: str = "team_task"
    type: str = "artifact"
    title: str
    content: str = ""
    path: str | None = None
    url: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectInsightView(_WireModel):
    id: str
    project_id: str
    task_id: str | None = None
    team_task_id: str | None = None
    source_artifact_id: str | None = None
    kind: ProjectInsightKind
    title: str
    detail: str = ""
    severity: str | None = None
    owner: str | None = None
    due_at: str | None = None
    status: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Patent / FTO models ─────────────────────────────────────────────────
# Used by the patent-fto-screener agent (registered from
# runtime/sensing/siphon/agent_market_sources/hardware-startup/agent-plugins/
# patent-fto-screener/). The skills in that bundle write/read these via the
# /api/company/projects/{id}/patents/* endpoints.

PatentSourceKind = Literal[
    "cnipa", "wipo", "google_patents", "uspto", "epo",
    "xlsx_import", "csv_import", "web_search", "manual", "other",
]
PatentRelevance = Literal["low", "medium", "high"]
PatentRiskLevel = Literal["low", "medium", "high", "critical"]
PatentLegalStatus = Literal[
    "active", "granted", "pending", "lapsed", "withdrawn", "expired", "unknown",
]
PatentTopicModule = Literal[
    "sensor", "algorithm", "hardware_structure", "app_report",
    "product_intervention", "data_pipeline", "regulated_claim_risk",
]
PatentTopicStatus = Literal["not_started", "searching", "reviewing", "done"]
PatentRiskStatus = Literal["open", "reviewing", "mitigated", "accepted", "closed"]


class PatentSearchTopic(_WireModel):
    id: str = Field(default_factory=lambda: new_id("ptopic"))
    project_id: str
    title: str
    module: PatentTopicModule
    keywords_zh: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    status: PatentTopicStatus = "not_started"
    owner_name: str | None = None
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic title is required")
        return value


class PatentRecord(_WireModel):
    id: str = Field(default_factory=lambda: new_id("pat"))
    project_id: str
    topic_id: str | None = None
    title: str
    applicant: str = ""
    publication_number: str = ""
    application_number: str = ""
    country: str = ""
    publication_date: str | None = None
    legal_status: PatentLegalStatus = "unknown"
    source: PatentSourceKind = "manual"
    url: str | None = None
    abstract: str = ""
    key_claims_summary: str = ""
    independent_claim_count: int = 0
    claim_source: str = ""  # "pdf" | "url" | "abstract_only"
    claims_extracted_at: str | None = None
    inventors: list[str] = Field(default_factory=list)
    ipc_codes: list[str] = Field(default_factory=list)
    related_module: str = ""
    relevance: PatentRelevance = "medium"
    risk_level: PatentRiskLevel = "low"
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("patent title is required")
        return value


class PatentRisk(_WireModel):
    id: str = Field(default_factory=lambda: new_id("prisk"))
    project_id: str
    patent_record_id: str | None = None
    title: str
    related_product_feature: str
    risk_level: PatentRiskLevel
    reason: str
    suggested_design_around: str = ""
    requires_patent_attorney_review: bool = False
    status: PatentRiskStatus = "open"
    owner_name: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("risk title is required")
        return value


class CompanyState(_WireModel):
    projects: list[Project] = Field(default_factory=list)
    milestones: list[ProjectMilestone] = Field(default_factory=list)
    tasks: list[ProjectTask] = Field(default_factory=list)
    dependencies: list[ProjectTaskDependency] = Field(default_factory=list)
    progress_events: list[ProjectProgressEvent] = Field(default_factory=list)
    patent_topics: list[PatentSearchTopic] = Field(default_factory=list)
    patents: list[PatentRecord] = Field(default_factory=list)
    patent_risks: list[PatentRisk] = Field(default_factory=list)
    updated_at: str = Field(default_factory=now_iso)


class CreateProjectRequest(_WireModel):
    name: str
    description: str = ""
    industry: str = ""
    stage: ProjectStage = "idea"
    owner_id: str | None = None
    team_room_id: str | None = None
    ding_talk_group_id: str | None = None
    start_date: str | None = None
    target_end_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateProjectRequest(_WireModel):
    name: str | None = None
    description: str | None = None
    industry: str | None = None
    stage: ProjectStage | None = None
    owner_id: str | None = None
    team_room_id: str | None = None
    ding_talk_group_id: str | None = None
    start_date: str | None = None
    target_end_date: str | None = None
    status: ProjectStatus | None = None
    metadata: dict[str, Any] | None = None


class CreateProjectBlueprintRequest(_WireModel):
    prompt: str
    name: str | None = None
    industry: str = ""
    budget_tier: ProjectBudgetTier = "standard"
    horizon_days: int = 90
    start_date: str | None = None
    owner_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def _prompt_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt is required")
        return value

    @field_validator("horizon_days")
    @classmethod
    def _horizon_bounds(cls, value: int) -> int:
        return max(30, min(365, int(value)))


class CreateProjectMilestoneRequest(_WireModel):
    title: str
    description: str = ""
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    target_date: str | None = None
    owner_id: str | None = None
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateProjectMilestoneRequest(_WireModel):
    title: str | None = None
    description: str | None = None
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    actual_start_at: str | None = None
    actual_end_at: str | None = None
    target_date: str | None = None
    status: MilestoneStatus | None = None
    progress: int | None = None
    owner_id: str | None = None
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class CreateProjectTaskRequest(_WireModel):
    milestone_id: str | None = None
    parent_task_id: str | None = None
    title: str
    description: str = ""
    source: TaskSource = "manual"
    priority: TaskPriority = "medium"
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    due_at: str | None = None
    estimate_hours: float | None = None
    owner_name: str | None = None
    owner_user_id: str | None = None
    assignees: list[TaskAssignee] = Field(default_factory=list)
    ding_todo_id: str | None = None
    team_task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateProjectTaskRequest(_WireModel):
    milestone_id: str | None = None
    parent_task_id: str | None = None
    title: str | None = None
    description: str | None = None
    source: TaskSource | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    actual_start_at: str | None = None
    actual_end_at: str | None = None
    due_at: str | None = None
    progress: int | None = None
    estimate_hours: float | None = None
    actual_hours: float | None = None
    owner_name: str | None = None
    owner_user_id: str | None = None
    assignees: list[TaskAssignee] | None = None
    ding_todo_id: str | None = None
    team_task_id: str | None = None
    metadata: dict[str, Any] | None = None


class DispatchProjectTaskRequest(_WireModel):
    room_id: str | None = None
    sop_template: str = ""
    run: bool = False
    force_new: bool = False


class BindProjectTeamRoomRequest(_WireModel):
    team_room_id: str | None = None
    name: str | None = None
    members: list[dict[str, Any]] = Field(default_factory=list)
    leaderId: str | None = None  # noqa: N815 - mirrors TeamRoom wire
    force_new: bool = False


class CreateProjectTaskDependencyRequest(_WireModel):
    from_task_id: str
    to_task_id: str
    type: DependencyType = "finish_to_start"
    lag_days: int = 0


class ProjectBlueprintResponse(_WireModel):
    project: Project
    milestones: list[ProjectMilestone]
    tasks: list[ProjectTask]
    dependencies: list[ProjectTaskDependency]
    blueprint: dict[str, Any] = Field(default_factory=dict)


class ProjectTeamAssemblyMember(_WireModel):
    id: str = Field(default_factory=lambda: new_id("member"))
    project_id: str
    slot_id: str
    kind: str
    role: str
    display_name: str
    level: str = ""
    status: str = "proposed"
    source_agent_id: str | None = None
    source_agent_name: str | None = None
    source_agent_category: str | None = None
    match_score: int = 0
    capability_score: int = 0
    monthly_cost: str = ""
    responsibility: str = ""
    skills: list[str] = Field(default_factory=list)
    installed_skills: list[str] = Field(default_factory=list)
    arms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectTeamAssemblyResponse(_WireModel):
    project: Project
    members: list[ProjectTeamAssemblyMember]
    budget_profile: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    available_agents_count: int = 0


class MaterializeTeamAssemblyMemberRequest(_WireModel):
    agent_id: str | None = None
    display_name: str | None = None
    model: str | None = None


class MaterializedAgentWire(_WireModel):
    id: str
    name: str
    description: str = ""
    agent_dir: str
    identity_card: dict[str, Any] = Field(default_factory=dict)


class MaterializeTeamAssemblyMemberResponse(_WireModel):
    project: Project
    member: ProjectTeamAssemblyMember
    agent: MaterializedAgentWire
    created: bool
    hot_loaded: bool = False
    requires_reload: bool = False
    team_room_synced: bool = False
    team_room_id: str | None = None


# ── Patent request models ──────────────────────────────────────────────


class CreatePatentSearchTopicRequest(_WireModel):
    title: str
    module: PatentTopicModule
    keywords_zh: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    owner_name: str | None = None
    notes: str = ""


class UpdatePatentSearchTopicRequest(_WireModel):
    title: str | None = None
    module: PatentTopicModule | None = None
    keywords_zh: list[str] | None = None
    keywords_en: list[str] | None = None
    status: PatentTopicStatus | None = None
    owner_name: str | None = None
    notes: str | None = None


class CreatePatentRecordRequest(_WireModel):
    topic_id: str | None = None
    title: str
    applicant: str = ""
    publication_number: str = ""
    application_number: str = ""
    country: str = ""
    publication_date: str | None = None
    legal_status: PatentLegalStatus = "unknown"
    source: PatentSourceKind = "manual"
    url: str | None = None
    abstract: str = ""
    key_claims_summary: str = ""
    inventors: list[str] = Field(default_factory=list)
    ipc_codes: list[str] = Field(default_factory=list)
    related_module: str = ""
    relevance: PatentRelevance = "medium"
    risk_level: PatentRiskLevel = "low"
    notes: str = ""


class UpdatePatentRecordRequest(_WireModel):
    topic_id: str | None = None
    title: str | None = None
    applicant: str | None = None
    publication_number: str | None = None
    application_number: str | None = None
    country: str | None = None
    publication_date: str | None = None
    legal_status: PatentLegalStatus | None = None
    source: PatentSourceKind | None = None
    url: str | None = None
    abstract: str | None = None
    key_claims_summary: str | None = None
    independent_claim_count: int | None = None
    claim_source: str | None = None
    claims_extracted_at: str | None = None
    inventors: list[str] | None = None
    ipc_codes: list[str] | None = None
    related_module: str | None = None
    relevance: PatentRelevance | None = None
    risk_level: PatentRiskLevel | None = None
    notes: str | None = None


class BulkImportPatentRecordsRequest(_WireModel):
    """Bulk import payload used by the patent-import-xlsx skill.

    Server-side dedup runs on (project_id, publication_number) when
    publication_number is non-empty, falling back to (project_id,
    application_number), then (project_id, title, applicant).
    """
    records: list[CreatePatentRecordRequest] = Field(default_factory=list)
    source_label: str = ""  # e.g. "Eight Sleep 智能床垫专利检索 (爱伊特睡眠相关专利列表-127件有效专利.XLSX)"


class CreatePatentRiskRequest(_WireModel):
    patent_record_id: str | None = None
    title: str
    related_product_feature: str
    risk_level: PatentRiskLevel
    reason: str
    suggested_design_around: str = ""
    requires_patent_attorney_review: bool = False
    owner_name: str | None = None


class UpdatePatentRiskRequest(_WireModel):
    title: str | None = None
    related_product_feature: str | None = None
    risk_level: PatentRiskLevel | None = None
    reason: str | None = None
    suggested_design_around: str | None = None
    requires_patent_attorney_review: bool | None = None
    status: PatentRiskStatus | None = None
    owner_name: str | None = None


__all__ = [
    "CompanyState",
    "BindProjectTeamRoomRequest",
    "CreateProjectBlueprintRequest",
    "CreateProjectMilestoneRequest",
    "CreateProjectRequest",
    "CreateProjectTaskDependencyRequest",
    "CreateProjectTaskRequest",
    "DispatchProjectTaskRequest",
    "GanttTaskView",
    "MaterializeTeamAssemblyMemberRequest",
    "MaterializeTeamAssemblyMemberResponse",
    "MaterializedAgentWire",
    "Project",
    "ProjectArtifactView",
    "ProjectBlueprintResponse",
    "ProjectBudgetTier",
    "ProjectInsightKind",
    "ProjectInsightView",
    "ProjectMilestone",
    "ProjectProgressEvent",
    "ProjectTask",
    "ProjectTaskDependency",
    "ProjectTeamAssemblyMember",
    "ProjectTeamAssemblyResponse",
    "TaskAssignee",
    "UpdateProjectMilestoneRequest",
    "UpdateProjectRequest",
    "UpdateProjectTaskRequest",
    # Patent / FTO models (used by hardware-startup/patent-fto-screener agent)
    "PatentSearchTopic",
    "PatentRecord",
    "PatentRisk",
    "PatentSourceKind",
    "PatentRelevance",
    "PatentRiskLevel",
    "PatentLegalStatus",
    "PatentTopicModule",
    "PatentTopicStatus",
    "PatentRiskStatus",
    "CreatePatentSearchTopicRequest",
    "UpdatePatentSearchTopicRequest",
    "CreatePatentRecordRequest",
    "UpdatePatentRecordRequest",
    "BulkImportPatentRecordsRequest",
    "CreatePatentRiskRequest",
    "UpdatePatentRiskRequest",
    "new_id",
    "now_iso",
]
