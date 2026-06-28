#!/usr/bin/env python3
"""Run the browser/desktop runtime evidence probe."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:8000",
        help="Octopus backend base URL",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="optional browser session id",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="per-request timeout in seconds",
    )
    parser.add_argument(
        "--queue-browser-replay",
        action="store_true",
        help="queue a browser replay case when the browser probe is replay-ready",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="leave the probe browser session open for debugging",
    )
    parser.add_argument(
        "--cleanup-session",
        action="store_true",
        default=True,
        help="reset the probe browser session after the run; enabled by default",
    )
    parser.add_argument(
        "--no-persist-evidence",
        action="store_true",
        help="do not write the successful runtime evidence snapshot",
    )
    parser.add_argument(
        "--bearer-token-env",
        default="",
        help="environment variable containing an optional backend bearer token",
    )
    parser.add_argument(
        "--auto-local-auth",
        action="store_true",
        help="try passwordless local auth when no bearer token env is provided",
    )
    parser.add_argument(
        "--real-chrome-relay",
        action="store_true",
        help=(
            "ask an already-connected Chrome extension/bookmarklet to execute "
            "a safe aria command; disabled by default"
        ),
    )
    parser.add_argument(
        "--open-real-chrome-relay",
        action="store_true",
        help=(
            "open a local Chrome/Chromium connect page before "
            "--real-chrome-relay and wait for it to attach"
        ),
    )
    parser.add_argument(
        "--local-auth-username",
        default="runtime-probe",
        help="username for --auto-local-auth",
    )
    parser.add_argument(
        "--local-auth-password-env",
        default="",
        help="environment variable containing the optional local-auth password",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format",
    )
    return parser


def _format_text(payload: dict[str, Any]) -> str:
    readiness = payload.get("runtime_readiness")
    readiness = readiness if isinstance(readiness, dict) else {}
    lines = [
        (
            "browser_desktop_runtime_probe: "
            f"ok={payload.get('ok')} ready={payload.get('ready')} "
            f"score={payload.get('score')}"
        ),
        (
            "auth: "
            f"blocked={_dict(payload.get('auth')).get('auth_blocked')} "
            f"token={_dict(payload.get('auth')).get('bearer_token_provided')} "
            f"auto_local={_dict(payload.get('auth')).get('auto_local_auth_enabled')}"
        ),
        (
            "runtime_readiness: "
            f"{readiness.get('verdict')} score={readiness.get('score')} "
            f"blockers={readiness.get('blocker_count')} warnings={readiness.get('warn_count')}"
        ),
        (
            "cleanup: "
            f"enabled={_dict(payload.get('cleanup')).get('enabled')} "
            f"attempted={_dict(payload.get('cleanup')).get('attempted')} "
            f"ok={_dict(payload.get('cleanup')).get('ok')}"
        ),
    ]
    for op in payload.get("operations") or []:
        if not isinstance(op, dict):
            continue
        state = "pass" if op.get("ok") else "fail"
        suffix = f" - {op.get('error')}" if op.get("error") else ""
        lines.append(f"- {op.get('method')} {op.get('path')}: {state}{suffix}")
    for action in payload.get("next_actions") or []:
        lines.append(f"next: {action}")
    return "\n".join(lines)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def main(argv: list[str] | None = None) -> int:
    from runtime.safety.evolution.browser_desktop_runtime_probe import (
        run_browser_desktop_runtime_probe,
    )

    args = _build_parser().parse_args(argv)
    payload = run_browser_desktop_runtime_probe(
        api_base_url=args.api_base_url,
        session_id=args.session_id or None,
        timeout_s=args.timeout,
        queue_browser_replay=args.queue_browser_replay,
        cleanup_session=bool(args.cleanup_session and not args.keep_session),
        persist_evidence=not args.no_persist_evidence,
        bearer_token=os.environ.get(args.bearer_token_env, "")
        if args.bearer_token_env
        else "",
        auto_local_auth=args.auto_local_auth,
        local_auth_username=args.local_auth_username,
        local_auth_password=os.environ.get(args.local_auth_password_env, "")
        if args.local_auth_password_env
        else "",
        real_chrome_relay=args.real_chrome_relay,
        open_real_chrome_relay=args.open_real_chrome_relay,
    )
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_text(payload))
    return 0 if payload.get("ready") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
