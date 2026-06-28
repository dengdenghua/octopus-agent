from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime.safety.evolution.agent_competitor_scorecard import (
    compute_agent_competitor_scorecard,
)
from runtime.safety.evolution.browser_desktop_runtime_probe import (
    PROBE_PAGE_URL,
    run_browser_desktop_runtime_probe,
)
from runtime.safety.evolution.browser_desktop_runtime_evidence import (
    load_browser_desktop_runtime_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
        *,
        text: str = "",
        content_type: str = "application/json",
        json_error: Exception | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload)
        self.headers = {"content-type": content_type} if content_type else {}
        self._json_error = json_error

    def json(self) -> dict[str, Any]:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _RuntimeProbeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._relay_commands: list[dict[str, Any]] = []
        self._relay_results: dict[str, dict[str, Any]] = {}
        self._relay_connected = False
        self.real_relay_connected = False
        self.real_relay_url = "https://example.test"

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        self.calls.append({
            "method": "POST",
            "url": url,
            "json": json,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        if url.endswith("/api/browser/session/ensure"):
            return _Response({"status": "ready", "session": {"session_id": json["session_id"]}})
        if url.endswith("/api/browser/navigate"):
            return _Response({
                "url": json["url"],
                "title": "Octopus probe",
            })
        if url.endswith("/api/browser/action"):
            return _Response({
                "ok": True,
                "url": PROBE_PAGE_URL,
                "title": "Octopus probe",
                "nodes": {"role": "document"},
            })
        if url.endswith("/api/browser/session/replay-case/queue"):
            return _Response({
                "schema": "octopus.browser_session_replay_case_queue.v1",
                "queue": {"created": 1, "items": []},
            })
        if url.endswith("/api/browser/relay/heartbeat"):
            self._relay_connected = True
            commands = list(self._relay_commands)
            self._relay_commands = []
            return _Response({
                "ok": True,
                "pending_commands": len(commands),
                "commands": commands,
            })
        if url.endswith("/api/browser/relay/command"):
            command = {
                "id": "cmd-1",
                "action": json["action"],
                "params": {
                    key: value
                    for key, value in (json or {}).items()
                    if key not in {"id", "action"}
                },
            }
            if self.real_relay_connected and command["action"] == "aria":
                return _Response({
                    "ok": True,
                    "id": command["id"],
                    "title": "Real relay page",
                    "url": self.real_relay_url,
                    "nodes": {"role": "document"},
                })
            self._relay_commands.append(command)
            for _ in range(80):
                result = self._relay_results.pop(command["id"], None)
                if result is not None:
                    return _Response(result)
                time.sleep(0.01)
            return _Response({"detail": "browser relay command timed out"}, status_code=504)
        if url.endswith("/api/browser/relay/result"):
            result = dict((json or {}).get("result") or {})
            result.setdefault("ok", True)
            result.setdefault("id", (json or {}).get("id"))
            self._relay_results[str((json or {}).get("id"))] = result
            return _Response({"ok": True})
        if url.endswith("/api/browser/open-real-chrome-relay"):
            self.real_relay_connected = True
            return _Response({
                "ok": True,
                "opened": True,
                "url": "http://probe.local/api/browser/relay/connect-page",
                "mode": "local_bookmarklet_connect_page",
            })
        if url.endswith("/api/computer/actions/preview"):
            return _Response({
                "ok": True,
                "token": "preview-token",
                "action": {"action": "wait", "ms": 10},
                "risk": {"level": "low", "reason": "does not submit data by itself"},
                "expires_in_seconds": 90,
                "lease": {"held": False, "ttl_seconds": 0},
            })
        if url.endswith("/api/computer/actions/execute"):
            return _Response({
                "ok": True,
                "action": {"action": "wait", "ms": 10},
                "risk": {"level": "low", "reason": "does not submit data by itself"},
                "result": {"waited_ms": 10},
                "lease": {
                    "held": True,
                    "owner_id": "probe-session",
                    "owner_label": "Runtime probe",
                    "ttl_seconds": 60,
                },
                "executed_at": 1,
            })
        if url.endswith("/api/computer/lease/release"):
            return _Response({
                "ok": True,
                "lease": {"held": False, "ttl_seconds": 0},
            })
        if url.endswith("/api/browser/session/reset"):
            return _Response({
                "ok": True,
                "status": "closed",
                "session": {"session_id": json["session_id"], "exists": False},
            })
        return _Response({"error": f"unexpected POST {url}"}, status_code=404)

    def get(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        self.calls.append({
            "method": "GET",
            "url": url,
            "json": json,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        if url.endswith("/api/browser/session/health"):
            return _Response({
                "schema": "octopus.browser_session_health.v1",
                "exists": True,
                "healthy": True,
                "score": 1.0,
                "issues": [],
                "replay_ready": True,
            })
        if url.endswith("/api/computer/status"):
            return _Response({
                "ok": True,
                "pyautogui_available": True,
                "uia_available": True,
                "lease": {"held": False, "ttl_seconds": 0},
                "recent_activity": [
                    {"event": "probe_status_observed", "ok": True},
                ],
            })
        if url.endswith("/api/computer/activity/replay-case"):
            return _Response({
                "schema": "octopus.computer_activity_replay_case.v1",
                "replay_ready": True,
                "case_id": "computer-activity:abc123",
                "fingerprint": "0123456789abcdef",
                "activity_count": 2,
                "pending_count": 0,
                "items": [
                    {"event": "preview_queued", "ok": True},
                    {
                        "event": "action_executed",
                        "ok": True,
                        "action": {"action": "wait", "ms": 10},
                    },
                ],
                "last_activity": {
                    "event": "action_executed",
                    "ok": True,
                    "action": {"action": "wait", "ms": 10},
                },
            })
        if url.endswith("/api/browser/relay/status"):
            connected = self.real_relay_connected or self._relay_connected
            return _Response({
                "connected": connected,
                "extension_version": "0.2.0" if self.real_relay_connected else "runtime-probe",
                "pending_commands": len(self._relay_commands),
                "last_seen": 1,
                "active_tab": {
                    "id": 1 if self.real_relay_connected else "runtime-probe",
                    "url": self.real_relay_url if self.real_relay_connected else PROBE_PAGE_URL,
                    "title": "Real relay page" if self.real_relay_connected else "Octopus runtime probe",
                },
                "manifest_exists": True,
            })
        return _Response({"error": f"unexpected GET {url}"}, status_code=404)


class _AuthBlockedProbeClient(_RuntimeProbeClient):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        self.calls.append({
            "method": "POST",
            "url": url,
            "json": json,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        return _Response(
            {"detail": "missing Authorization: Bearer <token>"},
            status_code=401,
        )

    def get(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        self.calls.append({
            "method": "GET",
            "url": url,
            "json": json,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        return _Response(
            {"detail": "missing Authorization: Bearer <token>"},
            status_code=401,
        )


class _LocalAuthProbeClient(_RuntimeProbeClient):
    def get(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        if url.endswith("/api/auth/providers"):
            self.calls.append({
                "method": "GET",
                "url": url,
                "json": json,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            })
            return _Response({
                "providers": [
                    {
                        "id": "local",
                        "endpoint": "/api/auth/local/login",
                    }
                ]
            })
        return super().get(
            url,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        if url.endswith("/api/auth/local/login"):
            self.calls.append({
                "method": "POST",
                "url": url,
                "json": json,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            })
            return _Response({
                "success": True,
                "access_token": "jwt.redacted.value",
                "token_type": "Bearer",
            })
        return super().post(
            url,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
        )


class _CleanupFailureProbeClient(_RuntimeProbeClient):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        if url.endswith("/api/browser/session/reset"):
            self.calls.append({
                "method": "POST",
                "url": url,
                "json": json,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            })
            return _Response({"error": "reset failed"}, status_code=500)
        return super().post(
            url,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
        )


class _NonJsonActionProbeClient(_RuntimeProbeClient):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        if url.endswith("/api/browser/action"):
            self.calls.append({
                "method": "POST",
                "url": url,
                "json": json,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            })
            return _Response(
                {},
                status_code=502,
                text="<html>upstream gateway error</html>",
                content_type="text/html",
                json_error=ValueError("not json"),
            )
        return super().post(
            url,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
        )


def test_runtime_probe_collects_snapshots_and_marks_quality_ready(
    tmp_path: Path,
) -> None:
    client = _RuntimeProbeClient()

    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["schema"] == "octopus.browser_desktop_runtime_probe.v1"
    assert report["ok"] is True
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["runtime_readiness"]["ready"] is True
    assert report["quality"]["ready"] is True
    assert report["operation_status"]["ok"] is True
    assert report["chrome_relay_handshake"]["ok"] is True
    assert report["computer_execute"]["ok"] is True
    assert report["computer_replay_case"]["replay_ready"] is True
    assert report["real_chrome_relay_probe"]["enabled"] is False
    assert report["cleanup"]["attempted"] is True
    assert report["cleanup"]["ok"] is True
    assert report["cleanup"]["desktop_lease_release"]["ok"] is True
    assert any(
        call["url"].endswith("/api/browser/relay/command")
        for call in client.calls
    )
    assert any(
        call["url"].endswith("/api/browser/relay/result")
        for call in client.calls
    )
    assert any(
        call["url"].endswith("/api/browser/session/reset")
        for call in client.calls
    )
    assert client.calls[-1]["url"].endswith("/api/computer/lease/release")


def test_runtime_probe_can_use_real_chrome_relay_when_connected(
    tmp_path: Path,
) -> None:
    client = _RuntimeProbeClient()
    client.real_relay_connected = True

    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        real_chrome_relay=True,
        review_queue_path=tmp_path / "review_queue.json",
    )

    real = report["real_chrome_relay_probe"]
    assert report["ready"] is True
    assert real["schema"] == "octopus.real_chrome_relay_probe.v1"
    assert real["ok"] is True
    assert real["evidence_level"] == "real_chrome_profile_verified"
    assert real["active_tab"]["title"] == "Real relay page"
    canary = report["quality"]["capability_canary"]
    assert canary["real_chrome_profile_verified_count"] == 1


def test_runtime_probe_real_chrome_ignores_runtime_self_test_relay(
    tmp_path: Path,
) -> None:
    client = _RuntimeProbeClient()

    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        real_chrome_relay=True,
        review_queue_path=tmp_path / "review_queue.json",
    )

    real = report["real_chrome_relay_probe"]
    assert report["ready"] is True
    assert report["operation_status"]["ok"] is True
    assert real["ok"] is False
    assert real["connected"] is True
    assert real["extension_version"] == "runtime-probe"
    assert "runtime self-test heartbeat" in real["error"]
    canary = report["quality"]["capability_canary"]
    assert canary["ready"] is True
    assert canary["real_chrome_profile_verified_count"] == 0
    assert "real_chrome_profile_flow" in canary["warnings"]


def test_runtime_probe_can_open_and_verify_real_chrome_relay(
    tmp_path: Path,
) -> None:
    client = _RuntimeProbeClient()

    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        real_chrome_relay=True,
        open_real_chrome_relay=True,
        review_queue_path=tmp_path / "review_queue.json",
    )

    real = report["real_chrome_relay_probe"]
    assert report["ready"] is True
    assert report["open_real_chrome_relay"] is True
    assert real["ok"] is True
    assert real["evidence_level"] == "real_chrome_profile_verified"
    assert any(
        call["url"].endswith("/api/browser/open-real-chrome-relay")
        for call in client.calls
    )
    canary = report["quality"]["capability_canary"]
    assert canary["real_chrome_profile_verified_count"] == 1


def test_runtime_probe_redacts_real_chrome_relay_token_from_report_and_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "runtime_evidence.json"
    client = _RuntimeProbeClient()
    client.real_relay_connected = True
    client.real_relay_url = (
        "http://probe.local/api/browser/relay/connect-page"
        "?api_base_url=http://probe.local&relay_token=relay-secret"
    )

    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        real_chrome_relay=True,
        persist_evidence=True,
        evidence_path=evidence_path,
        review_queue_path=tmp_path / "review_queue.json",
    )
    report_text = json.dumps(report, ensure_ascii=False)
    evidence_text = evidence_path.read_text(encoding="utf-8")

    assert report["ready"] is True
    assert "relay-secret" not in report_text
    assert "relay-secret" not in evidence_text
    assert "relay_token=<redacted>" in report_text
    assert "relay_token=<redacted>" in evidence_text


def test_runtime_probe_reports_auth_blocker(tmp_path: Path) -> None:
    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=_AuthBlockedProbeClient(),
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ok"] is False
    assert report["ready"] is False
    assert report["auth"]["auth_blocked"] is True
    assert report["auth"]["auth_blocked_count"] >= 7
    assert report["cleanup"]["attempted"] is False
    assert report["runtime_readiness"]["verdict"] == "blocked"
    assert any(
        check["id"] == "runtime_probe_auth" and check["status"] == "fail"
        for check in report["runtime_readiness"]["checks"]
    )


def test_runtime_probe_can_bootstrap_passwordless_local_auth(tmp_path: Path) -> None:
    client = _LocalAuthProbeClient()
    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        auto_local_auth=True,
        local_auth_username="runtime-probe",
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ok"] is True
    assert report["ready"] is True
    assert report["auth"]["local_auth_attempted"] is True
    assert report["auth"]["local_auth_succeeded"] is True
    assert report["auth"]["bearer_token_provided"] is True
    assert "jwt.redacted.value" not in json.dumps(report, ensure_ascii=False)
    assert all(
        call.get("headers", {}).get("Authorization") == "Bearer jwt.redacted.value"
        for call in client.calls[2:]
    )


def test_runtime_probe_cleanup_failure_blocks_readiness(tmp_path: Path) -> None:
    client = _CleanupFailureProbeClient()
    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=client,
        review_queue_path=tmp_path / "review_queue.json",
    )

    assert report["ok"] is False
    assert report["ready"] is False
    assert report["cleanup"]["attempted"] is True
    assert report["cleanup"]["ok"] is False
    assert report["cleanup"]["status_code"] == 500
    assert report["operation_status"]["failed_count"] == 1
    assert report["runtime_readiness"]["verdict"] == "blocked"
    assert any(
        check["id"] == "runtime_probe_cleanup" and check["status"] == "fail"
        for check in report["runtime_readiness"]["checks"]
    )


def test_runtime_probe_reports_non_json_api_response(tmp_path: Path) -> None:
    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=_NonJsonActionProbeClient(),
        review_queue_path=tmp_path / "review_queue.json",
    )

    action = next(
        row for row in report["operations"]
        if row["path"] == "/api/browser/action"
    )
    assert report["ok"] is False
    assert report["ready"] is False
    assert report["operation_status"]["failed_count"] == 1
    assert action["status_code"] == 502
    assert action["content_type"] == "text/html"
    assert "non-json response" in action["error"]
    assert "upstream gateway error" in action["response_preview"]
    assert any(
        check["id"] == "runtime_probe_operations" and check["status"] == "fail"
        for check in report["runtime_readiness"]["checks"]
    )


def test_runtime_probe_persists_fresh_evidence_snapshot(tmp_path: Path) -> None:
    evidence_path = tmp_path / "runtime_evidence.json"
    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=_RuntimeProbeClient(),
        persist_evidence=True,
        evidence_path=evidence_path,
        review_queue_path=tmp_path / "review_queue.json",
    )
    lookup = load_browser_desktop_runtime_evidence(path=evidence_path)

    assert report["ready"] is True
    assert report["runtime_evidence_snapshot"]["usable"] is True
    assert lookup["available"] is True
    assert lookup["usable"] is True
    assert lookup["evidence"]["operation_status"]["failed_count"] == 0
    assert lookup["evidence"]["chrome_relay_handshake"]["ok"] is True
    assert lookup["evidence"]["computer_preview"]["risk"]["level"] == "low"
    assert lookup["evidence"]["computer_execute"]["ok"] is True
    assert lookup["evidence"]["computer_replay_case"]["replay_ready"] is True
    assert lookup["evidence"]["cleanup"]["ok"] is True
    assert "jwt.redacted.value" not in evidence_path.read_text(encoding="utf-8")


def test_runtime_evidence_snapshot_expires(tmp_path: Path) -> None:
    evidence_path = tmp_path / "runtime_evidence.json"
    report = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=_RuntimeProbeClient(),
        persist_evidence=True,
        evidence_path=evidence_path,
        review_queue_path=tmp_path / "review_queue.json",
    )
    created_at = float(report["runtime_evidence_snapshot"]["evidence"]["created_at"])

    lookup = load_browser_desktop_runtime_evidence(
        path=evidence_path,
        max_age_s=1,
        now=created_at + 5,
    )

    assert lookup["available"] is True
    assert lookup["fresh"] is False
    assert lookup["usable"] is False
    assert lookup["reason"] == "runtime evidence snapshot is stale"


def test_scorecard_can_use_runtime_probe_to_close_browser_desktop_gap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_probe(**_kwargs: Any) -> dict[str, Any]:
        return {
            "schema": "octopus.browser_desktop_runtime_probe.v1",
            "ok": True,
            "ready": True,
            "browser_health": {
                "schema": "octopus.browser_session_health.v1",
                "exists": True,
                "healthy": True,
                "score": 1.0,
                "issues": [],
                "replay_ready": True,
            },
            "computer_status": {
                "ok": True,
                "pyautogui_available": True,
                "uia_available": True,
                "lease": {"held": False, "ttl_seconds": 0},
                "recent_activity": [{"event": "probe_status_observed", "ok": True}],
            },
            "computer_preview": {
                "ok": True,
                "token": "preview-token",
                "action": {"action": "wait", "ms": 10},
                "risk": {"level": "low"},
                "lease": {"held": False},
            },
            "computer_execute": {
                "ok": True,
                "action": {"action": "wait", "ms": 10},
                "risk": {"level": "low"},
                "result": {"waited_ms": 10},
                "lease": {"held": True},
            },
            "computer_replay_case": {
                "schema": "octopus.computer_activity_replay_case.v1",
                "replay_ready": True,
                "case_id": "computer-activity:abc123",
                "fingerprint": "0123456789abcdef",
                "activity_count": 2,
                "pending_count": 0,
                "last_activity": {"event": "action_executed", "ok": True},
            },
            "chrome_relay_handshake": {
                "schema": "octopus.browser_chrome_relay_handshake.v1",
                "ok": True,
                "command_id": "cmd-1",
                "command_result": {"ok": True, "id": "cmd-1"},
                "status": {"connected": True},
            },
            "operation_status": {"ok": True, "total": 8, "failed_count": 0},
            "cleanup": {
                "enabled": True,
                "ok": True,
                "required": True,
                "attempted": True,
                "status_code": 200,
            },
            "runtime_readiness": {
                "ready": True,
                "score": 1.0,
                "blocker_count": 0,
                "warn_count": 0,
            },
        }

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_runtime_probe.run_browser_desktop_runtime_probe",
        fake_probe,
    )
    report = compute_agent_competitor_scorecard(
        include_runtime_probe=True,
        api_base_url="http://probe.local",
        review_queue_path=tmp_path / "review_queue.json",
    )
    browser = next(
        row for row in report["dimensions"]
        if row["id"] == "browser_desktop"
    )

    assert browser["scores"]["octopus"] == 95
    assert browser["octopus_score_source"] == "verified_browser_desktop_recalibration"
    assert browser["octopus_recalibration"]["requirements"][
        "browser_desktop_productization_ready"
    ] is True
    assert browser["octopus_recalibration"]["requirements"][
        "chrome_relay_and_desktop_policy_probe_ready"
    ] is True
    assert report["browser_desktop_quality"]["runtime_readiness"]["ready"] is True
    assert report["browser_desktop_quality"]["productization_ready"] is True
    assert report["browser_desktop_quality"]["capability_canary_ready"] is True
    assert report["radar"]["octopus_true_gap_edges"] == []


def test_scorecard_uses_fresh_runtime_evidence_snapshot_by_default(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "runtime_evidence.json"
    probe = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=_RuntimeProbeClient(),
        persist_evidence=True,
        evidence_path=evidence_path,
        review_queue_path=tmp_path / "review_queue.json",
    )

    report = compute_agent_competitor_scorecard(
        review_queue_path=tmp_path / "review_queue.json",
        runtime_evidence_path=evidence_path,
    )
    browser = next(
        row for row in report["dimensions"]
        if row["id"] == "browser_desktop"
    )

    assert probe["ready"] is True
    assert browser["scores"]["octopus"] == 95
    assert browser["octopus_score_source"] == "verified_browser_desktop_recalibration"
    assert report["browser_desktop_quality"]["runtime_probe"] is None
    assert report["browser_desktop_quality"]["runtime_evidence"]["usable"] is True
    assert report["browser_desktop_quality"]["productization_ready"] is True
    assert report["browser_desktop_quality"]["capability_canary_ready"] is True
    assert report["radar"]["octopus_true_gap_edges"] == []


def test_scorecard_refreshes_stale_runtime_evidence_when_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "runtime_evidence.json"
    stale = run_browser_desktop_runtime_probe(
        api_base_url="http://probe.local",
        session_id="probe-session",
        client=_RuntimeProbeClient(),
        persist_evidence=True,
        evidence_path=evidence_path,
        review_queue_path=tmp_path / "review_queue.json",
    )
    created_at = float(stale["runtime_evidence_snapshot"]["evidence"]["created_at"])
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["created_at"] = created_at - 7200
    payload["expires_at"] = created_at - 3600
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    calls = {"count": 0}

    def fake_probe(**kwargs: Any) -> dict[str, Any]:
        calls["count"] += 1
        client = _RuntimeProbeClient()
        client.real_relay_connected = bool(kwargs.get("real_chrome_relay"))
        return run_browser_desktop_runtime_probe(
            api_base_url="http://probe.local",
            session_id="probe-session",
            client=client,
            persist_evidence=True,
            evidence_path=kwargs.get("evidence_path"),
            review_queue_path=tmp_path / "review_queue.json",
            real_chrome_relay=bool(kwargs.get("real_chrome_relay")),
        )

    monkeypatch.setattr(
        "runtime.safety.evolution.browser_desktop_runtime_probe.run_browser_desktop_runtime_probe",
        fake_probe,
    )
    report = compute_agent_competitor_scorecard(
        review_queue_path=tmp_path / "review_queue.json",
        runtime_evidence_path=evidence_path,
        runtime_evidence_max_age_s=60,
        refresh_runtime_evidence_if_stale=True,
        real_chrome_relay=True,
    )
    browser = next(
        row for row in report["dimensions"]
        if row["id"] == "browser_desktop"
    )

    assert calls["count"] == 1
    assert browser["scores"]["octopus"] == 96
    assert report["browser_desktop_quality"]["runtime_probe"]["ready"] is True
    assert report["browser_desktop_quality"]["runtime_evidence"]["usable"] is True
    assert report["browser_desktop_quality"]["capability_canary_ready"] is True


def test_runtime_probe_script_handles_unreachable_backend() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/browser_desktop_runtime_probe.py",
            "--api-base-url",
            "http://127.0.0.1:9",
            "--timeout",
            "0.1",
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["schema"] == "octopus.browser_desktop_runtime_probe.v1"
    assert payload["ready"] is False
    assert payload["operations"][0]["ok"] is False
