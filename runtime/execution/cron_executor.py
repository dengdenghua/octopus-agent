"""cron_executor · the missing igniter for persisted cron jobs.

The cron *store* (``runtime/execution/cron_store.py``), the
``schedule_task`` skill, and the ``/api/cron`` router let users and the
agent *register* jobs into ``cron_jobs.json`` — but nothing ever fired
them: ``last_run`` had no writer outside this module. One tick of
``run_due_cron_jobs`` closes that loop:

1. Read the raw job list (preserving the extra ``prompt`` / ``fire_at``
   / ``recurring`` fields the store's fixed projection would strip).
2. Decide per job whether it is due (see ``_is_due`` — one-shot vs
   recurring, with single-run catch-up after downtime).
3. Dispatch: agent jobs (``prompt`` field / ``creator_actor ==
   "agent_self"``) go to the ``prompt_runner``; UI shell jobs go to the
   ``shell_runner``. Both default to subprocess runners so this module
   stays dependency-free and testable.
4. Write back ``last_run`` / ``last_status`` / ``last_output`` in one
   atomic write.

Robustness contract: one job's failure never breaks the tick, and the
tick itself never raises — the scheduler treats callback exceptions as
task errors, and a crashing igniter would take down every other
periodic task sharing the runner.

Concurrency note: last-write-wins against concurrent UI edits. The
window is one tick (~ms), and the UI's own mutations are equally
atomic, so a lost update is benign (a job fires one tick late).
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.adapters.scheduler.cron import CronExpression
from runtime.platform.io import atomic_write_json
from runtime.platform.process.paths import app_paths

_log = logging.getLogger(__name__)

SHELL_JOB_TIMEOUT_S = 300
PROMPT_JOB_TIMEOUT_S = 1800
_OUTPUT_EXCERPT_CHARS = 500

# ``(status, output_excerpt)`` returned by runners.
RunResult = tuple[str, str]
ShellRunner = Callable[[str, dict[str, Any]], RunResult]
PromptRunner = Callable[[str, dict[str, Any]], RunResult]
_CRON_FALLBACK_LOCK = threading.Lock()


# ─── Default runners (subprocess) ────────────────────────────


def _pid_recorder(job: dict[str, Any]) -> Callable[[subprocess.Popen[Any]], None]:
    """Return an ``on_start`` hook that records the child pid on the job.

    Audit T-02: the child runs in its own session (pid == pgid), so the
    recorded pid doubles as the process-group id for startup recovery.
    """

    def _record(proc: subprocess.Popen[Any]) -> None:
        job["pid"] = proc.pid

    return _record


def default_shell_runner(command: str, job: dict[str, Any]) -> RunResult:
    """Run a UI-created shell job.

    Creation of these jobs is auth-gated at the router layer, so the
    command is operator-intended; we inherit the server environment.
    """
    proc, timed_out = _run_process(
        _shell_argv(command),
        timeout=SHELL_JOB_TIMEOUT_S,
        on_start=_pid_recorder(job),
    )
    if timed_out:
        return "timeout", f"exceeded {SHELL_JOB_TIMEOUT_S}s"
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    status = "ok" if proc.returncode == 0 else "error"
    if proc.returncode != 0:
        output = f"exit={proc.returncode} {output}"
    return status, output


def _shell_argv(command: str) -> list[str]:
    """Return an explicit platform shell invocation for an operator command.

    Scheduled UI jobs intentionally use shell syntax, but keeping the shell
    interpreter in argv makes that trust boundary visible and prevents the
    generic process runner from ever accepting ``shell=True``.
    """
    if sys.platform == "win32":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["/bin/sh", "-c", command]


def default_prompt_runner(prompt: str, job: dict[str, Any]) -> RunResult:
    """Run an agent-created prompt job as a headless ``runtime run``.

    Subprocess isolation keeps a scheduled turn's state (and failures)
    out of the serving process, and reuses the existing CLI path so the
    job gets the same planner/tools/config as an interactive run.
    """
    proc, timed_out = _run_process(
        [sys.executable, "-m", "runtime", "run", prompt],
        timeout=PROMPT_JOB_TIMEOUT_S,
        on_start=_pid_recorder(job),
    )
    if timed_out:
        return "timeout", f"exceeded {PROMPT_JOB_TIMEOUT_S}s"
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    status = "ok" if proc.returncode == 0 else "error"
    if proc.returncode != 0:
        output = f"exit={proc.returncode} {output}"
    return status, output


def _run_process(
    argv: list[str],
    *,
    timeout: float,
    on_start: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run a scheduled command in its own session and kill its descendants.

    ``subprocess.run(timeout=...)`` only guarantees that the direct child is
    reaped.  Scheduled commands commonly spawn shells, test runners, or
    agent subprocesses, so a timeout must target the whole process group.

    ``on_start`` (audit T-02) receives the Popen right after launch so the
    caller can persist the child's pid as an in-flight marker before the
    job's own work starts.
    """
    from runtime.platform.process.tree import process_group_kwargs, terminate_process_tree

    proc = subprocess.Popen(  # noqa: S603 — argv is explicit and shell=False
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **process_group_kwargs(),
    )
    if on_start is not None:
        try:
            on_start(proc)
        except Exception:  # noqa: BLE001 — marker recording must not abort the run
            _log.exception("cron_executor: on_start hook failed")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return (
            subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr),
            False,
        )
    except subprocess.TimeoutExpired as exc:
        terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        # Preserve any output captured before the timeout.  communicate may
        # return bytes only for non-text callers, but these runners are text.
        if not stdout:
            stdout = exc.stdout or ""
        if not stderr:
            stderr = exc.stderr or ""
        return (
            subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr),
            True,
        )


