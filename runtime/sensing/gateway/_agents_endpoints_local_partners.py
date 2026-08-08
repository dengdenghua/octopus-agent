"""LocalPartner endpoints for the agents router.

Pure structural split of ``_agents_endpoints.py`` — no logic changes.
``_register_local_partners`` attaches the local CLI partner endpoints
(list / doctor / model / probe / register) to the injected router.

The two ``_which_local_partner_command`` / ``_safe_local_partner_executable``
wrappers are injected from ``_agents_endpoints`` so their dynamic
resolution through the parent ``agents_router`` module (monkeypatched by
tests) is preserved exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from fastapi import HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from ._agents_endpoints_shared import _AuthActions
from ._agents_helpers import _to_detail_wire
from .agents_local_partner import (
    LOCAL_PARTNER_SPECS as _LOCAL_PARTNER_SPECS,
)
from .agents_local_partner import (
    doctor_summary as _local_partner_doctor_summary,
)
from .agents_local_partner import (
    partner_model as _partner_model,
)
from .agents_local_partner import (
    probe_partner as _probe_local_partner,
)
from .agents_local_partner import (
    readiness_for_partner as _local_partner_readiness,
)
from .agents_local_partner import (
    to_wire as _local_partner_wire,
)
from .agents_local_partner import (
    validate_alias as _validate_local_partner_alias,
)
from .agents_local_partner import (
    write_partner_agent as _write_local_partner_agent,
)
from .agents_models import (
    LocalPartnerDoctorResponse,
    LocalPartnerProbeResponse,
    LocalPartnerRegisterRequest,
    LocalPartnerRegisterResponse,
    LocalPartnerRegisterResult,
    LocalPartnerWire,
)

if TYPE_CHECKING:
    from ._agents_endpoints import _AgentsCtx


def _register_local_partners(
    router: Any,
    ctx: _AgentsCtx,
    auth: _AuthActions,
    _which_local_partner_command: Any,
    _safe_local_partner_executable: Any,
) -> None:
    registry = ctx.registry
    runtime = ctx.runtime
    _auth = auth.auth
    _require_admin = auth.require_admin

    @router.get("/api/agents/local-partners")
    def list_local_partners(request: Request) -> dict[str, list[LocalPartnerWire]]:
        # Listing is read-only — does NOT require admin (a regular
        # user can ask "what's installed" without being able to register).
        _auth(request)  # AUTH-OK: actor-agnostic — registry is server-global
        return {
            "partners": [
                _local_partner_wire(
                    spec,
                    registry,
                    which_fn=_which_local_partner_command,
                )
                for spec in _LOCAL_PARTNER_SPECS.values()
            ]
        }

    @router.get("/api/agents/local-partners/doctor")
    def local_partners_doctor(request: Request) -> LocalPartnerDoctorResponse:
        # Read-only doctor summary: safe for regular users, no subprocesses.
        _auth(request)  # AUTH-OK: actor-agnostic — summarizes local detection only
        partners = [
            _local_partner_wire(
                spec,
                registry,
                which_fn=_which_local_partner_command,
            )
            for spec in _LOCAL_PARTNER_SPECS.values()
        ]
        return LocalPartnerDoctorResponse(**_local_partner_doctor_summary(partners))

    @router.get("/api/agents/local-partners/{partner_id}/model")
    def get_local_partner_model(request: Request, partner_id: str) -> dict[str, Any]:
        # Read-only: the CLI partner's OWN configured default model (codex/claude
        # namespace), for the UI to display instead of octopus's model selector.
        _auth(request)  # AUTH-OK: actor-agnostic, reads local CLI config only
        if partner_id not in _LOCAL_PARTNER_SPECS:
            raise HTTPException(404, f"unknown local partner: {partner_id}")
        return _partner_model(partner_id)

    @router.post("/api/agents/local-partners/{partner_id}/probe")
    def probe_local_partner(request: Request, partner_id: str) -> LocalPartnerProbeResponse:
        # Spawns the local external CLI once, so it is admin-only in deployed
        # auth mode. Single-user dev mode remains friction-free.
        _require_admin(request)
        spec = _LOCAL_PARTNER_SPECS.get(partner_id)
        if spec is None:
            raise HTTPException(404, f"unknown local partner: {partner_id}")
        command, executable = _which_local_partner_command(list(spec["commands"]))
        if executable and not _safe_local_partner_executable(executable):
            return LocalPartnerProbeResponse(
                id=partner_id,
                agent_id=str(spec["agent_id"]),
                ok=False,
                detected=True,
                ready=False,
                status="unsafe_executable",
                command=command,
                executable=executable,
                error=f"refusing to run executable from a user-writable location: {executable}",
                raw_error="",
                failure_kind="unsafe_executable",
                failure_title="本地 CLI 路径不安全",
                fix_hint="请从官方安装位置启动 CLI，并确认 PATH 没有被当前项目目录污染。",
            )
        return LocalPartnerProbeResponse(
            **_probe_local_partner(
                partner_id,
                command=command,
                executable=executable,
            )
        )

    @router.post("/api/agents/local-partners/register")
    def register_local_partners(
        request: Request,
        body: LocalPartnerRegisterRequest,
    ) -> LocalPartnerRegisterResponse:
        # Mutates the global agent registry, writes SOUL.md / IDENTITY.md
        # under default_agents_root(), and binds the agent to a real
        # subprocess command. Admin-only when require_auth=True.
        _require_admin(request)
        if runtime is None:
            raise HTTPException(
                503, "local partner registration needs a GraphRuntime in this router"
            )
        if not body.partners:
            raise HTTPException(400, "at least one local partner is required")

        # Reject the whole request on any malformed alias before we
        # start writing files — atomic from the caller's POV.
        validated_aliases: dict[str, str] = {}
        for item in body.partners:
            try:
                validated_aliases[item.id] = _validate_local_partner_alias(item.alias)
            except ValueError as exc:
                raise HTTPException(400, f"{item.id}: {exc}") from exc

        results: list[LocalPartnerRegisterResult] = []
        registered_count = 0
        already_exists_count = 0
        skipped_count = 0

        for item in body.partners:
            spec = _LOCAL_PARTNER_SPECS.get(item.id)
            if spec is None:
                skipped_count += 1
                results.append(
                    LocalPartnerRegisterResult(
                        id=item.id,
                        agent_id="",
                        status="error",
                        message=f"unknown local partner: {item.id}",
                    )
                )
                continue

            agent_id = str(spec["agent_id"])
            alias = validated_aliases[item.id] or str(spec["default_alias"])
            if registry.has(agent_id):
                already_exists_count += 1
                results.append(
                    LocalPartnerRegisterResult(
                        id=str(spec["id"]),
                        agent_id=agent_id,
                        status="already_exists",
                        message="already registered",
                        agent=_to_detail_wire(registry.get(agent_id)),
                    )
                )
                continue

            command, executable = _which_local_partner_command(list(spec["commands"]))
            if not executable or not command:
                skipped_count += 1
                results.append(
                    LocalPartnerRegisterResult(
                        id=str(spec["id"]),
                        agent_id=agent_id,
                        status="not_detected",
                        message="local executable was not found on PATH",
                    )
                )
                continue

            readiness = _local_partner_readiness(str(spec["id"]), command, executable)
            if not readiness.get("ready"):
                skipped_count += 1
                results.append(
                    LocalPartnerRegisterResult(
                        id=str(spec["id"]),
                        agent_id=agent_id,
                        status=str(readiness.get("readiness_status") or "not_ready"),
                        message=str(
                            readiness.get("readiness_message") or "local partner is not ready"
                        ),
                    )
                )
                continue

            # PATH-poisoning guard: reject executables that resolve into
            # the user's home or the current working directory subtree.
            # An attacker dropping ``claude.cmd`` in cwd would otherwise
            # win the PATH race.
            if not _safe_local_partner_executable(executable):
                skipped_count += 1
                results.append(
                    LocalPartnerRegisterResult(
                        id=str(spec["id"]),
                        agent_id=agent_id,
                        status="error",
                        message=(
                            f"refusing to register executable from a user-writable "
                            f"location: {executable}"
                        ),
                    )
                )
                continue

            try:
                agent = _write_local_partner_agent(
                    spec=spec,
                    alias=alias,
                    command=command,
                    executable=executable,
                    runtime=runtime,
                    registry=registry,
                )
            except (OSError, ValueError, TypeError) as exc:
                skipped_count += 1
                results.append(
                    LocalPartnerRegisterResult(
                        id=str(spec["id"]),
                        agent_id=agent_id,
                        status="error",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            registered_count += 1
            results.append(
                LocalPartnerRegisterResult(
                    id=str(spec["id"]),
                    agent_id=agent_id,
                    status="registered",
                    message="registered",
                    agent=_to_detail_wire(agent),
                )
            )

        return LocalPartnerRegisterResponse(
            results=results,
            registered_count=registered_count,
            already_exists_count=already_exists_count,
            skipped_count=skipped_count,
        )
