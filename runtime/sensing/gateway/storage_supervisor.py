"""Optional co-launch of the octopus-storage sibling service.

octopus-storage stays an independent, separately-deployable package — it serves
File Agent for the whole family (agent / os / enterprise) and carries heavy
OCR / vision / embedding deps, so it must NOT be merged into octopus-agent. But
for a single-machine user, starting two services by hand is friction. This
supervisor lets ``octopus serve`` ALSO bring storage up as a child process,
opt-in via ``OCTOPUS_STORAGE_AUTOSTART`` — one command for them, while everyone
else still runs storage standalone and points ``OCTOPUS_STORAGE_URL`` at it.

Best-effort + graceful: disabled / already running / binary not found / fails to
start → log + skip; the agent runs fine and ``search_documents`` degrades to
"storage unavailable". The child is terminated when the agent process exits.
Resolution never uses a shell, so nothing here is an injection surface.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

_LOG = logging.getLogger("octopus.storage_supervisor")
_proc: subprocess.Popen | None = None
_lock = threading.Lock()


def _autostart_enabled() -> bool:
    return os.environ.get("OCTOPUS_STORAGE_AUTOSTART", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _storage_port() -> str:
    from runtime.execution.suckers.storage_skills import _base_url

    with contextlib.suppress(Exception):
        port = urlparse(_base_url()).port
        if port:
            return str(port)
    return "8767"


def resolve_storage_command() -> list[str] | None:
    """Resolve the argv that launches ``octopus-storage serve``, or ``None`` if
    it can't be found. Priority: ``OCTOPUS_STORAGE_CMD`` (explicit) → the sibling
    repo's ``.venv`` console script → a console script on PATH. Always argv lists
    (no shell)."""
    port = _storage_port()

    explicit = (os.environ.get("OCTOPUS_STORAGE_CMD") or "").strip()
    if explicit:
        argv = shlex.split(explicit)
        return argv if "serve" in argv else [*argv, "serve", "--port", port]

    # Sibling layout: <…>/octopus/octopus-agent/runtime/… → <…>/octopus/octopus-storage
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "runtime").is_dir():
            sibling = parent.parent / "octopus-storage" / ".venv" / "bin" / "octopus-storage"
            if sibling.exists():
                return [str(sibling), "serve", "--port", port]
            break

    found = shutil.which("octopus-storage")
    if found:
        return [found, "serve", "--port", port]
    return None


def _already_up() -> bool:
    from runtime.execution.suckers.storage_skills import storage_manifest

    return storage_manifest(timeout=1.5) is not None


def maybe_start_storage() -> str:
    """Co-launch storage when opt-in + not already up + resolvable. Returns a
    status: ``disabled`` / ``already_running`` / ``not_found`` / ``started`` /
    ``error``. Non-blocking — readiness is logged from a background thread, so
    server boot is never delayed. Never raises."""
    global _proc
    if not _autostart_enabled():
        return "disabled"
    try:
        if _already_up():
            _LOG.info("octopus-storage already running; not co-launching")
            return "already_running"
        cmd = resolve_storage_command()
        if cmd is None:
            _LOG.info(
                "octopus-storage not found; skipping autostart "
                "(install it, or set OCTOPUS_STORAGE_CMD)"
            )
            return "not_found"
        with _lock:
            if _proc is not None and _proc.poll() is None:
                return "started"
            _proc = subprocess.Popen(  # noqa: S603 — argv list, shell=False, resolved command
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            atexit.register(stop_storage)
        _LOG.info("octopus-storage co-launching: %s", " ".join(cmd))
        threading.Thread(target=_wait_ready, name="storage-ready", daemon=True).start()
        return "started"
    except Exception as exc:  # noqa: BLE001 — autostart is strictly best-effort
        _LOG.warning("octopus-storage autostart failed: %s", exc)
        return "error"


def _wait_ready(*, attempts: int = 20, interval: float = 0.5) -> None:
    for _ in range(attempts):
        proc = _proc
        if proc is None or proc.poll() is not None:
            _LOG.warning("octopus-storage exited during startup; running without it")
            return
        if _already_up():
            _LOG.info("octopus-storage co-launched and ready (pid %s)", proc.pid)
            return
        time.sleep(interval)
    _LOG.info("octopus-storage not ready yet; search_documents will pick it up once it is")


def stop_storage() -> None:
    """Terminate the co-launched child (if we started one). Idempotent."""
    global _proc
    with _lock:
        proc, _proc = _proc, None
    if proc is None or proc.poll() is not None:
        return
    with contextlib.suppress(Exception):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