@contextmanager
def _cron_execution_lock(path: Path):
    """Acquire a non-blocking lock so multiple service replicas don't fire.

    POSIX flock is released by the kernel on crash, which avoids stale lock
    files.  On platforms without ``fcntl`` this remains a process-local
    fallback; the subprocess cleanup contract still applies there.
    """
    # Keep this separate from atomic_write_json's ``<target>.lock``.  The
    # executor holds its lock while persisting last_run; reusing the writer's
    # sidecar would deadlock when the same process opens that second fd.
    lock_path = path.with_name(path.name + ".execution.lock")
    handle = None
    acquired = False
    fallback_acquired = False
    try:
        try:
            import fcntl

            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        except ImportError:
            # Windows deployments currently run one scheduler per data dir;
            # retain process-local protection when POSIX flock is absent.
            fallback_acquired = _CRON_FALLBACK_LOCK.acquire(blocking=False)
            acquired = fallback_acquired
        yield acquired
    finally:
        if fallback_acquired:
            _CRON_FALLBACK_LOCK.release()
        if handle is not None:
            with contextlib.suppress(Exception):
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            with contextlib.suppress(Exception):
                handle.close()


# ─── Due calculation ─────────────────────────────────────────


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO timestamp, normalizing to an aware local datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # ``astimezone`` on a naive datetime assumes system-local — which is
    # the same clock ``CronExpression.matches`` is evaluated against.
    return dt.astimezone()


def _is_due(job: dict[str, Any], now: datetime) -> bool:
    """Decide whether one job should fire on this tick.

    One-shot jobs (``recurring=False`` + ``fire_at``): fire once when
    ``now >= fire_at``; the ``last_run`` write-back prevents refiring.

    Recurring jobs: a never-run job fires when the expression matches
    the current minute; a previously-run job fires when the next
    scheduled minute after ``last_run`` has passed — which yields
    exactly one catch-up run after downtime, not a burst.

    In-flight jobs (audit T-02): a persisted ``started_at`` marker means
    the job is either running now or was left in flight by a crash. A
    live run must never double-fire; a stale marker is reclaimed by the
    startup sweep (``recover_interrupted_cron_jobs``), which clears it
    and stamps ``last_run`` so the job does not re-fire either.
    """
    if job.get("started_at"):
        return False
    last_run_dt = _parse_dt(job.get("last_run"))

    fire_at_dt = _parse_dt(job.get("fire_at"))
    if fire_at_dt is not None and job.get("recurring") is False:
        return last_run_dt is None and now >= fire_at_dt

    try:
        ce = CronExpression.parse(str(job.get("cron_expression") or ""))
    except Exception:  # noqa: BLE001 — a corrupt job must not break the tick
        _log.warning("cron_executor: unparseable cron for job %r", job.get("name"))
        return False

    if last_run_dt is None:
        return ce.matches(now)
    try:
        return ce.next_after(last_run_dt) <= now
    except Exception:  # noqa: BLE001 — pathological expression; skip rather than crash
        return False


# ─── Tick ────────────────────────────────────────────────────


def _read_raw_jobs(path: Path) -> list[dict[str, Any]]:
    """Read the job file without the store's fixed projection.

    ``cron_store._read_cron_jobs`` strips ``prompt`` / ``fire_at`` /
    ``recurring``; the executor needs them and must write them back.
    """
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("name")]


