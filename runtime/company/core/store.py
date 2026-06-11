from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from runtime.execution.agents.loader import default_agents_root
from runtime.platform.process.paths import app_paths
from runtime.platform.process.utils import parse_jsonc

from .models import (
    BulkImportPatentRecordsRequest,
    CompanyState,
    CreatePatentRecordRequest,
    CreatePatentRiskRequest,
    CreatePatentSearchTopicRequest,
    CreateProjectBlueprintRequest,
    CreateProjectMilestoneRequest,
    CreateProjectRequest,
    CreateProjectTaskDependencyRequest,
    CreateProjectTaskRequest,
    GanttTaskView,
    PatentRecord,
    PatentRisk,
    PatentSearchTopic,
    Project,
    ProjectArtifactView,
    ProjectBlueprintResponse,
    ProjectInsightView,
    ProjectMilestone,
    ProjectProgressEvent,
    ProjectTask,
    ProjectTaskDependency,
    ProjectTeamAssemblyMember,
    ProjectTeamAssemblyResponse,
    TaskAssignee,
    UpdatePatentRecordRequest,
    UpdatePatentRiskRequest,
    UpdatePatentSearchTopicRequest,
    UpdateProjectMilestoneRequest,
    UpdateProjectRequest,
    UpdateProjectTaskRequest,
    now_iso,
)

_LOG = logging.getLogger("octopus.company.store")


