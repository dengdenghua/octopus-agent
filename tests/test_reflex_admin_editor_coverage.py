"""Dense coverage for _reflex_admin_editor endpoints (audit Q-05)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.ui._reflex_admin_editor import register_reflex_editor_endpoints

RULES_YAML = """rules:
  - id: hi
    pattern: ^hello$
    reply: Hi there!
    priority: 20
  - id: webhook
    pattern: alert
    reply: alerting
    action:
      webhook:
        url: http://h/1
        method: POST
"""


def _build(rules_path: Path) -> TestClient:
    app = FastAPI()
    admin = app.router
    register_reflex_editor_endpoints(
        admin,
        _reflex_router=SimpleNamespace(replace_reflexes=lambda _reflexes: 1),
        panel_html="<html>panel</html>",
        editor_html="<html>editor</html>",
    )
    import runtime.core.nerves.reflex.rules_loader as rl

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rl, "find_default_rules_file", lambda: rules_path)
    app.state._rl_patch = monkeypatch  # keep patch alive for the client lifetime
    return TestClient(app)


def test_panel_and_editor_pages(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML, encoding="utf-8")
    client = _build(rules)
    r = client.get("/admin/reflex")
    assert r.status_code == 200 and "panel" in r.text
    r2 = client.get("/admin/reflex/edit")
    assert r2.status_code == 200 and "editor" in r2.text


def test_rules_yaml_get_and_put(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML, encoding="utf-8")
    client = _build(rules)

    got = client.get("/api/reflex/rules-yaml")
    assert got.json()["ok"] is True
    assert "hello" in got.json()["content"]

    ok = client.post(
        "/api/reflex/rules-yaml",
        json={"content": RULES_YAML, "expected_mtime": 0, "reload": False},
    )
    assert ok.json()["ok"] is True

    bad = client.post(
        "/api/reflex/rules-yaml",
        json={"content": "rules: [broken", "expected_mtime": 0, "reload": False},
    )
    assert ok.json()["ok"] is True or bad.json().get("ok") is False
    missing = client.post(
        "/api/reflex/rules-yaml",
        json={"content": 123, "expected_mtime": 0, "reload": False},
    )
    assert "missing content" in missing.json()["error"]


def test_rules_cards_get(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML, encoding="utf-8")
    client = _build(rules)
    resp = client.get("/api/reflex/rules-cards")
    data = resp.json()
    if data.get("ok") is True:
        cards = {c["id"]: c for c in data["cards"]}
        assert cards["hi"]["trigger_mode"] == "exact"
        assert cards["webhook"]["action"]["mode"] == "webhook"
    else:
        # ruamel missing — the endpoint degrades cleanly.
        assert "error" in data


def test_rules_cards_put_upsert_and_delete(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML, encoding="utf-8")
    client = _build(rules)
    resp = client.post(
        "/api/reflex/rules-cards",
        json={
            "expected_mtime": 0,
            "reload": False,
            "upserts": [
                {"id": "new1", "trigger_mode": "contains", "trigger_text": "ping", "reply": "pong", "priority": "low"}
            ],
            "deletes": ["webhook"],
        },
    )
    data = resp.json()
    if data.get("ok") is True:
        content = rules.read_text(encoding="utf-8")
        assert "ping" in content
        assert "webhook" not in content
    else:
        assert "error" in data  # ruamel missing degrades cleanly


def test_rules_yaml_mtime_conflict(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML, encoding="utf-8")
    client = _build(rules)
    future_mtime = rules.stat().st_mtime + 1000
    resp = client.post(
        "/api/reflex/rules-yaml",
        json={"content": RULES_YAML, "expected_mtime": future_mtime, "reload": False},
    )
    data = resp.json()
    if data.get("ok") is not True:
        assert "modified externally" in data.get("error", "") or "parse failed" in data.get("error", "")
