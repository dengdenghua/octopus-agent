from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from runtime.execution.loops.models import LoopRun
from runtime.platform.io import atomic_write_json, read_json_with_backup
from runtime.platform.io.atomic import _cross_process_lock

_SCHEMA = "octopus.loop_runs.v1"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _empty_payload() -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "version": 1,
        "lastUpdated": "",
        "runs": [],
    }


def _normalize_payload(raw: Any) -> dict[str, Any]:
    payload = _empty_payload()
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for item in raw.get("runs") or []:
            if not isinstance(item, dict):
                continue
            try:
                loop_run = LoopRun.model_validate(item)
            except Exception:
                continue
            rows.append(loop_run.model_dump(mode="json"))
        payload["lastUpdated"] = str(raw.get("lastUpdated") or "")
    payload["runs"] = rows
    return payload


class LoopRunStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def create(self, run: LoopRun) -> LoopRun:
        with self._write_lock():
            payload = self._read_payload()
            runs = self._read_runs_from_payload(payload)
            if any(existing.run_id == run.run_id for existing in runs):
                raise KeyError(run.run_id)
            runs.append(run)
            payload["runs"] = self._dump_runs(runs)
            payload["lastUpdated"] = run.updated_at
            self._write_payload(payload)
            return run

    def get(self, run_id: str) -> LoopRun | None:
        with self._lock:
            for run in self._read_runs():
                if run.run_id == run_id:
                    return run
        return None

    def list(
        self,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LoopRun]:
        with self._lock:
            runs = self._read_runs()
        if owner_id is not None:
            runs = [run for run in runs if run.owner_id in (None, "", owner_id)]
        if status:
            runs = [run for run in runs if run.status.value == str(status).strip()]
        if mode:
            runs = [run for run in runs if run.mode.value == str(mode).strip()]
        runs.sort(key=lambda run: (run.created_at, run.run_id), reverse=True)
        return runs[offset : offset + limit]

    def count(
        self,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        mode: str | None = None,
    ) -> int:
        return len(self.list(owner_id=owner_id, status=status, mode=mode, limit=1_000_000))

    def save(self, run: LoopRun) -> LoopRun:
        return self.mutate(run.run_id, lambda _: run)

    def mutate(
        self,
        run_id: str,
        mutator: Callable[[LoopRun], LoopRun],
    ) -> LoopRun:
        with self._write_lock():
            payload = self._read_payload()
            runs = self._read_runs_from_payload(payload)
            updated: LoopRun | None = None
            next_runs: list[LoopRun] = []
            for run in runs:
                if run.run_id != run_id:
                    next_runs.append(run)
                    continue
                candidate = mutator(run)
                updated = candidate.model_copy(update={"updated_at": _now_iso()})
                next_runs.append(updated)
            if updated is None:
                raise KeyError(run_id)
            payload["runs"] = self._dump_runs(next_runs)
            payload["lastUpdated"] = updated.updated_at
            self._write_payload(payload)
            return updated

    def _read_payload(self) -> dict[str, Any]:
        raw = read_json_with_backup(self.path, default=None)
        return _normalize_payload(raw)

    def _write_payload(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.path, _normalize_payload(payload))

    def _write_lock(self) -> Any:
        return _StoreWriteLock(self._lock, self.path.parent / f"{self.path.name}.rw")

    def _read_runs(self) -> list[LoopRun]:
        return self._read_runs_from_payload(self._read_payload())

    @staticmethod
    def _read_runs_from_payload(payload: dict[str, Any]) -> list[LoopRun]:
        runs: list[LoopRun] = []
        for item in payload.get("runs") or []:
            if not isinstance(item, dict):
                continue
            try:
                runs.append(LoopRun.model_validate(item))
            except Exception:
                continue
        return runs

    @staticmethod
    def _dump_runs(runs: list[LoopRun]) -> list[dict[str, Any]]:
        return [cast(dict[str, Any], run.model_dump(mode="json")) for run in runs]


class _StoreWriteLock:
    def __init__(self, thread_lock: threading.RLock, target: Path) -> None:
        self._thread_lock = thread_lock
        self._target = target
        self._process_lock: Any = None

    def __enter__(self) -> None:
        self._thread_lock.__enter__()
        self._process_lock = _cross_process_lock(self._target)
        self._process_lock.__enter__()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self._process_lock is not None:
                self._process_lock.__exit__(exc_type, exc, tb)
        finally:
            self._thread_lock.__exit__(exc_type, exc, tb)