class CompanyStore:
    """Small JSON-backed store for Company Workbench planning data."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_paths().data_dir / "company_projects.json")
        self._lock = Lock()
        self._state = self._load()

    def list_projects(self) -> list[Project]:
        with self._lock:
            return sorted(
                self._state.projects,
                key=lambda p: p.updated_at,
                reverse=True,
            )

    def create_project(self, body: CreateProjectRequest) -> Project:
        now = now_iso()
        project = Project(
            **body.model_dump(),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._state.projects.append(project)
            self._save_locked()
        return project

    def create_project_blueprint(
        self,
        body: CreateProjectBlueprintRequest,
    ) -> ProjectBlueprintResponse:
        prompt = body.prompt.strip()
        horizon_days = max(30, min(365, int(body.horizon_days)))
        start = _parse_date(body.start_date) or datetime.now(UTC).date()
        end = start + timedelta(days=horizon_days)
        blueprint = _build_blueprint_payload(body, start=start, end=end)
        now = now_iso()
        project = Project(
            name=_blueprint_project_name(prompt, body.name),
            description=prompt,
            industry=body.industry.strip() or "通用项目",
            stage="idea",
            owner_id=body.owner_id,
            start_date=start.isoformat(),
            target_end_date=end.isoformat(),
            metadata={
                **dict(body.metadata),
                "origin_prompt": prompt,
                "workbench": "company",
                "blueprint": blueprint,
            },
            created_at=now,
            updated_at=now,
        )

        milestones = _build_blueprint_milestones(
            project.id,
            start=start,
            horizon_days=horizon_days,
        )
        tasks = _build_blueprint_tasks(project.id, milestones, start=start)
        dependencies = [
            ProjectTaskDependency(
                project_id=project.id,
                from_task_id=tasks[index].id,
                to_task_id=tasks[index + 1].id,
            )
            for index in range(len(tasks) - 1)
        ]

        with self._lock:
            self._state.projects.append(project)
            self._state.milestones.extend(milestones)
            self._state.tasks.extend(tasks)
            self._state.dependencies.extend(dependencies)
            self._save_locked()

        return ProjectBlueprintResponse(
            project=project,
            milestones=milestones,
            tasks=tasks,
            dependencies=dependencies,
            blueprint=blueprint,
        )

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            return self._project_locked(project_id)

    def update_project(
        self,
        project_id: str,
        body: UpdateProjectRequest,
    ) -> Project | None:
        updates = _drop_none(body.model_dump())
        with self._lock:
            project = self._project_locked(project_id)
            if project is None:
                return None
            updated = Project.model_validate(
                {
                    **project.model_dump(),
                    **updates,
                    "updated_at": now_iso(),
                }
            )
            self._replace_project_locked(updated)
            self._save_locked()
            return updated

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            if self._project_locked(project_id) is None:
                return False
            task_ids = {t.id for t in self._state.tasks if t.project_id == project_id}
            self._state.projects = [
                project for project in self._state.projects if project.id != project_id
            ]
            self._state.milestones = [
                milestone
                for milestone in self._state.milestones
                if milestone.project_id != project_id
            ]
            self._state.tasks = [
                task for task in self._state.tasks if task.project_id != project_id
            ]
            self._state.dependencies = [
                dep
                for dep in self._state.dependencies
                if (
                    dep.project_id != project_id
                    and dep.from_task_id not in task_ids
                    and dep.to_task_id not in task_ids
                )
            ]
            self._state.progress_events = [
                event for event in self._state.progress_events if event.project_id != project_id
            ]
            self._state.patent_topics = [
                topic for topic in self._state.patent_topics if topic.project_id != project_id
            ]
            self._state.patents = [
                patent for patent in self._state.patents if patent.project_id != project_id
            ]
            self._state.patent_risks = [
                risk for risk in self._state.patent_risks if risk.project_id != project_id
            ]
            self._save_locked()
            return True

    def assemble_project_team(self, project_id: str) -> ProjectTeamAssemblyResponse | None:
        candidates = _load_agent_candidates()
        with self._lock:
            project = self._project_locked(project_id)
            if project is None:
                return None
            blueprint = _project_blueprint(project)
            budget_profile = _dict_or_empty(blueprint.get("budget_profile"))
            roles = _blueprint_roles(blueprint)
            members = [
                _assemble_role_member(project.id, role, candidates, index=index)
                for index, role in enumerate(roles)
            ]
            summary = _assembly_summary(members, budget_profile)
            assembled_at = now_iso()
            updated = Project.model_validate(
                {
                    **project.model_dump(),
                    "metadata": {
                        **dict(project.metadata),
                        "team_assembly": {
                            "version": 1,
                            "generated_at": assembled_at,
                            "budget_profile": budget_profile,
                            "summary": summary,
                            "members": [member.model_dump() for member in members],
                        },
                    },
                    "updated_at": assembled_at,
                }
            )
            self._replace_project_locked(updated)
            self._save_locked()
            return ProjectTeamAssemblyResponse(
                project=updated,
                members=members,
                budget_profile=budget_profile,
                summary=summary,
                available_agents_count=len(candidates),
            )

    def list_milestones(self, project_id: str) -> list[ProjectMilestone]:
        with self._lock:
            return sorted(
                [m for m in self._state.milestones if m.project_id == project_id],
                key=lambda m: (m.sort_order, m.planned_end_at or m.target_date or ""),
            )

    def create_milestone(
        self,
        project_id: str,
        body: CreateProjectMilestoneRequest,
    ) -> ProjectMilestone | None:
        now = now_iso()
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            milestone = ProjectMilestone(
                **body.model_dump(),
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            self._state.milestones.append(milestone)
            self._save_locked()
            return milestone

    def update_milestone(
        self,
        milestone_id: str,
        body: UpdateProjectMilestoneRequest,
    ) -> ProjectMilestone | None:
        updates = _drop_none(body.model_dump())
        with self._lock:
            milestone = self._milestone_locked(milestone_id)
            if milestone is None:
                return None
            updated = ProjectMilestone.model_validate(
                {
                    **milestone.model_dump(),
                    **updates,
                    "updated_at": now_iso(),
                }
            )
            self._replace_milestone_locked(updated)
            self._save_locked()
            return updated

    def list_tasks(self, project_id: str) -> list[ProjectTask]:
        with self._lock:
            return sorted(
                [t for t in self._state.tasks if t.project_id == project_id],
                key=lambda t: (t.planned_start_at or t.created_at, t.created_at),
            )

    def get_task(self, task_id: str) -> ProjectTask | None:
        with self._lock:
            return self._task_locked(task_id)

    def create_task(
        self,
        project_id: str,
        body: CreateProjectTaskRequest,
    ) -> ProjectTask | None:
        now = now_iso()
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            if body.milestone_id and self._milestone_locked(body.milestone_id) is None:
                return None
            task = ProjectTask(
                **body.model_dump(),
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            self._state.tasks.append(task)
            self._save_locked()
            return task

    def update_task(
        self,
        task_id: str,
        body: UpdateProjectTaskRequest,
    ) -> ProjectTask | None:
        updates = _drop_none(body.model_dump())
        with self._lock:
            task = self._task_locked(task_id)
            if task is None:
                return None
            milestone_id = updates.get("milestone_id")
            if milestone_id and self._milestone_locked(str(milestone_id)) is None:
                return None
            updated = ProjectTask.model_validate(
                {
                    **task.model_dump(),
                    **updates,
                    "updated_at": now_iso(),
                }
            )
            self._replace_task_locked(updated)
            self._save_locked()
            return updated

    def list_dependencies(self, project_id: str) -> list[ProjectTaskDependency]:
        with self._lock:
            return [d for d in self._state.dependencies if d.project_id == project_id]

    def create_dependency(
        self,
        project_id: str,
        body: CreateProjectTaskDependencyRequest,
    ) -> ProjectTaskDependency | None:
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            from_task = self._task_locked(body.from_task_id)
            to_task = self._task_locked(body.to_task_id)
            if (
                from_task is None
                or to_task is None
                or from_task.project_id != project_id
                or to_task.project_id != project_id
                or from_task.id == to_task.id
            ):
                return None
            dependency = ProjectTaskDependency(
                **body.model_dump(),
                project_id=project_id,
            )
            self._state.dependencies.append(dependency)
            self._save_locked()
            return dependency

    def list_progress_events(self, project_id: str) -> list[ProjectProgressEvent]:
        with self._lock:
            return [e for e in self._state.progress_events if e.project_id == project_id]

    def list_artifacts(self, project_id: str) -> list[ProjectArtifactView] | None:
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            artifacts: list[ProjectArtifactView] = []
            for task in self._state.tasks:
                if task.project_id != project_id:
                    continue
                artifacts.extend(_task_artifact_views(task))
            return sorted(
                artifacts,
                key=lambda artifact: artifact.created_at or "",
                reverse=True,
            )

    def list_insights(self, project_id: str) -> list[ProjectInsightView] | None:
        artifacts = self.list_artifacts(project_id)
        if artifacts is None:
            return None
        insights: list[ProjectInsightView] = []
        for artifact in artifacts:
            insights.extend(_artifact_insight_views(artifact))
        return sorted(
            insights,
            key=lambda insight: insight.created_at or "",
            reverse=True,
        )

    def gantt_view(self, project_id: str) -> list[GanttTaskView] | None:
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            dependencies_by_target: dict[str, list[str]] = {}
            for dep in self._state.dependencies:
                if dep.project_id != project_id:
                    continue
                dependencies_by_target.setdefault(dep.to_task_id, []).append(
                    dep.from_task_id,
                )
            rows: list[GanttTaskView] = []
            for milestone in sorted(
                [m for m in self._state.milestones if m.project_id == project_id],
                key=lambda m: (m.sort_order, m.planned_start_at or ""),
            ):
                rows.append(
                    GanttTaskView(
                        id=milestone.id,
                        name=milestone.title,
                        milestone_id=milestone.id,
                        start=milestone.planned_start_at,
                        end=(
                            milestone.planned_end_at
                            or milestone.target_date
                            or milestone.planned_start_at
                        ),
                        progress=milestone.progress,
                        status=milestone.status,
                        assignee=milestone.owner_id,
                        dependencies=[],
                        is_milestone=True,
                    ),
                )
                for task in sorted(
                    [
                        t
                        for t in self._state.tasks
                        if t.project_id == project_id and t.milestone_id == milestone.id
                    ],
                    key=lambda t: (t.planned_start_at or t.created_at, t.created_at),
                ):
                    rows.append(_task_to_gantt(task, dependencies_by_target))
            milestone_ids = {m.id for m in self._state.milestones}
            for task in sorted(
                [
                    t
                    for t in self._state.tasks
                    if t.project_id == project_id and t.milestone_id not in milestone_ids
                ],
                key=lambda t: (t.planned_start_at or t.created_at, t.created_at),
            ):
                rows.append(_task_to_gantt(task, dependencies_by_target))
            return rows

    def _load(self) -> CompanyState:
        if not self.path.exists():
            return CompanyState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return CompanyState.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _LOG.warning("failed to load company state from %s: %s", self.path, exc)
            return CompanyState()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state.updated_at = now_iso()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                self._state.model_dump(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _project_locked(self, project_id: str) -> Project | None:
        return next((p for p in self._state.projects if p.id == project_id), None)

    def _milestone_locked(self, milestone_id: str) -> ProjectMilestone | None:
        return next((m for m in self._state.milestones if m.id == milestone_id), None)

    def _task_locked(self, task_id: str) -> ProjectTask | None:
        return next((t for t in self._state.tasks if t.id == task_id), None)

    def _replace_project_locked(self, project: Project) -> None:
        self._state.projects = [project if p.id == project.id else p for p in self._state.projects]

    def _replace_milestone_locked(self, milestone: ProjectMilestone) -> None:
        self._state.milestones = [
            milestone if m.id == milestone.id else m for m in self._state.milestones
        ]

    def _replace_task_locked(self, task: ProjectTask) -> None:
        self._state.tasks = [task if t.id == task.id else t for t in self._state.tasks]

    # ── Patent CRUD ────────────────────────────────────────────────────
    # Used by the patent-fto-screener agent (registered from
    # agent_market_sources/hardware-startup/agent-plugins/patent-fto-screener).
    # All methods are project-scoped — no cross-project queries by design.

    # Topics
    def list_patent_topics(self, project_id: str) -> list[PatentSearchTopic]:
        with self._lock:
            return [t for t in self._state.patent_topics if t.project_id == project_id]

    def get_patent_topic(self, topic_id: str) -> PatentSearchTopic | None:
        with self._lock:
            return self._patent_topic_locked(topic_id)

    def create_patent_topic(
        self,
        project_id: str,
        body: CreatePatentSearchTopicRequest,
    ) -> PatentSearchTopic | None:
        now = now_iso()
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            topic = PatentSearchTopic(
                **body.model_dump(),
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            self._state.patent_topics.append(topic)
            self._save_locked()
            return topic

    def update_patent_topic(
        self,
        topic_id: str,
        body: UpdatePatentSearchTopicRequest,
    ) -> PatentSearchTopic | None:
        updates = _drop_none(body.model_dump())
        with self._lock:
            topic = self._patent_topic_locked(topic_id)
            if topic is None:
                return None
            updated = PatentSearchTopic.model_validate(
                {
                    **topic.model_dump(),
                    **updates,
                    "updated_at": now_iso(),
                }
            )
            self._state.patent_topics = [
                updated if t.id == updated.id else t for t in self._state.patent_topics
            ]
            self._save_locked()
            return updated

    # Patent records
    def list_patents(self, project_id: str) -> list[PatentRecord]:
        with self._lock:
            return sorted(
                [p for p in self._state.patents if p.project_id == project_id],
                key=lambda p: (
                    {"high": 0, "medium": 1, "low": 2}.get(p.relevance, 3),
                    p.publication_date or "",
                ),
            )

    def get_patent(self, patent_id: str) -> PatentRecord | None:
        with self._lock:
            return self._patent_locked(patent_id)

    def create_patent(
        self,
        project_id: str,
        body: CreatePatentRecordRequest,
    ) -> PatentRecord | None:
        now = now_iso()
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            if body.topic_id and self._patent_topic_locked(body.topic_id) is None:
                return None
            existing = self._patent_dedup_locked(project_id, body)
            if existing is not None:
                return self._merge_patent_locked(existing, body)
            record = PatentRecord(
                **body.model_dump(),
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            self._state.patents.append(record)
            self._save_locked()
            return record

    def update_patent(
        self,
        patent_id: str,
        body: UpdatePatentRecordRequest,
    ) -> PatentRecord | None:
        updates = _drop_none(body.model_dump())
        with self._lock:
            patent = self._patent_locked(patent_id)
            if patent is None:
                return None
            updated = PatentRecord.model_validate(
                {
                    **patent.model_dump(),
                    **updates,
                    "updated_at": now_iso(),
                }
            )
            self._state.patents = [
                updated if p.id == updated.id else p for p in self._state.patents
            ]
            self._save_locked()
            return updated

    def bulk_import_patents(
        self,
        project_id: str,
        body: BulkImportPatentRecordsRequest,
    ) -> dict[str, int] | None:
        """Bulk import with server-side dedup. Returns counts dict."""
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            created = 0
            updated = 0
            skipped = 0
            for record_req in body.records:
                existing = self._patent_dedup_locked(project_id, record_req)
                if existing is not None:
                    before = existing.model_dump()
                    merged = self._merge_patent_locked(existing, record_req)
                    if merged is not None and merged.model_dump() != before:
                        updated += 1
                    else:
                        skipped += 1
                else:
                    record = PatentRecord(
                        **record_req.model_dump(),
                        project_id=project_id,
                    )
                    self._state.patents.append(record)
                    created += 1
            self._save_locked()
            return {"created": created, "updated": updated, "skipped": skipped}

    # Patent risks
    def list_patent_risks(self, project_id: str) -> list[PatentRisk]:
        with self._lock:
            return sorted(
                [r for r in self._state.patent_risks if r.project_id == project_id],
                key=lambda r: (
                    {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r.risk_level, 4),
                    r.created_at,
                ),
            )

    def get_patent_risk(self, risk_id: str) -> PatentRisk | None:
        with self._lock:
            return self._patent_risk_locked(risk_id)

    def create_patent_risk(
        self,
        project_id: str,
        body: CreatePatentRiskRequest,
    ) -> PatentRisk | None:
        now = now_iso()
        with self._lock:
            if self._project_locked(project_id) is None:
                return None
            if body.patent_record_id and self._patent_locked(body.patent_record_id) is None:
                return None
            requires_review = body.requires_patent_attorney_review
            if body.risk_level in ("high", "critical"):
                requires_review = True
            risk = PatentRisk(
                **{**body.model_dump(), "requires_patent_attorney_review": requires_review},
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            self._state.patent_risks.append(risk)
            self._save_locked()
            return risk

    def update_patent_risk(
        self,
        risk_id: str,
        body: UpdatePatentRiskRequest,
    ) -> PatentRisk | None:
        updates = _drop_none(body.model_dump())
        with self._lock:
            risk = self._patent_risk_locked(risk_id)
            if risk is None:
                return None
            merged = {**risk.model_dump(), **updates}
            if merged.get("risk_level") in ("high", "critical"):
                merged["requires_patent_attorney_review"] = True
            merged["updated_at"] = now_iso()
            updated = PatentRisk.model_validate(merged)
            self._state.patent_risks = [
                updated if r.id == updated.id else r for r in self._state.patent_risks
            ]
            self._save_locked()
            return updated

    # ── Patent helpers (locked) ────────────────────────────────────────

    def _patent_topic_locked(self, topic_id: str) -> PatentSearchTopic | None:
        return next(
            (t for t in self._state.patent_topics if t.id == topic_id),
            None,
        )

    def _patent_locked(self, patent_id: str) -> PatentRecord | None:
        return next(
            (p for p in self._state.patents if p.id == patent_id),
            None,
        )

    def _patent_risk_locked(self, risk_id: str) -> PatentRisk | None:
        return next(
            (r for r in self._state.patent_risks if r.id == risk_id),
            None,
        )

    def _patent_dedup_locked(
        self,
        project_id: str,
        body: CreatePatentRecordRequest,
    ) -> PatentRecord | None:
        """Find an existing PatentRecord that matches the dedup keys.

        Priority:
          1. (project_id, publication_number) when publication_number non-empty
          2. (project_id, application_number) when application_number non-empty

        We INTENTIONALLY do NOT fall back to (project_id, title, applicant)
        as that collapses patent family members (the same invention filed
        in CN, US, EP, etc.) into one record. If neither identifier is
        present, the row gets a fresh record — better to over-create than
        to silently merge unrelated patents.
        """
        candidates = [p for p in self._state.patents if p.project_id == project_id]
        if body.publication_number:
            for p in candidates:
                if p.publication_number == body.publication_number:
                    return p
        if body.application_number:
            for p in candidates:
                if p.application_number == body.application_number:
                    return p
        return None

    def _merge_patent_locked(
        self,
        existing: PatentRecord,
        body: CreatePatentRecordRequest,
    ) -> PatentRecord | None:
        new_fields = body.model_dump()
        merged = existing.model_dump()
        for key, value in new_fields.items():
            if value in (None, "", [], {}):
                continue
            if key == "relevance" and value == "medium" and merged.get(key) in {"high", "low"}:
                continue
            if (
                key == "risk_level"
                and value == "low"
                and merged.get(key) in {"medium", "high", "critical"}
            ):
                continue
            if key == "legal_status" and value == "unknown" and merged.get(key) != "unknown":
                continue
            merged[key] = value
        merged["updated_at"] = now_iso()
        updated = PatentRecord.model_validate(merged)
        self._state.patents = [updated if p.id == updated.id else p for p in self._state.patents]
        self._save_locked()
        return updated


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _project_blueprint(project: Project) -> dict[str, Any]:
    blueprint = project.metadata.get("blueprint")
    return _dict_or_empty(blueprint)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _blueprint_roles(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    roles = blueprint.get("team_roles")
    if isinstance(roles, list):
        normalized = [role for role in roles if isinstance(role, dict)]
        if normalized:
            return normalized
    return [
        {
            "kind": "agent",
            "role": "planner",
            "display_name": "项目规划 Agent",
            "level": "senior",
            "capability_score": 80,
            "monthly_cost": "待估算",
            "skills": ["goal_breakdown", "gantt_planning", "risk_register"],
            "responsibility": "拆解目标、里程碑、依赖和验收标准",
        },
        {
            "kind": "agent",
            "role": "researcher",
            "display_name": "调研 Agent",
            "level": "mid",
            "capability_score": 75,
            "monthly_cost": "待估算",
            "skills": ["market_research", "web_search", "evidence_digest"],
            "responsibility": "收集市场、技术、供应链和竞品证据",
        },
        {
            "kind": "digital_twin",
            "role": "domain_operator",
            "display_name": "领域数字分身",
            "level": "expert",
            "capability_score": 85,
            "monthly_cost": "按专家授权/席位",
            "skills": ["domain_judgement", "review", "business_context"],
            "responsibility": "承载真人经验、偏好和业务判断",
        },
        {
            "kind": "human",
            "role": "decision_owner",
            "display_name": "决策负责人",
            "level": "owner",
            "capability_score": 95,
            "monthly_cost": "真人岗位成本",
            "skills": ["budget", "contract", "offline_resources"],
            "responsibility": "预算、法律、合同、线下资源和最终决策",
        },
    ]


def _load_agent_candidates() -> list[dict[str, Any]]:
    root = default_agents_root()
    if not root.is_dir():
        return []
    candidates: list[dict[str, Any]] = []
    for agent_dir in sorted(root.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith((".", "_")):
            continue
        if agent_dir.name in {"admin", "desktop_operator"}:
            continue
        profile_path = agent_dir / "profile.jsonc"
        if not profile_path.is_file():
            continue
        try:
            profile = parse_jsonc(profile_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("skip agent profile %s: %s", profile_path, exc)
            continue
        registry = _load_agent_tool_registry(agent_dir)
        candidates.append(
            {
                "id": str(profile.get("id") or agent_dir.name),
                "name": str(profile.get("name") or agent_dir.name),
                "description": str(profile.get("description") or ""),
                "category": str(profile.get("category") or ""),
                "tags": _string_list(profile.get("tags")),
                "arms": _string_list(registry.get("arms")),
                "affinity": _string_list(registry.get("extra_affinity")),
                "private_skills": _string_list(registry.get("private_skills")),
            }
        )
    return candidates


def _load_agent_tool_registry(agent_dir: Path) -> dict[str, Any]:
    path = agent_dir / "agent-core" / "tool-registry.jsonc"
    if not path.is_file():
        return {}
    try:
        parsed = parse_jsonc(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("skip agent tool registry %s: %s", path, exc)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _assemble_role_member(
    project_id: str,
    role: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    index: int,
) -> ProjectTeamAssemblyMember:
    kind = str(role.get("kind") or "agent")
    role_id = str(role.get("role") or f"role_{index + 1}")
    display_name = str(role.get("display_name") or role_id)
    role_skills = _string_list(role.get("skills"))
    role_metadata = _dict_or_empty(role.get("metadata"))
    base = {
        "project_id": project_id,
        "slot_id": f"{kind}:{role_id}",
        "kind": kind,
        "role": role_id,
        "display_name": display_name,
        "level": str(role.get("level") or ""),
        "capability_score": int(role.get("capability_score") or 0),
        "monthly_cost": str(role.get("monthly_cost") or ""),
        "responsibility": str(role.get("responsibility") or ""),
        "skills": role_skills,
        "metadata": {
            "blueprint_role": role,
            **role_metadata,
        },
    }
    if kind == "human":
        return ProjectTeamAssemblyMember(
            **base,
            status="requires_human",
            match_score=0,
        )
    if kind == "digital_twin":
        match, score = _best_agent_match(role, candidates)
        if match and score >= 35:
            return ProjectTeamAssemblyMember(
                **base,
                status="matched",
                source_agent_id=str(match["id"]),
                source_agent_name=str(match["name"]),
                source_agent_category=str(match.get("category") or ""),
                match_score=score,
                installed_skills=_string_list(match.get("private_skills")),
                arms=_string_list(match.get("arms")),
            )
        return ProjectTeamAssemblyMember(
            **base,
            status="needs_digital_twin",
            match_score=score,
        )
    match, score = _best_agent_match(role, candidates)
    if match is None:
        return ProjectTeamAssemblyMember(
            **base,
            status="needs_agent",
            match_score=0,
        )
    return ProjectTeamAssemblyMember(
        **base,
        status="matched" if score >= 25 else "weak_match",
        source_agent_id=str(match["id"]),
        source_agent_name=str(match["name"]),
        source_agent_category=str(match.get("category") or ""),
        match_score=score,
        installed_skills=_string_list(match.get("private_skills")),
        arms=_string_list(match.get("arms")),
    )


def _best_agent_match(
    role: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int]:
    if not candidates:
        return None, 0
    scored = [(_score_agent_for_role(role, candidate), candidate) for candidate in candidates]
    scored.sort(key=lambda item: item[0], reverse=True)
    score, candidate = scored[0]
    return candidate, score


def _score_agent_for_role(role: dict[str, Any], candidate: dict[str, Any]) -> int:
    role_terms = _terms(
        [
            role.get("kind"),
            role.get("role"),
            role.get("display_name"),
            role.get("responsibility"),
            *(_string_list(role.get("skills"))),
        ]
    )
    candidate_terms = _terms(
        [
            candidate.get("id"),
            candidate.get("name"),
            candidate.get("description"),
            candidate.get("category"),
            *(_string_list(candidate.get("tags"))),
            *(_string_list(candidate.get("affinity"))),
            *(_string_list(candidate.get("private_skills"))),
            *(_string_list(candidate.get("arms"))),
        ]
    )
    role_id = str(role.get("role") or "").lower()
    candidate_id = str(candidate.get("id") or "").lower()
    score = 0
    overlap = role_terms & candidate_terms
    score += min(45, len(overlap) * 9)
    if role_id and role_id in candidate_id:
        score += 30
    if role_id == "researcher" and ("researcher" in candidate_id or "research" in candidate_terms):
        score += 35
    if role_id in {"planner", "synthesizer"} and candidate_id in {"general", "coder"}:
        score += 24
    if "market_research" in role_terms and "market" in candidate_terms:
        score += 18
    if "web_search" in role_terms and "web_read" in candidate_terms:
        score += 16
    return max(0, min(100, score))


def _terms(values: list[Any]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        raw = str(value or "").lower()
        for part in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", raw):
            if part:
                terms.add(part)
    return terms


def _assembly_summary(
    members: list[ProjectTeamAssemblyMember],
    budget_profile: dict[str, Any],
) -> dict[str, Any]:
    matched = [member for member in members if member.status == "matched"]
    needs_human = [member for member in members if member.status == "requires_human"]
    needs_twin = [member for member in members if member.status == "needs_digital_twin"]
    needs_agent = [member for member in members if member.status in {"needs_agent", "weak_match"}]
    estimated_low, estimated_high, human_cost_excluded, unknown_cost_slots = (
        _estimate_member_cost_range(members)
    )
    budget_min = budget_profile.get("monthly_budget_min")
    budget_max = budget_profile.get("monthly_budget_max")
    over_budget = (
        isinstance(budget_max, int) and estimated_high is not None and estimated_high > budget_max
    )
    return {
        "total_slots": len(members),
        "matched_agents": len(matched),
        "requires_human": len(needs_human),
        "needs_digital_twin": len(needs_twin),
        "needs_agent": len(needs_agent),
        "budget_label": budget_profile.get("label") or "",
        "monthly_budget": budget_profile.get("monthly_budget") or "",
        "team_size": budget_profile.get("team_size") or "",
        "monthly_budget_min": budget_min,
        "monthly_budget_max": budget_max,
        "estimated_monthly_low": estimated_low,
        "estimated_monthly_high": estimated_high,
        "estimated_monthly_label": _format_monthly_range(
            estimated_low,
            estimated_high,
        ),
        "budget_fit": _budget_fit(
            estimated_low=estimated_low,
            estimated_high=estimated_high,
            budget_min=budget_min,
            budget_max=budget_max,
        ),
        "over_budget": over_budget,
        "human_cost_excluded": human_cost_excluded,
        "unknown_cost_slots": unknown_cost_slots,
        "recommended_parallel_agents": budget_profile.get("recommended_parallel_agents") or 1,
        "level_counts": _level_counts(members),
    }


def _estimate_member_cost_range(
    members: list[ProjectTeamAssemblyMember],
) -> tuple[int, int | None, bool, int]:
    low_total = 0
    high_total = 0
    high_known = True
    human_cost_excluded = False
    unknown_cost_slots = 0
    for member in members:
        pricing = _dict_or_empty(member.metadata.get("pricing"))
        low = pricing.get("monthly_low")
        high = pricing.get("monthly_high")
        if member.kind == "human":
            human_cost_excluded = True
            continue
        member_cost_known = isinstance(low, int) and isinstance(high, int)
        if isinstance(low, int):
            low_total += low
        if isinstance(high, int):
            high_total += high
        else:
            high_known = False
        if not member_cost_known:
            unknown_cost_slots += 1
    return (
        low_total,
        high_total if high_known else None,
        human_cost_excluded,
        unknown_cost_slots,
    )


def _budget_fit(
    *,
    estimated_low: int,
    estimated_high: int | None,
    budget_min: Any,
    budget_max: Any,
) -> str:
    if not isinstance(budget_max, int):
        return "custom"
    comparable = estimated_high if estimated_high is not None else estimated_low
    if comparable > budget_max:
        return "over_budget"
    if isinstance(budget_min, int) and comparable < budget_min:
        return "under_budget"
    return "within_budget"


def _format_monthly_range(low: int, high: int | None) -> str:
    if high is None:
        return f"CNY {low:,}+ / month"
    if low == high:
        return f"CNY {low:,} / month"
    return f"CNY {low:,}-{high:,} / month"


def _level_counts(members: list[ProjectTeamAssemblyMember]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for member in members:
        level = member.level or "unknown"
        counts[level] = counts.get(level, 0) + 1
    return counts


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _blueprint_project_name(prompt: str, explicit: str | None) -> str:
    source = (explicit or prompt).replace("\n", " ").strip()
    source = re.sub(r"\s+", " ", source)
    if not source:
        return "新项目"
    return source if len(source) <= 28 else f"{source[:28]}..."


def _budget_profile_for(tier: str) -> dict[str, Any]:
    profiles = {
        "lean": {
            "label": "精简",
            "monthly_budget": "¥10k-30k",
            "monthly_budget_min": 10000,
            "monthly_budget_max": 30000,
            "team_size": "1-3",
            "fit": "探索、验证、轻量交付",
            "delivery_speed": "标准",
            "human_ratio": "低",
            "recommended_parallel_agents": 1,
        },
        "standard": {
            "label": "标准",
            "monthly_budget": "¥30k-100k",
            "monthly_budget_min": 30000,
            "monthly_budget_max": 100000,
            "team_size": "3-6",
            "fit": "稳定推进、跨角色协作",
            "delivery_speed": "较快",
            "human_ratio": "中",
            "recommended_parallel_agents": 2,
        },
        "premium": {
            "label": "旗舰",
            "monthly_budget": "¥100k-300k",
            "monthly_budget_min": 100000,
            "monthly_budget_max": 300000,
            "team_size": "6-10",
            "fit": "多线并行、快速交付",
            "delivery_speed": "快",
            "human_ratio": "中高",
            "recommended_parallel_agents": 4,
        },
        "enterprise": {
            "label": "企业",
            "monthly_budget": "定制",
            "monthly_budget_min": 300000,
            "monthly_budget_max": None,
            "team_size": "10+",
            "fit": "长期项目、合规治理、跨部门协作",
            "delivery_speed": "定制",
            "human_ratio": "高",
            "recommended_parallel_agents": 6,
        },
    }
    return dict(profiles.get(tier, profiles["standard"]))


def _capability_model_for_budget(tier: str) -> dict[str, Any]:
    profile = _budget_profile_for(tier)
    return {
        "version": 1,
        "budget_tier": tier,
        "pricing_currency": "CNY",
        "recommended_parallel_agents": profile["recommended_parallel_agents"],
        "levels": {
            "junior": {"score": "50-64", "price_multiplier": 0.6},
            "mid": {"score": "65-79", "price_multiplier": 1.0},
            "senior": {"score": "80-89", "price_multiplier": 1.6},
            "expert": {"score": "90-96", "price_multiplier": 2.4},
            "owner": {"score": "human", "price_multiplier": None},
        },
        "role_value_basis": [
            "execution_scope",
            "domain_context",
            "tool_pack",
            "risk_ownership",
            "human_approval_need",
        ],
    }


def _team_roles_for_budget(tier: str) -> list[dict[str, Any]]:
    if tier == "lean":
        return [
            _role_blueprint(
                "agent",
                "planner",
                "项目规划 Agent",
                "mid",
                74,
                6000,
                12000,
                ["goal_breakdown", "market_scan", "gantt_planning", "risk_register"],
                ["web_read", "fs_writer"],
                "压缩承担规划、轻量调研、风险识别和第一版路线图。",
            ),
            _role_blueprint(
                "digital_twin",
                "domain_operator",
                "领域数字分身",
                "senior",
                82,
                8000,
                18000,
                ["domain_judgement", "review", "business_context"],
                ["web_read"],
                "承载真人经验、偏好和业务判断，辅助验证关键假设。",
            ),
            _role_blueprint(
                "human",
                "decision_owner",
                "决策负责人",
                "owner",
                95,
                None,
                None,
                ["budget", "contract", "offline_resources"],
                [],
                "负责预算、法务、线下资源和最终取舍。",
            ),
        ]
    if tier == "premium":
        return [
            _role_blueprint(
                "agent",
                "planner",
                "项目规划 Agent",
                "expert",
                92,
                15000,
                32000,
                ["goal_breakdown", "gantt_planning", "risk_register", "parallel_coordination"],
                ["fs_writer"],
                "拆解目标、里程碑、依赖、预算和并行执行节奏。",
            ),
            _role_blueprint(
                "agent",
                "researcher",
                "调研 Agent",
                "senior",
                88,
                12000,
                26000,
                ["market_research", "web_search", "evidence_digest", "competitive_scan"],
                ["web_read", "fs_writer"],
                "持续收集市场、技术、运营和竞品证据。",
            ),
            _role_blueprint(
                "agent",
                "builder_operator",
                "交付执行 Agent",
                "senior",
                86,
                12000,
                24000,
                ["artifact_delivery", "workflow_execution", "handoff"],
                ["fs_writer"],
                "把计划转成产物、流程、文档和可执行交付。",
            ),
            _role_blueprint(
                "agent",
                "growth_operator",
                "增长运营 Agent",
                "mid",
                78,
                8000,
                18000,
                ["channel_test", "campaign_plan", "feedback_loop"],
                ["web_read", "fs_writer"],
                "规划获客、内容、反馈收集和增长实验。",
            ),
            _role_blueprint(
                "digital_twin",
                "domain_operator",
                "领域数字分身",
                "expert",
                92,
                18000,
                45000,
                ["domain_judgement", "expert_review", "business_context"],
                ["web_read"],
                "代表专家经验参与评审、判断和关键场景复盘。",
            ),
            _role_blueprint(
                "human",
                "decision_owner",
                "决策负责人",
                "owner",
                95,
                None,
                None,
                ["budget", "contract", "offline_resources"],
                [],
                "负责预算、合同、外部资源和最终决策。",
            ),
        ]
    if tier == "enterprise":
        return [
            _role_blueprint(
                "agent",
                "planner",
                "项目规划 Agent",
                "expert",
                95,
                25000,
                50000,
                ["portfolio_planning", "gantt_planning", "risk_register", "parallel_coordination"],
                ["fs_writer"],
                "管理长期项目组合、里程碑、依赖、预算和治理节奏。",
            ),
            _role_blueprint(
                "agent",
                "researcher",
                "情报调研 Agent",
                "expert",
                93,
                20000,
                45000,
                ["market_research", "web_search", "evidence_digest", "competitive_scan"],
                ["web_read", "fs_writer"],
                "建立持续情报、竞品、市场和外部环境监测。",
            ),
            _role_blueprint(
                "agent",
                "builder_operator",
                "交付执行 Agent",
                "senior",
                88,
                16000,
                36000,
                ["artifact_delivery", "workflow_execution", "handoff"],
                ["fs_writer"],
                "推动跨职能交付、沉淀文档和执行闭环。",
            ),
            _role_blueprint(
                "agent",
                "operations_operator",
                "运营协同 Agent",
                "senior",
                86,
                14000,
                32000,
                ["process_design", "vendor_coordination", "resource_planning"],
                ["web_read", "fs_writer"],
                "协调流程、供应资源、外部伙伴和运营风险。",
            ),
            _role_blueprint(
                "agent",
                "growth_operator",
                "增长运营 Agent",
                "senior",
                84,
                14000,
                30000,
                ["channel_test", "campaign_plan", "feedback_loop"],
                ["web_read", "fs_writer"],
                "管理市场推广、获客实验和用户反馈闭环。",
            ),
            _role_blueprint(
                "agent",
                "governance_controller",
                "治理风控 Agent",
                "senior",
                88,
                16000,
                36000,
                ["compliance_check", "risk_review", "decision_log"],
                ["fs_writer"],
                "管理合规、风险、审批记录和决策留痕。",
            ),
            _role_blueprint(
                "digital_twin",
                "domain_operator",
                "领域数字分身",
                "expert",
                94,
                30000,
                80000,
                ["domain_judgement", "expert_review", "business_context"],
                ["web_read"],
                "代表专家经验参与高风险判断和关键评审。",
            ),
            _role_blueprint(
                "human",
                "decision_owner",
                "决策负责人",
                "owner",
                95,
                None,
                None,
                ["budget", "contract", "offline_resources"],
                [],
                "负责预算、合同、授权、外部资源和最终决策。",
            ),
        ]
    return [
        _role_blueprint(
            "agent",
            "planner",
            "项目规划 Agent",
            "senior",
            86,
            8000,
            18000,
            ["goal_breakdown", "gantt_planning", "risk_register", "budget_modeling"],
            ["fs_writer"],
            "拆解目标、里程碑、依赖、预算和验收标准。",
        ),
        _role_blueprint(
            "agent",
            "researcher",
            "调研 Agent",
            "mid",
            78,
            6000,
            15000,
            ["market_research", "web_search", "evidence_digest"],
            ["web_read", "fs_writer"],
            "收集市场、技术、运营和竞品证据。",
        ),
        _role_blueprint(
            "digital_twin",
            "domain_operator",
            "领域数字分身",
            "expert",
            88,
            12000,
            30000,
            ["domain_judgement", "review", "business_context"],
            ["web_read"],
            "承载真人经验、偏好和业务判断。",
        ),
        _role_blueprint(
            "human",
            "decision_owner",
            "决策负责人",
            "owner",
            95,
            None,
            None,
            ["budget", "contract", "offline_resources"],
            [],
            "负责预算、法务、合同、线下资源和最终决策。",
        ),
    ]


def _role_blueprint(
    kind: str,
    role: str,
    display_name: str,
    level: str,
    capability_score: int,
    monthly_low: int | None,
    monthly_high: int | None,
    skills: list[str],
    tool_pack: list[str],
    responsibility: str,
) -> dict[str, Any]:
    pricing = {
        "currency": "CNY",
        "monthly_low": monthly_low,
        "monthly_high": monthly_high,
        "basis": "equivalent_seat" if kind != "human" else "human_role",
    }
    return {
        "kind": kind,
        "role": role,
        "display_name": display_name,
        "level": level,
        "capability_score": capability_score,
        "monthly_cost": _monthly_cost_label(monthly_low, monthly_high, kind),
        "skills": skills,
        "responsibility": responsibility,
        "metadata": {
            "pricing": pricing,
            "skill_pack": {
                "id": f"{role}_{level}",
                "level": level,
                "skills": skills,
            },
            "tool_pack": tool_pack,
            "value_model": {
                "level": level,
                "capability_score": capability_score,
                "automation_weight": 0 if kind == "human" else 70,
                "human_approval_required": kind == "human",
            },
        },
    }


def _monthly_cost_label(
    monthly_low: int | None,
    monthly_high: int | None,
    kind: str,
) -> str:
    if kind == "human":
        return "真人岗位成本"
    if monthly_low is None or monthly_high is None:
        return "按授权/席位"
    return f"¥{monthly_low // 1000}k-{monthly_high // 1000}k 等效"


def _build_blueprint_payload(
    body: CreateProjectBlueprintRequest,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    profile = _budget_profile_for(body.budget_tier)
    return {
        "version": 1,
        "kind": "human_agent_company_blueprint",
        "prompt": body.prompt,
        "budget_tier": body.budget_tier,
        "budget_profile": profile,
        "capability_model": _capability_model_for_budget(body.budget_tier),
        "horizon_days": max(30, min(365, int(body.horizon_days))),
        "start_date": start.isoformat(),
        "target_end_date": end.isoformat(),
        "team_roles": _team_roles_for_budget(body.budget_tier),
    }


def _build_blueprint_milestones(
    project_id: str,
    *,
    start: date,
    horizon_days: int,
) -> list[ProjectMilestone]:
    spans = _milestone_spans(start, horizon_days)
    specs = [
        (
            "需求澄清与商业假设",
            "确认目标用户、约束、预算、成功标准和关键假设。",
        ),
        (
            "团队与能力装配",
            "拆分 Agent、数字分身和真人角色，评估能力等级与成本。",
        ),
        (
            "计划排期与预算",
            "形成里程碑、甘特图、依赖关系、预算区间和风险台账。",
        ),
        (
            "执行验证与增长",
            "进入交付节奏，跟踪产物、复盘风险并沉淀组织知识。",
        ),
    ]
    return [
        ProjectMilestone(
            project_id=project_id,
            title=title,
            description=description,
            planned_start_at=span_start.isoformat(),
            planned_end_at=span_end.isoformat(),
            target_date=span_end.isoformat(),
            sort_order=index + 1,
            metadata={"blueprint": True, "blueprint_step": index + 1},
        )
        for index, ((title, description), (span_start, span_end)) in enumerate(
            zip(specs, spans, strict=True),
        )
    ]


def _milestone_spans(start: date, horizon_days: int) -> list[tuple[date, date]]:
    horizon = max(30, min(365, int(horizon_days)))
    points = [
        0,
        max(7, round(horizon * 0.16)),
        max(14, round(horizon * 0.38)),
        max(28, round(horizon * 0.72)),
        horizon,
    ]
    spans: list[tuple[date, date]] = []
    for index in range(4):
        span_start = start + timedelta(days=points[index])
        span_end = start + timedelta(days=max(points[index], points[index + 1] - 1))
        spans.append((span_start, span_end))
    return spans


def _build_blueprint_tasks(
    project_id: str,
    milestones: list[ProjectMilestone],
    *,
    start: date,
) -> list[ProjectTask]:
    specs = [
        {
            "milestone_id": milestones[0].id,
            "title": "整理关键问题清单",
            "description": ("把不明确目标转成可选择的问题，用于需求问卷和下一轮确认。"),
            "priority": "high",
            "assignees": [{"kind": "agent", "ref": "planner"}],
            "offset": 2,
            "duration": 5,
        },
        {
            "milestone_id": milestones[1].id,
            "title": "生成角色与能力矩阵",
            "description": ("区分 Agent、数字分身、真人岗位，标注等级、预算和责任边界。"),
            "priority": "high",
            "assignees": [{"kind": "agent", "ref": "planner"}],
            "offset": 10,
            "duration": 7,
        },
        {
            "milestone_id": milestones[2].id,
            "title": "输出第一版里程碑甘特",
            "description": ("根据团队组合生成周期、依赖关系、预算和风险缓冲。"),
            "priority": "medium",
            "assignees": [{"kind": "agent", "ref": "synthesizer"}],
            "offset": 22,
            "duration": 10,
        },
        {
            "milestone_id": milestones[3].id,
            "title": "派发首个执行验证任务",
            "description": ("让团队基于结构化输出契约回流风险、下一步行动和决策。"),
            "priority": "high",
            "assignees": [{"kind": "agent", "ref": "synthesizer"}],
            "offset": 34,
            "duration": 7,
        },
    ]
    tasks: list[ProjectTask] = []
    for index, spec in enumerate(specs):
        planned_start = start + timedelta(days=int(spec["offset"]))
        planned_end = planned_start + timedelta(days=int(spec["duration"]))
        tasks.append(
            ProjectTask(
                project_id=project_id,
                milestone_id=str(spec["milestone_id"]),
                title=str(spec["title"]),
                description=str(spec["description"]),
                source="milestone",
                priority=str(spec["priority"]),  # type: ignore[arg-type]
                planned_start_at=planned_start.isoformat(),
                planned_end_at=planned_end.isoformat(),
                due_at=planned_end.isoformat(),
                assignees=[
                    item if isinstance(item, TaskAssignee) else TaskAssignee(**item)
                    for item in spec["assignees"]  # type: ignore[index]
                ],
                metadata={
                    "blueprint": True,
                    "blueprint_step": index + 1,
                },
            ),
        )
    return tasks


def _task_to_gantt(
    task: ProjectTask,
    dependencies_by_target: dict[str, list[str]],
) -> GanttTaskView:
    return GanttTaskView(
        id=task.id,
        name=task.title,
        milestone_id=task.milestone_id,
        start=task.planned_start_at or task.actual_start_at or task.created_at,
        end=task.planned_end_at or task.due_at or task.actual_end_at,
        progress=task.progress,
        status=task.status,
        assignee=task.owner_name or task.owner_user_id,
        dependencies=dependencies_by_target.get(task.id, []),
        is_milestone=False,
    )


def _task_artifact_views(task: ProjectTask) -> list[ProjectArtifactView]:
    raw_artifacts = task.metadata.get("team_task_artifacts")
    if not isinstance(raw_artifacts, list):
        return []

    views: list[ProjectArtifactView] = []
    for index, raw in enumerate(raw_artifacts):
        artifact = raw if isinstance(raw, dict) else {"content": raw}
        raw_id = _artifact_string(artifact.get("id"))
        path = _artifact_string(
            artifact.get("path")
            or artifact.get("file_path")
            or artifact.get("file")
            or artifact.get("filename"),
        )
        url = _artifact_string(artifact.get("url") or artifact.get("href"))
        artifact_type = _artifact_string(artifact.get("type")) or "artifact"
        content = (
            _artifact_string(artifact.get("content"))
            or _artifact_string(artifact.get("text"))
            or _artifact_string(artifact.get("summary"))
            or ""
        )
        title = (
            _artifact_string(artifact.get("title"))
            or _artifact_string(artifact.get("name"))
            or _filename_from_path(path)
            or task.title
        )
        created_at = (
            _artifact_string(artifact.get("created_at"))
            or _artifact_string(artifact.get("updated_at"))
            or _artifact_string(artifact.get("timestamp"))
            or task.actual_end_at
            or task.updated_at
        )
        metadata = {
            "task_title": task.title,
            "task_status": task.status,
            "raw": {
                key: value
                for key, value in artifact.items()
                if key not in {"content", "text", "summary"}
            },
        }
        stable_id = raw_id or path or str(index + 1)
        views.append(
            ProjectArtifactView(
                id=f"{task.id}:{stable_id}",
                project_id=task.project_id,
                task_id=task.id,
                team_task_id=task.team_task_id,
                source="team_task",
                type=artifact_type,
                title=title,
                content=content,
                path=path,
                url=url,
                created_at=created_at,
                metadata=metadata,
            ),
        )
    return views


def _artifact_insight_views(
    artifact: ProjectArtifactView,
) -> list[ProjectInsightView]:
    raw = artifact.metadata.get("raw")
    payloads: list[dict[str, Any]] = []
    _append_insight_payload(payloads, raw if isinstance(raw, dict) else {})
    parsed_content = _json_object_from_text(artifact.content)
    if isinstance(parsed_content, dict):
        _append_insight_payload(payloads, parsed_content)

    insights: list[ProjectInsightView] = []
    seen: set[tuple[str, str, str]] = set()
    for payload in payloads:
        for kind, keys in _INSIGHT_KEYS.items():
            for key in keys:
                for index, item in enumerate(_insight_items(payload.get(key))):
                    view = _insight_view_from_item(
                        artifact,
                        kind=kind,
                        key=key,
                        index=index,
                        item=item,
                    )
                    identity = (view.kind, view.title, view.detail)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    insights.append(view)
        role_outputs = payload.get("role_outputs")
        if isinstance(role_outputs, list):
            for role_index, role_output in enumerate(role_outputs):
                if not isinstance(role_output, dict):
                    continue
                parsed_output = _json_object_from_text(role_output.get("output"))
                if not isinstance(parsed_output, dict):
                    continue
                role_artifact = artifact.model_copy(
                    update={
                        "metadata": {
                            **dict(artifact.metadata),
                            "role": role_output.get("role"),
                            "agent_id": role_output.get("agent_id"),
                        },
                    }
                )
                role_payloads: list[dict[str, Any]] = []
                _append_insight_payload(role_payloads, parsed_output)
                for role_payload in role_payloads:
                    for key_kind, keys in _INSIGHT_KEYS.items():
                        for key in keys:
                            for index, item in enumerate(
                                _insight_items(role_payload.get(key)),
                            ):
                                view = _insight_view_from_item(
                                    role_artifact,
                                    kind=key_kind,
                                    key=f"role_outputs.{role_index}.{key}",
                                    index=index,
                                    item=item,
                                )
                                identity = (view.kind, view.title, view.detail)
                                if identity in seen:
                                    continue
                                seen.add(identity)
                                insights.append(view)
    return insights


def _append_insight_payload(
    payloads: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    payloads.append(payload)
    for key in ("project_update", "projectUpdate", "project_management_update"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            payloads.append(nested)


def _insight_view_from_item(
    artifact: ProjectArtifactView,
    *,
    kind: str,
    key: str,
    index: int,
    item: Any,
) -> ProjectInsightView:
    payload = item if isinstance(item, dict) else {"title": item}
    title = (
        _artifact_string(payload.get("title"))
        or _artifact_string(payload.get("name"))
        or _artifact_string(payload.get("summary"))
        or _artifact_string(payload.get("action"))
        or _artifact_string(payload.get("decision"))
        or _artifact_string(payload.get("risk"))
        or _artifact_string(payload.get("description"))
        or _artifact_string(item)
        or "Untitled insight"
    )
    detail = (
        _artifact_string(payload.get("detail"))
        or _artifact_string(payload.get("description"))
        or _artifact_string(payload.get("reason"))
        or _artifact_string(payload.get("rationale"))
        or ""
    )
    owner = (
        _artifact_string(payload.get("owner"))
        or _artifact_string(payload.get("assignee"))
        or _artifact_string(payload.get("role"))
    )
    created_at = (
        _artifact_string(payload.get("created_at"))
        or _artifact_string(payload.get("timestamp"))
        or artifact.created_at
    )
    return ProjectInsightView(
        id=f"{artifact.id}:{key}:{index + 1}",
        project_id=artifact.project_id,
        task_id=artifact.task_id,
        team_task_id=artifact.team_task_id,
        source_artifact_id=artifact.id,
        kind=kind,  # type: ignore[arg-type]
        title=title,
        detail=detail,
        severity=_artifact_string(payload.get("severity") or payload.get("level")),
        owner=owner,
        due_at=_artifact_string(payload.get("due_at") or payload.get("deadline")),
        status=_artifact_string(payload.get("status")),
        created_at=created_at,
        metadata={
            "source_key": key,
            "source_type": artifact.type,
            "task_title": artifact.metadata.get("task_title"),
            "raw": payload,
            **{
                key: value
                for key, value in artifact.metadata.items()
                if key in {"role", "agent_id"}
            },
        },
    )


def _insight_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    text = _artifact_string(value)
    return [text] if text else []


def _json_object_from_text(value: Any) -> dict[str, Any] | None:
    text = _artifact_string(value)
    if not text:
        return None
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidates.append(match.group(1))
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    return candidates


def _artifact_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _filename_from_path(path: str | None) -> str | None:
    if not path:
        return None
    return path.replace("\\", "/").rstrip("/").split("/")[-1] or None


_INSIGHT_KEYS = {
    "risk": ("risks", "risk_items", "project_risks", "risk"),
    "next_action": (
        "next_actions",
        "action_items",
        "actions",
        "next_steps",
        "todos",
    ),
    "decision": ("decisions", "decision_log", "project_decisions", "decision"),
}


__all__ = ["CompanyStore"]
