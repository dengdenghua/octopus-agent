from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.threads import ThreadStateStore
from runtime.sensing.gateway._conversation_error_diagnostics import (
    build_conversation_error_diagnostics,
    classify_conversation_error,
)
from runtime.sensing.gateway.thread_state_router import create_thread_state_router


def _error_message(message_id: str, message: str, code: str) -> dict[str, object]:
    return {
        "type": "ai",
        "id": message_id,
        "content": f"raw display: {message}",
        "additional_kwargs": {
            "error": {
                "message": message,
                "will_retry": False,
                "info": {"code": code},
            }
        },
    }


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        ("router", "http_429: Rate limit exceeded", ("rate_limit", "retry_later", True)),
        (
            "router",
            "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
            ("network", "retry", True),
        ),
        (
            "_ToolStartAuditError",
            "tool execution blocked because its start event was not durably applied",
            ("lifecycle", "retry_task", True),
        ),
        (
            "codex_app_server_error",
            "unexpected status 409 Conflict: Responses request replay was rejected",
            ("engine_replay", "retry_task", True),
        ),
        (
            "ChatGPTSubscriptionRouterError",
            "ChatGPT 登录凭据刷新失败",
            ("authentication", "reauthenticate", True),
        ),
    ],
)
def test_classifies_observed_conversation_failures(
    code: str,
    message: str,
    expected: tuple[str, str, bool],
) -> None:
    assert classify_conversation_error(code, message) == expected


def test_report_is_bounded_deduplicated_and_does_not_expose_raw_errors() -> None:
    secret = "sk-super-secret-value"
    thread = {
        "thread_id": "thread-1",
        "updated_at": "2026-09-01T08:22:59Z",
        "values": {
            "title": "Production check",
            "messages": [
                _error_message("same", f"invalid credential {secret}", "auth"),
                _error_message("same", f"invalid credential {secret}", "auth"),
                _error_message("rate", "http_429: Rate limit exceeded", "router"),
            ],
        },
    }

    report = build_conversation_error_diagnostics([thread], message_limit=20, sample_limit=1)

    assert report["summary"] == {
        "threads_scanned": 1,
        "threads_with_errors": 1,
        "error_count": 2,
        "retryable_count": 2,
        "by_code": {"auth": 1, "router": 1},
        "by_category": {"authentication": 1, "rate_limit": 1},
    }
    assert len(report["samples"]) == 1
    encoded = json.dumps(report)
    assert secret not in encoded
    assert "invalid credential" not in encoded


def test_report_rejects_untrusted_error_code_text() -> None:
    thread = {
        "thread_id": "thread-unsafe-code",
        "values": {
            "messages": [
                _error_message(
                    "error-id",
                    "provider failed",
                    "router secret=value with spaces",
                )
            ]
        },
    }

    report = build_conversation_error_diagnostics([thread])

    assert report["summary"]["by_code"] == {"unknown": 1}
    assert report["samples"][0]["code"] == "unknown"
    assert "secret=value" not in json.dumps(report)


def test_owner_filtered_endpoint_returns_only_structured_diagnostics() -> None:
    store = ThreadStateStore()
    created = store.create(
        values={
            "title": "Audit project",
            "messages": [
                _error_message(
                    "ssl",
                    "[SSL: UNEXPECTED_EOF_WHILE_READING] private upstream detail",
                    "router",
                )
            ],
        }
    )
    app = FastAPI()
    app.include_router(create_thread_state_router(store=store))

    response = TestClient(app).get(
        "/api/threads/diagnostics/errors",
        params={"thread_limit": 10, "message_limit": 10, "sample_limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "octopus.conversation_error_diagnostics.v1"
    assert body["bounds"] == {
        "message_limit_per_thread": 10,
        "sample_limit": 10,
        "thread_limit": 10,
    }
    assert body["summary"]["by_category"] == {"network": 1}
    assert body["samples"][0]["thread_id"] == created["thread_id"]
    encoded = response.text
    assert "private upstream detail" not in encoded
    assert "UNEXPECTED_EOF" not in encoded


def test_endpoint_never_aggregates_another_actors_threads() -> None:
    from runtime.safety.auth import Identity, IdentityStore

    identities = IdentityStore()
    identities.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    identities.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")
    store = ThreadStateStore()
    for actor in ("alice", "bob"):
        store.ensure_thread(
            f"{actor}-thread",
            metadata={"owner_actor_id": actor},
            values={
                "title": f"{actor} private task",
                "messages": [
                    _error_message(
                        f"{actor}-error",
                        f"{actor} private upstream failure",
                        "router",
                    )
                ],
            },
        )
    app = FastAPI()
    app.include_router(
        create_thread_state_router(
            store=store,
            identity_store=identities,
            require_auth=True,
        )
    )

    response = TestClient(app).get(
        "/api/threads/diagnostics/errors",
        params={"thread_limit": 1},
        headers={"Authorization": "Bearer sk-alice"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["threads_scanned"] == 1
    assert body["summary"]["error_count"] == 1
    assert [sample["thread_id"] for sample in body["samples"]] == ["alice-thread"]
    assert "bob" not in response.text
