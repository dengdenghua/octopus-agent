"""Persistence for user-defined cron jobs.

Read/validate and atomically write the cron-jobs JSON file. Both the
cron *skills* (execution) and the ``/api/cron`` compatibility *router*
(sensing/gateway) need this; it lived in the router, which made the
execution-layer cron skills depend upward on the web layer. It depends
only on stdlib + ``platform.io``, so it belongs with the cron domain
logic in execution. The router now imports it from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.platform.io import atomic_write_json


def _read_cron_jobs(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []

    jobs: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        command = str(item.get("command") or "").strip()
        if not name or not command:
            continue
        jobs.append(
            {
                "name": name,
                "command": command,
                "cron_expression": str(item.get("cron_expression") or "0 * * * *"),
                "last_run": item.get("last_run"),
                "last_status": item.get("last_status"),
                # ``creator_actor`` ties a job back to the identity that
                # registered it. ``None`` is legacy (pre-auth) data that
                # only an admin can delete. Anonymous deployments with
                # ``require_auth=False`` all share the ``"*"`` bucket.
                "creator_actor": item.get("creator_actor"),
            }
        )
    return jobs


def _write_cron_jobs(path: Path, jobs: list[dict[str, Any]]) -> None:
    atomic_write_json(path, jobs)
