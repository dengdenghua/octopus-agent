"""Subprocess streaming helper.

Spawn a child process, stream stdout/stderr line-by-line as they arrive,
forward each line to the active ``tool_output_sink`` so the react-loop
can push ``commandExecution/outputDelta`` events to the client. The
return shape mirrors the old ``subprocess.run(capture_output=True)``
dict so callers can drop this in without restructuring.

Used by:
    * Mantles (docker / k8s / ssh CLI) — ``runtime.sensing.server.*``
    * Long-running skills (exec_shell, git, quality checks, verify) —
      ``runtime.execution.suckers.*``

Skills don't depend on the sensing/mantle layer, so this lives at the
platform tier where both can import it without crossing layers.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any


def stream_run(
    argv: list[str],
    *,
    input_data: str | None = None,
    timeout: float,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    output_cap_bytes: int = 200_000,
    on_timeout: Callable[[subprocess.Popen[str]], None] | None = None,
) -> dict[str, Any]:
    """Run ``argv`` as a subprocess, streaming output as it arrives.

    Returns a dict with ``stdout``, ``stderr``, ``exit_code``,
    ``timed_out``, ``stdout_truncated``, ``stderr_truncated``. Callers
    are expected to merge in backend-specific keys (``container``,
    ``pod``, ``host``, etc.) on the returned dict.

    ``on_timeout`` is called after the process is killed, letting the
    caller run any backend-specific cleanup (e.g. ``docker kill``).
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            bufsize=1,
            shell=False,
        )
    except FileNotFoundError as e:
        return {"error": f"exec_failed: {e}"}
    except OSError as e:
        return {"error": f"exec_failed: {e}"}

    from runtime.core.cerebrum import tool_output_sink
    from runtime.safety.approval.cancellation import current_cancellation_token

    # Capture the sink on the calling thread — reader threads below do
    # not inherit ContextVars.
    sink = tool_output_sink.current_sink()
    cancel_token = current_cancellation_token()

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def _reader(stream: Any, parts: list[str], kind: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                parts.append(line)
                if sink is not None:
                    with contextlib.suppress(Exception):
                        sink(kind, line)  # type: ignore[arg-type]
        finally:
            with contextlib.suppress(Exception):
                stream.close()

    t_out = threading.Thread(
        target=_reader, args=(proc.stdout, stdout_parts, "stdout"), daemon=True,
    )
    t_err = threading.Thread(
        target=_reader, args=(proc.stderr, stderr_parts, "stderr"), daemon=True,
    )
    t_out.start()
    t_err.start()

    if input_data is not None and proc.stdin is not None:
        with contextlib.suppress((BrokenPipeError, OSError)):
            proc.stdin.write(input_data)
        with contextlib.suppress(Exception):
            proc.stdin.close()

    timed_out = False
    cancelled = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel_token.is_cancelled:
                cancelled = True
                proc.kill()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                if on_timeout is not None:
                    with contextlib.suppress(Exception):
                        on_timeout(proc)
                break
            try:
                # Short wait slice so we can poll the cancel token
                # roughly every 100ms. Choosing too small wastes CPU;
                # too large delays responding to a stop click.
                proc.wait(timeout=min(remaining, 0.1))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)

    raw_stdout = "".join(stdout_parts)
    raw_stderr = "".join(stderr_parts)
    return {
        "stdout": raw_stdout[:output_cap_bytes],
        "stderr": raw_stderr[:output_cap_bytes],
        "exit_code": None if (timed_out or cancelled) else proc.returncode,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "stdout_truncated": len(raw_stdout) > output_cap_bytes,
        "stderr_truncated": len(raw_stderr) > output_cap_bytes,
    }