def run_due_cron_jobs(
    *,
    cron_path: Path | None = None,
    now: datetime | None = None,
    shell_runner: ShellRunner | None = None,
    prompt_runner: PromptRunner | None = None,
    deliver: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run due jobs once, serialized across scheduler processes."""
    path = cron_path or app_paths().cron_jobs_path
    with _cron_execution_lock(path) as acquired:
        if not acquired:
            _log.debug("cron_executor: another scheduler owns %s", path)
            return {"ok": True, "fired": 0, "results": [], "skipped": "lock_held"}
        return _run_due_cron_jobs(
            cron_path=path,
            now=now,
            shell_runner=shell_runner,
            prompt_runner=prompt_runner,
            deliver=deliver,
        )


def _run_due_cron_jobs(
    *,
    cron_path: Path | None = None,
    now: datetime | None = None,
    shell_runner: ShellRunner | None = None,
    prompt_runner: PromptRunner | None = None,
    deliver: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fire every due job once. Returns a per-tick summary; never raises.

    ``deliver`` is an optional per-run hook called with the run record
    (name/kind/fired_at/duration_ms/status/output_excerpt) after the
    ledger write — the serve layer can use it to push completion
    notifications; failures inside the hook are logged and swallowed.
    """
    path = cron_path or app_paths().cron_jobs_path
    tick_now = (now or datetime.now().astimezone()).astimezone()
    shell_fn = shell_runner or default_shell_runner
    prompt_fn = prompt_runner or default_prompt_runner

    jobs = _read_raw_jobs(path)
    if not jobs:
        return {"ok": True, "fired": 0, "results": []}

    results: list[dict[str, Any]] = []
    changed = False
    run_records: list[dict[str, Any]] = []
    for job in jobs:
        name = str(job.get("name") or "")
        try:
            due = _is_due(job, tick_now)
        except Exception:  # noqa: BLE001 — paranoid: never let one job break the tick
            _log.exception("cron_executor: due-check failed for job %r", name)
            continue
        if not due:
            continue

        is_agent_job = bool(job.get("prompt")) or job.get("creator_actor") == "agent_self"
        payload = str(job.get("prompt") or job.get("command") or "").strip()
        if not payload:
            results.append({"name": name, "status": "skipped_empty"})
            continue

        import time as _time

        # Audit T-02: persist the in-flight marker BEFORE dispatching so a
        # crash mid-run leaves a recoverable trace. The tick skips marked
        # jobs; startup recovery reclaims them (kill orphan + no re-fire).
        job["started_at"] = tick_now.isoformat()
        job["pid"] = None
        changed = True
        try:
            atomic_write_json(path, jobs)
        except OSError:
            _log.exception("cron_executor: failed to persist in-flight marker for %r", name)

        started = _time.monotonic()
        try:
            if is_agent_job:
                status, output = prompt_fn(payload, job)
            else:
                status, output = shell_fn(payload, job)
        except Exception as exc:  # noqa: BLE001 — a runner bug must not kill the tick
            status, output = "error", f"{type(exc).__name__}: {exc}"
        duration_ms = int((_time.monotonic() - started) * 1000)

        job.pop("started_at", None)
        job.pop("pid", None)
        job["last_run"] = tick_now.isoformat()
        job["last_status"] = status
        job["last_output"] = (output or "")[-_OUTPUT_EXCERPT_CHARS:]
        results.append({"name": name, "status": status})
        record = {
            "run_id": f"{name}-{tick_now.strftime('%Y%m%dT%H%M%S')}",
            "name": name,
            "kind": "prompt" if is_agent_job else "shell",
            "creator_actor": job.get("creator_actor"),
            "fired_at": tick_now.isoformat(),
            "duration_ms": duration_ms,
            "status": status,
            "output_excerpt": (output or "")[-_OUTPUT_EXCERPT_CHARS:],
            # 订阅推送 · IM delivery target recorded at schedule time.
            "channel_id": str(job.get("channel_id") or ""),
            "thread_id": str(job.get("thread_id") or ""),
        }
        run_records.append(record)
        _log.info("cron_executor: fired job %r → %s", name, status)

    if changed:
        try:
            atomic_write_json(path, jobs)
        except OSError:
            _log.exception("cron_executor: failed to persist results to %s", path)
            return {"ok": False, "fired": len(results), "results": results}

    if run_records:
        _append_run_ledger(_runs_ledger_path(path), run_records)
        if deliver is not None:
            for record in run_records:
                try:
                    deliver(record)
                except Exception:  # noqa: BLE001 — delivery must never break the tick
                    _log.exception("cron_executor: deliver hook failed for %r", record["name"])

    return {"ok": True, "fired": len(results), "results": results}


# ─── Run ledger ──────────────────────────────────────────────

_RUNS_LEDGER_NAME = "cron_runs.jsonl"
_RUNS_LEDGER_MAX_BYTES = 2 * 1024 * 1024


def _runs_ledger_path(cron_path: Path) -> Path:
    return cron_path.parent / _RUNS_LEDGER_NAME


def _append_run_ledger(ledger_path: Path, records: list[dict[str, Any]]) -> None:
    """Append run records to the JSONL history ledger (best-effort).

    The ledger is the queryable "what ran and how did it go" surface —
    ``/api/cron/runs`` reads it back. Capped by simple truncation of the
    oldest lines so a chatty every-minute job can't fill the disk.
    """
    import json

    try:
        lines = [json.dumps(r, ensure_ascii=False) for r in records]
        with ledger_path.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        if ledger_path.stat().st_size > _RUNS_LEDGER_MAX_BYTES:
            existing = ledger_path.read_text(encoding="utf-8").splitlines()
            keep = existing[-(len(existing) // 2) :]
            ledger_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except OSError:
        _log.exception("cron_executor: failed to append run ledger %s", ledger_path)


def _process_group_alive(pid: int) -> bool:
    """True when a POSIX process group led by ``pid`` still exists.

    Cron children launch with ``start_new_session=True``, so the child's
    pid IS its process-group id. ``killpg(pid, 0)`` probes the group
    (survives the leader exiting while descendants remain); Windows falls
    back to a plain pid probe.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user — treat as alive (do not kill).
        return True


def recover_interrupted_cron_jobs(cron_path: Path | None = None) -> dict[str, Any]:
    """Startup sweep (audit T-02): reclaim jobs left in-flight by a crash.

    A job whose subprocess died with the server leaves a persisted
    ``started_at``/``pid`` marker but nothing driving it. Without this
    sweep the marker would skip the job forever (``_is_due`` refuses
    in-flight jobs) while the orphaned process group keeps running.

    Recovery, per marked job:
      * kills the surviving process group by pid (``start_new_session``
        makes pid == pgid),
      * clears the marker and records ``last_status=interrupted``,
      * stamps ``last_run`` so the job does NOT re-fire on the next
        catch-up tick — no double execution.

    Never raises; returns ``{"ok", "interrupted", "jobs"}``.
    """
    path = cron_path or app_paths().cron_jobs_path
    try:
        jobs = _read_raw_jobs(path)
    except Exception:  # noqa: BLE001
        _log.exception("cron recovery: cannot read %s", path)
        return {"ok": False, "interrupted": 0, "jobs": [], "error": "read failed"}

    now = datetime.now().astimezone().isoformat()
    touched: list[str] = []
    for job in jobs:
        if not job.get("started_at"):
            continue
        name = str(job.get("name") or "?")
        pid = job.get("pid")
        if isinstance(pid, int) and pid > 0 and _process_group_alive(pid):
            try:
                from runtime.platform.process.tree import terminate_pid_tree

                terminated = terminate_pid_tree(pid)
            except Exception:  # noqa: BLE001 — recovery must never raise
                _log.exception("cron recovery: kill failed for %r pid=%s", name, pid)
                terminated = False
            _log.warning(
                "cron recovery: reaped orphaned process group pid=%s job=%r (%s)",
                pid,
                name,
                "killed" if terminated else "kill-failed",
            )
        job.pop("started_at", None)
        job.pop("pid", None)
        job["last_run"] = now
        job["last_status"] = "interrupted"
        job["last_output"] = "interrupted by process restart (audit T-02)"
        touched.append(name)

    if touched:
        try:
            atomic_write_json(path, jobs)
        except OSError:
            _log.exception("cron recovery: failed to persist %s", path)
            return {"ok": False, "interrupted": len(touched), "jobs": touched, "error": "persist failed"}
    return {"ok": True, "interrupted": len(touched), "jobs": touched}


def read_run_ledger(ledger_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Read the newest ``limit`` run records (newest first)."""
    import json

    try:
        raw = ledger_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("name"):
            records.append(item)
    return records[-limit:][::-1]


__all__ = [
    "SHELL_JOB_TIMEOUT_S",
    "PROMPT_JOB_TIMEOUT_S",
    "default_shell_runner",
    "default_prompt_runner",
    "read_run_ledger",
    "run_due_cron_jobs",
    "recover_interrupted_cron_jobs",
]
