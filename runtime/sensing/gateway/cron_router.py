"""Cron settings compatibility router.

The settings UI still talks to ``/api/cron`` for simple user-defined jobs.
This router keeps that compatibility layer out of ``app.py`` while sharing
the same cwd-relative data path as the rest of the platform runtime.

Cron jobs drive arbitrary ``command`` strings on a schedule — full RCE
once the job fires — so every mutation end-point forces authentication
and binds the job to the creator's actor id.  A user can only delete
their own jobs (an identity without ``admin`` role is scoped to its own
actor); an admin may delete anything.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = object  # type: ignore[assignment, misc]

from runtime.execution.cron_store import _read_cron_jobs, _write_cron_jobs
from runtime.platform.process.paths import app_paths


def _actor_is_admin(identity_store: Any, actor: str | None) -> bool:
    if not actor or identity_store is None:
        return False
    try:
        ident = identity_store.get(actor) if hasattr(identity_store, "get") else None
        if ident is None:
            return False
        roles = getattr(ident, "roles", None) or []
        return "admin" in roles or "root" in roles
    except Exception:
        return False


def create_cron_router(
    jobs_path: Path | str | None = None,
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    """Create the ``/api/cron`` compatibility router."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI is required for cron router")

    path = Path(jobs_path) if jobs_path is not None else app_paths().cron_jobs_path
    router = APIRouter()

    def _force_auth(request: Any) -> str | None:
        """Resolve actor and require a token regardless of global
        ``require_auth``.

        Cron jobs execute shell commands; anonymous create would be
        arbitrary RCE.  Always force Bearer auth when ``identity_store``
        is configured.  When no identity store is configured at all
        (old, single-user local dev), fall back to the global flag.
        """
        try:
            from runtime.sensing.gateway.openai_gateway import _resolve_actor

            force = True if identity_store is not None else require_auth
            return _resolve_actor(
                request, identity_store, force,
                jwt_secret=jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(401, "auth required") from exc

    @router.get("/api/cron")
    @router.get("/api/cron/")
    def api_cron_list(request: Request) -> list[dict[str, Any]]:
        actor = _force_auth(request)
        jobs = _read_cron_jobs(path)
        if _actor_is_admin(identity_store, actor):
            return jobs
        return [
            j for j in jobs
            if j.get("creator_actor") == actor
            or j.get("creator_actor") in (None, "*")  # legacy / anon
        ]

    @router.post("/api/cron")
    @router.post("/api/cron/")
    async def api_cron_create(request: Request) -> dict[str, Any]:
        actor = _force_auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "invalid cron job")

        name = str(body.get("name") or "").strip()
        command = str(body.get("command") or "").strip()
        cron_expression = str(body.get("cron_expression") or "0 * * * *").strip()
        if not name:
            raise HTTPException(400, "name is required")
        if not command:
            raise HTTPException(400, "command is required")
        if "/" in name or "\\" in name:
            raise HTTPException(400, "name cannot contain path separators")
        try:
            from runtime.adapters.scheduler.cron import CronExpression

            CronExpression.parse(cron_expression)
        except Exception as exc:
            raise HTTPException(400, f"invalid cron expression: {exc}") from exc

        # A non-admin cannot overwrite a job created by someone else.
        existing = _read_cron_jobs(path)
        for j in existing:
            if j.get("name") != name:
                continue
            owner = j.get("creator_actor")
            if (
                owner not in (None, "*", actor)
                and not _actor_is_admin(identity_store, actor)
            ):
                raise HTTPException(
                    409,
                    "cron job name already used by another actor",
                )
            break

        jobs = [j for j in existing if j.get("name") != name]
        job = {
            "name": name,
            "command": command,
            "cron_expression": cron_expression,
            "last_run": None,
            "last_status": "created",
            "creator_actor": actor or "*",
        }
        jobs.append(job)
        _write_cron_jobs(path, jobs)
        return job

    @router.delete("/api/cron/{name}")
    def api_cron_delete(name: str, request: Request) -> dict[str, Any]:
        actor = _force_auth(request)
        is_admin = _actor_is_admin(identity_store, actor)
        jobs = _read_cron_jobs(path)
        target = next((j for j in jobs if j.get("name") == name), None)
        if target is None:
            raise HTTPException(404, "cron job not found")
        owner = target.get("creator_actor")
        if not is_admin and owner not in (None, "*", actor):
            raise HTTPException(403, "not owner of this cron job")
        next_jobs = [j for j in jobs if j.get("name") != name]
        _write_cron_jobs(path, next_jobs)
        return {"ok": True, "deleted": name}

    return router
