"""Opt-in, read-only shadow reviews on bounded workspace snapshots."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_SNAPSHOT_FILES = 5_000
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
IGNORED_NAMES = frozenset(
    {
        ".git",
        ".env",
        ".venv",
        "__pycache__",
        "data",
        "dist",
        "build",
        "node_modules",
        ".next",
        ".cache",
        ".pytest_cache",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ShadowRun:
    run_id: str
    goal: str
    primary_engine: str
    shadow_engine: str
    status: str
    created_at: str
    updated_at: str
    source_thread_id: str | None = None
    source_message_id: str | None = None
    workspace_snapshot: str | None = None
    result: str | None = None
    error: str | None = None


ShadowRunner = Callable[[str, Path, str], Awaitable[str]]


class DualHelixShadowService:
    def __init__(
        self,
        state_path: Path | str,
        snapshot_root: Path | str,
        *,
        allowed_workspace_root: Path | str,
        codex_runner: ShadowRunner | None = None,
        native_runner: ShadowRunner | None = None,
    ) -> None:
        self._state_path = Path(state_path).resolve(strict=False)
        self._snapshot_root = Path(snapshot_root).resolve(strict=False)
        self._allowed_root = Path(allowed_workspace_root).resolve(strict=True)
        self._codex_runner = codex_runner
        self._native_runner = native_runner
        self._lock = threading.RLock()
        self._tasks: set[asyncio.Task[None]] = set()

    def status(self) -> dict[str, Any]:
        state = self._read()
        runs = list(state.get("runs") or [])[-20:]
        runs.reverse()
        return {
            "ok": True,
            "schema": "octopus.dual_helix_shadow.v1",
            "enabled": bool(state.get("enabled", False)),
            "isolation": "bounded_snapshot_read_only",
            "runs": runs,
        }

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        state = self._read()
        state["enabled"] = bool(enabled)
        self._write(state)
        return self.status()

    def queue(
        self,
        *,
        goal: str,
        primary_engine: str,
        primary_output: str,
        workspace_path: str | None = None,
        source_thread_id: str | None = None,
        source_message_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._read()
        if not state.get("enabled"):
            raise PermissionError("dual-helix shadow mode is disabled")
        if primary_engine not in {"octopus", "codex"}:
            raise ValueError("primary engine must be octopus or codex")
        workspace = self._resolve_workspace(workspace_path)
        run = ShadowRun(
            run_id=f"shadow_{uuid4().hex[:16]}",
            goal=goal.strip(),
            primary_engine=primary_engine,
            shadow_engine="codex" if primary_engine == "octopus" else "octopus",
            status="queued",
            created_at=_now(),
            updated_at=_now(),
            source_thread_id=(source_thread_id or "").strip() or None,
            source_message_id=(source_message_id or "").strip() or None,
        )
        state.setdefault("runs", []).append(asdict(run))
        state["runs"] = state["runs"][-100:]
        self._write(state)
        task = asyncio.create_task(
            self._execute(run, workspace, primary_output),
            name=f"dual-helix-{run.run_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return asdict(run)

    async def _execute(self, run: ShadowRun, workspace: Path, primary_output: str) -> None:
        try:
            self._update(run.run_id, status="snapshotting")
            snapshot = await asyncio.to_thread(
                materialize_shadow_snapshot,
                workspace,
                self._snapshot_root / run.run_id / "workspace",
            )
            self._update(
                run.run_id,
                status="running",
                workspace_snapshot=str(snapshot),
            )
            runner = self._codex_runner if run.shadow_engine == "codex" else self._native_runner
            if runner is None:
                raise RuntimeError(f"{run.shadow_engine} shadow runner is unavailable")
            result = await runner(run.goal, snapshot, primary_output)
            self._update(run.run_id, status="completed", result=result[:50_000])
        except Exception as exc:  # noqa: BLE001 - persisted bounded failure
            self._update(run.run_id, status="failed", error=str(exc)[:500])

    def _resolve_workspace(self, raw: str | None) -> Path:
        candidate = Path(raw).expanduser() if raw else self._allowed_root
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(self._allowed_root)
        except ValueError as exc:
            raise ValueError("shadow workspace is outside the allowed project root") from exc
        if not resolved.is_dir():
            raise ValueError("shadow workspace must be a directory")
        return resolved

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                value = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"enabled": False, "runs": []}
            return value if isinstance(value, dict) else {"enabled": False, "runs": []}

    def _write(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._state_path.parent,
                prefix=f".{self._state_path.name}.",
                delete=False,
            ) as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                temp = Path(handle.name)
            os.chmod(temp, 0o600)
            os.replace(temp, self._state_path)

    def _update(self, run_id: str, **changes: Any) -> None:
        state = self._read()
        for row in state.get("runs") or []:
            if row.get("run_id") == run_id:
                row.update(changes)
                row["updated_at"] = _now()
                break
        self._write(state)


def materialize_shadow_snapshot(source: Path, destination: Path) -> Path:
    source = source.resolve(strict=True)
    destination = destination.resolve(strict=False)
    if destination.exists():
        raise FileExistsError("shadow snapshot already exists")
    destination.mkdir(parents=True, exist_ok=False)
    files = total_bytes = 0
    try:
        for root, dirnames, filenames in os.walk(source, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in IGNORED_NAMES and not (Path(root) / name).is_symlink()
            ]
            relative = Path(root).relative_to(source)
            target_dir = destination / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in filenames:
                src = Path(root) / name
                if name in IGNORED_NAMES or src.is_symlink():
                    continue
                size = src.stat().st_size
                files += 1
                total_bytes += size
                if files > MAX_SNAPSHOT_FILES or total_bytes > MAX_SNAPSHOT_BYTES:
                    raise ValueError("workspace exceeds the bounded shadow snapshot budget")
                shutil.copy2(src, target_dir / name)
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def build_codex_shadow_runner(stack: Any, agent_registry: Any) -> ShadowRunner:
    async def _run(goal: str, workspace: Path, primary_output: str) -> str:
        from runtime.execution.codex_backend.role_runner import run_agent_role

        if agent_registry is None or not agent_registry.has("coder"):
            raise RuntimeError("Coder role is unavailable")
        agent = agent_registry.get("coder")
        prompt = _review_prompt(goal, primary_output)
        result = await run_agent_role(
            stack,
            agent,
            prompt,
            context={
                "workspace_path": str(workspace),
                "workspace_contract": "audit_read_only",
                "tool_allowlist_read_only": True,
                "sandbox_policy": {"type": "readOnly", "networkAccess": False},
                "timeout_s": 600,
            },
        )
        if not result.success and not result.output:
            raise RuntimeError(f"Codex shadow review failed: {result.status}")
        return result.output

    return _run


def build_native_shadow_runner(stack: Any) -> ShadowRunner:
    async def _run(goal: str, workspace: Path, primary_output: str) -> str:
        from runtime.platform.models.llm import Message, ModelRequest

        router = getattr(getattr(stack, "planner", None), "router", None)
        if router is None or not callable(getattr(router, "call", None)):
            raise RuntimeError("Octopus model router is unavailable")
        model = str(
            getattr(router, "default_model", None)
            or getattr(getattr(getattr(stack, "config", None), "planner", None), "model", None)
            or ""
        ).strip()
        if not model:
            raise RuntimeError("Octopus shadow model is unavailable")
        manifest = await asyncio.to_thread(_snapshot_manifest, workspace)
        prompt = _review_prompt(goal, primary_output, manifest=manifest)

        def _call() -> str:
            response = router.call(
                ModelRequest(
                    model=model,
                    messages=[Message(role="user", content=prompt)],
                    max_tokens=1_200,
                    temperature=0.0,
                )
            )
            return str(response.text or "").strip()

        result = await asyncio.to_thread(_call)
        if not result:
            raise RuntimeError("Octopus shadow review returned no result")
        return result

    return _run


def _snapshot_manifest(workspace: Path, *, limit: int = 300) -> str:
    rows: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            rows.append(str(path.relative_to(workspace)))
            if len(rows) >= limit:
                break
    return "\n".join(rows)


def _review_prompt(goal: str, primary_output: str, *, manifest: str = "") -> str:
    return (
        "You are the read-only shadow reviewer in a dual-engine evolution experiment. "
        "Do not edit files, run network actions, or request approvals. Evaluate correctness, "
        "missing verification, safety, and whether the result satisfies the task. Return a "
        "concise verdict with PASS or FAIL, evidence, and recommended improvements.\n\n"
        f"TASK:\n{goal}\n\nPRIMARY ENGINE OUTPUT:\n{primary_output or '(not supplied)'}"
        + (f"\n\nISOLATED SNAPSHOT FILE MANIFEST:\n{manifest}" if manifest else "")
    )


__all__ = [
    "DualHelixShadowService",
    "ShadowRun",
    "build_codex_shadow_runner",
    "build_native_shadow_runner",
    "materialize_shadow_snapshot",
]
