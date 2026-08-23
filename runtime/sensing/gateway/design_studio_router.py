"""Local creative-workbench integrations used by the Design canvas."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from runtime.platform.process.paths import app_paths
from runtime.sensing.gateway.comfyui_supervisor import (
    process_status as comfyui_process_status,
    resolve_comfyui_home,
    start_comfyui,
    stop_comfyui,
)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._\-\u4e00-\u9fff]+")
_SAFE_PROJECT_ID = re.compile(r"^[a-zA-Z0-9._-]{1,160}$")
_CANVAS_LOCK = threading.RLock()
_MAX_CANVAS_BYTES = 2 * 1024 * 1024
_COMFY_MODEL_GROUPS = (
    "checkpoints",
    "diffusion_models",
    "loras",
    "vae",
    "controlnet",
)
_COMFY_MODEL_SUFFIXES = frozenset({".safetensors", ".ckpt", ".pt", ".pth", ".bin"})


class WorkflowImport(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workflow: dict[str, Any]
    ui: dict[str, Any] = Field(default_factory=dict)


class WorkflowSave(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workflow: dict[str, Any]
    ui: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int = Field(default=0, ge=0)


class QueueRequest(BaseModel):
    prompt: dict[str, Any] | None = None
    workflow_id: str | None = Field(default=None, max_length=80)
    client_id: str | None = Field(default=None, max_length=120)


class CanvasSave(BaseModel):
    document: dict[str, Any]
    expected_revision: int = Field(default=0, ge=0)


def _comfyui_url() -> str:
    raw = os.environ.get("OCTOPUS_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("OCTOPUS_COMFYUI_URL must point to a local HTTP service")
    return raw


def _comfyui_home() -> Path | None:
    return resolve_comfyui_home()


def _comfyui_dependencies() -> dict[str, Any]:
    """Summarize user-managed ComfyUI assets without modifying the installation."""
    home = _comfyui_home()
    configured = bool(os.environ.get("OCTOPUS_COMFYUI_HOME", "").strip())
    model_counts = {group: 0 for group in _COMFY_MODEL_GROUPS}
    custom_nodes: list[str] = []
    if home is not None:
        models_dir = home / "models"
        for group in _COMFY_MODEL_GROUPS:
            directory = models_dir / group
            if not directory.is_dir():
                continue
            model_counts[group] = sum(
                1
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.lower() in _COMFY_MODEL_SUFFIXES
            )
        nodes_dir = home / "custom_nodes"
        if nodes_dir.is_dir():
            custom_nodes = sorted(
                path.name
                for path in nodes_dir.iterdir()
                if path.is_dir() and not path.name.startswith((".", "_"))
            )[:200]
    return {
        "detected": home is not None,
        "configured": configured,
        "path": str(home) if home is not None else None,
        "model_counts": model_counts,
        "total_models": sum(model_counts.values()),
        "custom_nodes": custom_nodes,
        "total_custom_nodes": len(custom_nodes),
        "managed": False,
    }


def _workflow_dir() -> Path:
    target = app_paths().data_dir / "design" / "comfyui-workflows"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _bundled_workflow_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "platform"
        / "plugins"
        / "bundled"
        / "comfyui_bridge"
        / "workflows"
    )


def _canvas_dir() -> Path:
    target = app_paths().data_dir / "design" / "project-canvases"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _canvas_path(project_id: str) -> Path:
    if not _SAFE_PROJECT_ID.fullmatch(project_id):
        raise HTTPException(404, "project not found")
    return _canvas_dir() / f"{project_id}.json"


def _read_canvas(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "project canvas is unreadable") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("document"), dict):
        raise HTTPException(500, "project canvas is invalid")
    return payload


def _workflow_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow"), dict):
        return None
    return payload


def create_design_studio_router(
    *,
    project_store: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    def _auth_dep(request: Request) -> None:
        from runtime.safety.auth.principal import resolve_principal

        principal = resolve_principal(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        request.state.design_principal = principal

    def _scoped_project_store(request: Request) -> Any:
        if project_store is None:
            return None
        principal = getattr(request.state, "design_principal", None)
        if principal is None:
            return project_store
        from runtime.safety.auth.scope import scope_from_principal

        allow_cross_tenant = bool(principal.roles.intersection({"admin", "operator"}))
        with_scope = getattr(project_store, "with_scope", None)
        return (
            with_scope(
                scope_from_principal(
                    principal,
                    allow_cross_tenant=allow_cross_tenant,
                )
            )
            if callable(with_scope)
            else project_store
        )

    def _require_project(request: Request, project_id: str) -> None:
        scoped = _scoped_project_store(request)
        if scoped is None:
            return
        getter = getattr(scoped, "get_project", None)
        if not callable(getter) or getter(project_id) is None:
            raise HTTPException(404, "project not found")

    router = APIRouter(
        prefix="/api/design",
        tags=["design-studio"],
        dependencies=[Depends(_auth_dep)],
    )

    @router.get("/projects/{project_id}/canvas")
    def get_project_canvas(request: Request, project_id: str) -> dict[str, Any]:
        _require_project(request, project_id)
        path = _canvas_path(project_id)
        with _CANVAS_LOCK:
            payload = _read_canvas(path)
        if payload is None:
            return {
                "project_id": project_id,
                "revision": 0,
                "document": None,
                "updated_at": None,
            }
        return {"project_id": project_id, **payload}

    @router.put("/projects/{project_id}/canvas")
    def save_project_canvas(
        request: Request,
        project_id: str,
        body: CanvasSave,
    ) -> dict[str, Any]:
        _require_project(request, project_id)
        encoded_document = json.dumps(body.document, ensure_ascii=False).encode("utf-8")
        if len(encoded_document) > _MAX_CANVAS_BYTES:
            raise HTTPException(413, "project canvas is too large")
        path = _canvas_path(project_id)
        with _CANVAS_LOCK:
            current = _read_canvas(path)
            current_revision = int((current or {}).get("revision") or 0)
            if body.expected_revision != current_revision:
                raise HTTPException(
                    409,
                    {
                        "code": "CANVAS_REVISION_CONFLICT",
                        "revision": current_revision,
                    },
                )
            payload = {
                "revision": current_revision + 1,
                "document": body.document,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        return {"project_id": project_id, **payload}

    @router.get("/comfyui/status")
    async def comfyui_status() -> dict[str, Any]:
        try:
            base_url = _comfyui_url()
        except RuntimeError as exc:
            return {"online": False, "state": "invalid_config", "detail": str(exc)}
        try:
            async with httpx.AsyncClient(timeout=1.8) as client:
                response = await client.get(f"{base_url}/system_stats")
                response.raise_for_status()
                payload = response.json()
            return {
                "online": True,
                "state": "online",
                "base_url": base_url,
                "system": payload,
                "process": comfyui_process_status(),
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "online": False,
                "state": "offline",
                "base_url": base_url,
                "detail": str(exc),
                "process": comfyui_process_status(),
            }

    @router.get("/comfyui/dependencies")
    def comfyui_dependencies() -> dict[str, Any]:
        return _comfyui_dependencies()

    @router.post("/comfyui/start")
    async def comfyui_start() -> dict[str, Any]:
        try:
            base_url = _comfyui_url()
            async with httpx.AsyncClient(timeout=0.7) as client:
                response = await client.get(f"{base_url}/system_stats")
            if response.status_code < 500:
                return {
                    "ok": True,
                    "state": "already_running",
                    "process": comfyui_process_status(),
                }
        except (RuntimeError, httpx.HTTPError):
            pass
        state = start_comfyui()
        return {
            "ok": state in {"started", "already_started"},
            "state": state,
            "process": comfyui_process_status(),
        }

    @router.post("/comfyui/stop")
    def comfyui_stop() -> dict[str, Any]:
        state = stop_comfyui()
        return {
            "ok": state in {"stopped", "already_stopped"},
            "state": state,
            "process": comfyui_process_status(),
        }

    @router.get("/comfyui/object-info")
    async def comfyui_object_info() -> dict[str, Any]:
        """Return a compact, UI-safe view of locally installed ComfyUI nodes."""
        try:
            base_url = _comfyui_url()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                response = await client.get(f"{base_url}/object_info")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "local ComfyUI node catalog is unavailable") from exc
        if not isinstance(payload, dict):
            raise HTTPException(502, "local ComfyUI returned an invalid node catalog")
        nodes: list[dict[str, Any]] = []
        for class_type, raw in list(payload.items())[:2000]:
            if not isinstance(class_type, str) or not isinstance(raw, dict):
                continue
            inputs: list[dict[str, Any]] = []
            input_groups = raw.get("input") if isinstance(raw.get("input"), dict) else {}
            for group in ("required", "optional"):
                definitions = input_groups.get(group)
                if not isinstance(definitions, dict):
                    continue
                for input_name, spec in list(definitions.items())[:100]:
                    if not isinstance(input_name, str):
                        continue
                    input_type: Any = spec
                    options: dict[str, Any] = {}
                    if isinstance(spec, list) and spec:
                        input_type = spec[0]
                        if len(spec) > 1 and isinstance(spec[1], dict):
                            options = spec[1]
                    inputs.append(
                        {
                            "name": input_name,
                            "type": input_type,
                            "optional": group == "optional",
                            "default": options.get("default"),
                        }
                    )
            nodes.append(
                {
                    "class_type": class_type,
                    "title": raw.get("display_name") or raw.get("name") or class_type,
                    "category": raw.get("category") or "其他",
                    "inputs": inputs,
                }
            )
        nodes.sort(key=lambda item: (str(item["category"]), str(item["title"])))
        return {"online": True, "items": nodes, "total": len(nodes)}

    @router.get("/comfyui/workflows")
    def list_workflows() -> dict[str, Any]:
        indexed: dict[str, dict[str, Any]] = {}
        for source, directory in (
            ("bundled", _bundled_workflow_dir()),
            ("user", _workflow_dir()),
        ):
            for path in sorted(directory.glob("*.json")):
                payload = _workflow_payload(path)
                if payload is None:
                    continue
                indexed[path.stem] = {
                    "id": path.stem,
                    "name": payload.get("name", path.stem),
                    "description": payload.get("description", ""),
                    "tags": payload.get("tags", []),
                    "source": source,
                    "revision": int(payload.get("revision") or 0),
                }
        items = list(indexed.values())
        return {"items": items, "total": len(items)}

    @router.get("/comfyui/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        safe_id = _SAFE_NAME.sub("-", workflow_id.strip()).strip("-.")[:80]
        if not safe_id or safe_id != workflow_id:
            raise HTTPException(404, "workflow not found")
        for source, directory in (
            ("user", _workflow_dir()),
            ("bundled", _bundled_workflow_dir()),
        ):
            path = directory / f"{safe_id}.json"
            payload = _workflow_payload(path)
            if payload is not None:
                return {"id": safe_id, "source": source, **payload}
        raise HTTPException(404, "workflow not found")

    @router.post("/comfyui/workflows/import")
    def import_workflow(body: WorkflowImport) -> dict[str, Any]:
        slug = _SAFE_NAME.sub("-", body.name.strip()).strip("-.")[:80]
        if not slug:
            raise HTTPException(400, "workflow name has no usable characters")
        target = _workflow_dir() / f"{slug}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "name": body.name.strip(),
                    "workflow": body.workflow,
                    "ui": body.ui,
                    "revision": 1,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(target)
        return {"ok": True, "id": slug, "name": body.name.strip(), "revision": 1}

    @router.put("/comfyui/workflows/{workflow_id}")
    def save_workflow(workflow_id: str, body: WorkflowSave) -> dict[str, Any]:
        safe_id = _SAFE_NAME.sub("-", workflow_id.strip()).strip("-.")[:80]
        if not safe_id or safe_id != workflow_id:
            raise HTTPException(404, "workflow not found")
        target = _workflow_dir() / f"{safe_id}.json"
        current = _workflow_payload(target)
        current_revision = int((current or {}).get("revision") or 0)
        if body.expected_revision != current_revision:
            raise HTTPException(
                409,
                {
                    "code": "WORKFLOW_REVISION_CONFLICT",
                    "revision": current_revision,
                },
            )
        payload = {
            "name": body.name.strip(),
            "workflow": body.workflow,
            "ui": body.ui,
            "revision": current_revision + 1,
        }
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return {"ok": True, "id": safe_id, **payload}

    @router.post("/comfyui/queue")
    async def queue_workflow(body: QueueRequest) -> dict[str, Any]:
        try:
            base_url = _comfyui_url()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        prompt = body.prompt
        if prompt is None and body.workflow_id:
            safe_id = _SAFE_NAME.sub("-", body.workflow_id.strip()).strip("-.")[:80]
            if not safe_id or safe_id != body.workflow_id:
                raise HTTPException(404, "workflow not found")
            for directory in (_workflow_dir(), _bundled_workflow_dir()):
                workflow_payload = _workflow_payload(directory / f"{safe_id}.json")
                if workflow_payload is not None:
                    prompt = workflow_payload["workflow"]
                    break
        if not prompt:
            raise HTTPException(400, "prompt or workflow_id is required")
        payload: dict[str, Any] = {"prompt": prompt}
        if body.client_id:
            payload["client_id"] = body.client_id
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(f"{base_url}/prompt", json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(503, f"ComfyUI is unavailable: {exc}") from exc

    @router.get("/comfyui/history/{prompt_id}")
    async def comfyui_history(prompt_id: str) -> dict[str, Any]:
        if not prompt_id or len(prompt_id) > 160 or "/" in prompt_id:
            raise HTTPException(404, "prompt not found")
        try:
            base_url = _comfyui_url()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{base_url}/history/{prompt_id}")
                response.raise_for_status()
                history = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, f"ComfyUI is unavailable: {exc}") from exc
        record = history.get(prompt_id) if isinstance(history, dict) else None
        if not isinstance(record, dict):
            return {"ok": True, "state": "pending", "prompt_id": prompt_id, "outputs": []}
        outputs: list[dict[str, Any]] = []
        for node_id, node_output in (record.get("outputs") or {}).items():
            if not isinstance(node_output, dict):
                continue
            for media_type, values in node_output.items():
                if not isinstance(values, list):
                    continue
                for item in values:
                    if not isinstance(item, dict) or not item.get("filename"):
                        continue
                    query = httpx.QueryParams(
                        {
                            "filename": str(item["filename"]),
                            "subfolder": str(item.get("subfolder") or ""),
                            "type": str(item.get("type") or "output"),
                        }
                    )
                    outputs.append(
                        {
                            "node_id": str(node_id),
                            "kind": media_type,
                            **item,
                            "url": f"{base_url}/view?{query}",
                        }
                    )
        status = record.get("status") if isinstance(record.get("status"), dict) else {}
        completed = bool(status.get("completed", outputs))
        return {
            "ok": True,
            "state": "completed" if completed else "running",
            "prompt_id": prompt_id,
            "outputs": outputs,
            "status": status,
        }

    return router


__all__ = ["create_design_studio_router"]
