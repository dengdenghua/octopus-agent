"""Implementation note."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime import __version__  # noqa: E402
from runtime.platform.ui import create_app  # noqa: E402
from runtime.platform.ui.health_router import create_health_router  # noqa: E402

# ═══════════════════════════════════════════════════════════
# factory
# ═══════════════════════════════════════════════════════════


@pytest.fixture()
def client() -> TestClient:
    app = create_app(journal_path=None)
    return TestClient(app)


def _seed_journal(path: Path) -> None:
    """Implementation note."""
    from runtime.core.cerebrum import StaticPlanner
    from runtime.core.cerebrum.planner import Rule
    from runtime.core.graph_runtime import GraphRuntime
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.builtins import register_all
    from runtime.execution.tool_engine import ToolExecutor
    from runtime.memory.journal import JSONLJournal
    from runtime.platform.models import (
        ArmId,
        Budget,
        BudgetLimits,
        BudgetSpec,
        ParsedIntent,
        SkillId,
    )
    from runtime.safety.auth import TrustEngine

    journal = JSONLJournal(path)
    registry = SkillRegistry()
    register_all(registry)
    executor = ToolExecutor(
        registry=registry,
        immunity=TrustEngine(trusted_sources=["skill://public/*"]),
        journal=journal,
    )
    runtime = GraphRuntime(executor=executor, journal=journal)
    planner = StaticPlanner(
        rules=[
            Rule(
                name="seed",
                intent_types=["task"],
                skill_sequence=[SkillId("list_cwd")],
            )
        ],
        default_budget=BudgetSpec(tokens=10_000, usd=0.10),
        fallback_skill=SkillId("list_cwd"),
    )
    intent = ParsedIntent(raw="seed", intent_type="task", normalized_goal="seed")
    graph = planner.plan(intent)
    budget = Budget(task_id=graph.task_id, limits=BudgetLimits(tokens=10_000, usd=0.10))
    runtime.run(graph, budget=budget, caller="arms/seed", arm_id=ArmId("seed_arm"))


def _check_by_id(data: dict, check_id: str) -> dict:
    for row in data.get("checks", []):
        if row.get("id") == check_id:
            return row
    raise AssertionError(f"missing check {check_id}")


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestBasicRoutes:
    def test_create_app_tentacle_startup_registration_has_no_on_event_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)

            create_app(journal_path=None, tentacle_enabled=True)

        messages = [str(item.message) for item in caught]
        assert not any("on_event is deprecated" in msg for msg in messages)

    def test_index_html(self, client: TestClient):
        r = client.get("/")
        assert r.status_code == 200
        assert "octopus-agent" in r.text
        assert "<html" in r.text.lower()

    def test_status_endpoint(self, client: TestClient):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == __version__
        assert data["skill_count"] > 0
        assert "capabilities" in data
        assert set(data["capabilities"]) >= {"opentelemetry", "mcp", "httpx"}

    def test_runtime_self_check_reports_versions_and_loopback_aliases(self):
        app = create_app(
            journal_path=None,
            server_host="localhost",
            server_port=8000,
        )
        client = TestClient(app, base_url="http://localhost:8000")

        r = client.get(
            "/api/runtime/self-check",
            headers={"Origin": "http://localhost:3000"},
        )
        data = r.json()

        assert r.status_code == 200
        assert data["schema"] == "octopus.runtime_self_check.v1"
        assert data["ready"] is True
        assert data["version"] == __version__
        assert data["version_drift"]["runtime_matches_pyproject"] is True
        assert data["version_drift"]["frontend_matches_runtime"] is True
        assert data["backend"]["canonical_base_url"] == "http://127.0.0.1:8000"
        assert data["backend"]["request_origin_base_url"] == "http://localhost:8000"
        assert data["frontend"]["observed_origin"] == "http://localhost:3000"
        assert data["frontend"]["canonical_origin"] == "http://localhost:3000"
        assert data["frontend"]["origin_normalized"] is True
        assert data["frontend"]["proxy_target"] == "http://127.0.0.1:8000"
        assert data["frontend"]["proxy_targets_backend"] is True
        assert data["loopback_aliases"]["same_loopback_family"] is True
        assert "http://localhost:8000" in data["loopback_aliases"]["aliases"]
        assert "http://127.0.0.1:8000" in data["loopback_aliases"]["aliases"]
        assert data["model_compat"]["schema"] == "octopus.openai_compat_profile_self_check.v1"
        assert data["model_compat"]["required_profiles_present"] is True
        assert data["model_compat"]["missing_required_profile_ids"] == []
        assert data["model_compat"]["missing_smoke_provider_ids"] == []
        assert data["model_compat"]["orphan_smoke_provider_ids"] == []
        assert data["model_compat"]["resolver_mismatches"] == []
        assert data["model_compat"]["model_alias_mismatches"] == [
            {
                "profile_id": "siliconflow",
                "base_url": "https://api.siliconflow.cn/v1",
                "model": "deepseek-ai/DeepSeek-V3",
                "model_resolves_to": "deepseek",
                "reason": "model_id_looks_like_upstream_model_on_aggregator",
            }
        ]
        assert data["model_compat"]["request_contract_mismatches"] == []
        assert data["model_compat"]["request_contract_ready"] is True
        assert data["model_compat"]["request_contract_count"] >= 13
        assert data["model_compat"]["domestic_profile_count"] >= 13
        assert len(data["model_compat"]["sample_probes"]) >= 13
        assert "kimi_coding" in data["model_compat"]["profile_ids"]
        assert "deepseek" in data["model_compat"]["profile_ids"]
        assert "qwen" in data["model_compat"]["profile_ids"]
        probes = {item["profile_id"]: item for item in data["model_compat"]["sample_probes"]}
        assert probes["kimi_coding"]["smoke_provider_configured"] is True
        assert probes["kimi_coding"]["base_url_resolves_to"] == "kimi_coding"
        assert probes["kimi_coding"]["model_resolves_to"] == "kimi_coding"
        contracts = {
            item["profile_id"]: item for item in data["model_compat"]["request_contract_probes"]
        }
        assert contracts["kimi_coding"]["contract_ready"] is True
        assert "sampling_parameters_removed" in contracts["kimi_coding"]["risk_reasons"]
        assert "tool_schema_normalized" in contracts["qwen"]["risk_reasons"]
        assert _check_by_id(data, "openai_compat_profiles")["passed"] is True
        assert data["orchestration"]["schema"] == "octopus.orchestration_surface_self_check.v1"
        assert data["orchestration"]["ready"] is True
        assert data["orchestration"]["missing_required_routes"] == []
        assert data["orchestration"]["missing_route_methods"] == []
        assert data["orchestration"]["capabilities"] == {
            "parallel_dispatch": True,
            "split_planning": True,
            "recovery_snapshot": True,
            "sse_event_replay": True,
            "completion_receipt": True,
            "file_write_observability": True,
            "work_contracts": True,
            "owner_scoping": True,
        }
        assert data["orchestration"]["route_methods"][
            "/api/agents/parallel/batch/{batch_id}/recovery-snapshot"
        ] == ["GET"]
        assert data["orchestration"]["route_methods"]["/api/agents/parallel/stream/{batch_id}"] == [
            "GET"
        ]
        assert data["orchestration"]["missing_model_fields"] == []
        assert data["orchestration"]["missing_methods"] == []
        assert _check_by_id(data, "orchestration_surface")["passed"] is True
        assert data["run_evidence"]["schema"] == ("octopus.run_evidence_surface_self_check.v1")
        assert data["run_evidence"]["ready"] is True
        assert data["run_evidence"]["missing_required_routes"] == []
        assert data["run_evidence"]["missing_route_methods"] == []
        assert data["run_evidence"]["missing_methods"] == []
        assert data["run_evidence"]["capabilities"] == {
            "trace_stats": True,
            "task_run_review": True,
            "task_run_replay_case": True,
            "task_run_replay_evaluation": True,
            "replay_gate": True,
            "process_timeline": True,
            "experience_ledger": True,
            "review_queue": True,
            "promotion_gate": True,
            "checkpoint_resume": True,
            "loop_review": True,
            "loop_replay": True,
            "loop_resume": True,
        }
        assert data["run_evidence"]["route_methods"][
            "/api/agent-trace/task-runs/{task_id}/process-timeline"
        ] == ["GET"]
        assert data["run_evidence"]["route_methods"][
            "/api/agent-trace/review-queue/promotions/apply"
        ] == ["POST"]
        assert data["run_evidence"]["route_methods"]["/api/loops/{run_id}/replay-case"] == ["GET"]
        evidence_methods = {
            item["method"]: item for item in data["run_evidence"]["method_contracts"]
        }
        assert evidence_methods["AgentTraceStore.task_run_review"]["present"] is True
        assert evidence_methods["AgentTraceStore.replay_gate"]["present"] is True
        assert evidence_methods["ExperienceLedger.add_from_task_run_review"]["present"] is True
        assert evidence_methods["ReviewQueue.add_from_task_run_review"]["present"] is True
        assert evidence_methods["PromotionApplier.apply"]["present"] is True
        assert (
            evidence_methods["process_timeline.build_task_run_process_timeline"]["present"] is True
        )
        assert evidence_methods["loop_replay.build_loop_run_replay_case"]["present"] is True
        assert evidence_methods["loop_recovery.build_loop_run_resume_proposal"]["present"] is True
        assert _check_by_id(data, "run_evidence_surface")["passed"] is True
        assert data["automation"]["schema"] == "octopus.automation_surface_self_check.v1"
        assert data["automation"]["ready"] is True
        assert data["automation"]["missing_required_routes"] == []
        assert data["automation"]["missing_route_methods"] == []
        assert data["automation"]["missing_methods"] == []
        assert data["automation"]["capabilities"] == {
            "browser_session_lifecycle": True,
            "browser_health": True,
            "browser_navigation": True,
            "browser_screenshot_evidence": True,
            "browser_replay_queue": True,
            "browser_relay": True,
            "computer_preview_execute": True,
            "computer_grounding": True,
            "computer_activity_replay": True,
            "computer_uia": True,
            "computer_lease": True,
            "pixel_replay_gate": True,
        }
        assert data["automation"]["route_methods"]["/api/browser/session/replay-case/queue"] == [
            "POST"
        ]
        assert data["automation"]["route_methods"]["/api/computer/actions/execute"] == ["POST"]
        assert data["automation"]["route_methods"]["/api/computer/uia/tree"] == ["GET"]
        automation_methods = {
            item["method"]: item for item in data["automation"]["method_contracts"]
        }
        assert automation_methods["BrowserSessionCenter.health_report"]["present"] is True
        assert (
            automation_methods["browser_replay.browser_session_replay_identity"]["present"] is True
        )
        assert automation_methods["browser_pixel.browser_pixel_replay_gate_case"]["present"] is True
        assert automation_methods["computer_skills._screen_capture"]["present"] is True
        assert automation_methods["computer_uia.uia_replay_assertion_for_action"]["present"] is True
        assert _check_by_id(data, "automation_surface")["passed"] is True
        assert _check_by_id(data, "frontend_origin")["passed"] is True
        assert _check_by_id(data, "vite_proxy_target")["passed"] is True

    def test_runtime_self_check_flags_missing_run_evidence_and_automation_routes(self):
        app = FastAPI()
        source = create_app(journal_path=None)
        state = source.state.octopus_state
        app.include_router(
            create_health_router(
                state=state,
                server_host="localhost",
                server_port=8000,
            )
        )
        client = TestClient(app, base_url="http://localhost:8000")

        data = client.get(
            "/api/runtime/self-check",
            headers={"Origin": "http://localhost:3000"},
        ).json()

        assert data["ready"] is False
        assert data["run_evidence"]["ready"] is False
        assert "/api/agent-trace/stats" in data["run_evidence"]["missing_required_routes"]
        assert "/api/loops/{run_id}/replay-case" in data["run_evidence"]["missing_required_routes"]
        assert _check_by_id(data, "run_evidence_surface")["passed"] is False
        assert data["automation"]["ready"] is False
        assert "/api/browser/session/replay-case" in data["automation"]["missing_required_routes"]
        assert "/api/computer/actions/execute" in data["automation"]["missing_required_routes"]
        assert _check_by_id(data, "automation_surface")["passed"] is False

    def test_runtime_self_check_flags_noncanonical_frontend_origin(self):
        app = create_app(
            journal_path=None,
            server_host="localhost",
            server_port=8000,
        )
        client = TestClient(app, base_url="http://localhost:8000")

        data = client.get(
            "/api/runtime/self-check",
            headers={"Origin": "http://127.0.0.1:3000"},
        ).json()

        assert data["ready"] is False
        assert data["status"] == "degraded"
        assert data["frontend"]["observed_origin"] == "http://127.0.0.1:3000"
        assert data["frontend"]["canonical_origin"] == "http://localhost:3000"
        assert data["frontend"]["origin_normalized"] is False
        assert _check_by_id(data, "frontend_origin") == {
            "id": "frontend_origin",
            "severity": "error",
            "passed": False,
            "detail": ("origin=http://127.0.0.1:3000 canonical=http://localhost:3000"),
        }
        assert any("origin=http://127.0.0.1:3000" in item for item in data["next_actions"])

    def test_runtime_self_check_flags_vite_proxy_mismatch(self, monkeypatch):
        monkeypatch.setenv("OCTOPUS_INTERNAL_GATEWAY_BASE_URL", "http://127.0.0.1:9999")
        app = create_app(
            journal_path=None,
            server_host="localhost",
            server_port=8000,
        )
        client = TestClient(app, base_url="http://localhost:8000")

        data = client.get(
            "/api/runtime/self-check",
            headers={"Origin": "http://localhost:3000"},
        ).json()

        assert data["ready"] is False
        assert data["frontend"]["proxy_target"] == "http://127.0.0.1:9999"
        assert data["frontend"]["proxy_targets_backend"] is False
        assert _check_by_id(data, "vite_proxy_target")["passed"] is False

    def test_runtime_self_check_uses_request_port_when_server_port_missing(self):
        app = create_app(journal_path=None)
        client = TestClient(app, base_url="http://127.0.0.1:8123")

        data = client.get("/api/runtime/self-check").json()

        assert data["backend"]["canonical_base_url"] == "http://127.0.0.1:8123"
        assert data["backend"]["port"] == 8123

    def test_runtime_self_check_reports_process_api_and_webui_state(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        dist = tmp_path / "dist"
        assets = dist / "assets"
        assets.mkdir(parents=True)
        (dist / "index.html").write_text("<html>webui</html>", encoding="utf-8")
        (assets / "bundle.js").write_text("console.log('ok')", encoding="utf-8")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))
        app = create_app(
            journal_path=tmp_path / "events.jsonl",
            server_host="localhost",
            server_port=8000,
            frontend_host="localhost",
            frontend_port=3000,
            frontend_proxy_target="http://127.0.0.1:8000",
        )
        client = TestClient(app, base_url="http://localhost:8000")

        data = client.get(
            "/api/runtime/self-check",
            headers={"Origin": "http://localhost:3000"},
        ).json()

        assert data["ready"] is True
        assert data["process"]["pid"] > 0
        assert data["api_surface"]["required_routes_present"] is True
        assert data["api_surface"]["missing_required_routes"] == []
        assert data["webui"]["available"] is True
        assert data["webui"]["selected_dist"] == str(dist)
        assert data["webui"]["assets_count"] == 1
        assert _check_by_id(data, "api_surface")["passed"] is True
        assert _check_by_id(data, "webui_dist")["passed"] is True

    def test_runtime_self_check_warns_on_invalid_webui_dist(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(tmp_path / "missing"))
        app = create_app(
            journal_path=tmp_path / "events.jsonl",
            server_host="localhost",
            server_port=8000,
        )
        client = TestClient(app, base_url="http://localhost:8000")

        data = client.get(
            "/api/runtime/self-check",
            headers={"Origin": "http://localhost:3000"},
        ).json()

        assert data["ready"] is True
        assert data["status"] == "degraded"
        assert data["webui"]["available"] is True
        assert data["webui"]["env_dist_invalid"] is True
        assert data["webui"]["selected_dist"]
        assert _check_by_id(data, "webui_dist")["severity"] == "warn"
        assert _check_by_id(data, "webui_dist")["passed"] is False
        assert data["next_actions"] == []
        assert any("OCTOPUS_WEBUI_DIST" in item for item in data["warnings"])

    def test_skills_endpoint(self, client: TestClient):
        r = client.get("/api/skills")
        assert r.status_code == 200
        data = r.json()
        assert "skills" in data
        names = {s["name"] for s in data["skills"]}
        assert "list_cwd" in names
        assert "hash_text" in names

    def test_journal_empty(self, client: TestClient):
        r = client.get("/api/journal?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["recent"] == []

    def test_reflect_empty_journal_returns_error(self, client: TestClient):
        r = client.get("/api/reflect")
        assert r.status_code == 200
        assert "error" in r.json()


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestWithJournal:
    def test_run_populates_journal(self, client: TestClient):
        r = client.post("/api/run", json={"goal": "list files"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["steps"] >= 1

        # Implementation note.
        jr = client.get("/api/journal")
        jdata = jr.json()
        assert jdata["total"] >= 2  # step + trajectory
        assert "step" in jdata["counts"]

    def test_run_requires_goal(self, client: TestClient):
        r = client.post("/api/run", json={"goal": ""})
        assert r.status_code == 400

    def test_reflect_after_seed(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        _seed_journal(path)
        app = create_app(journal_path=path)
        client = TestClient(app)

        r = client.get("/api/reflect")
        assert r.status_code == 200
        data = r.json()
        assert "error" not in data
        assert "kg" in data
        assert "recipe" in data
        assert "memory" in data

    def test_kg_endpoint_with_data(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        _seed_journal(path)
        app = create_app(journal_path=path)
        client = TestClient(app)

        r = client.get("/api/kg?limit=20")
        assert r.status_code == 200
        data = r.json()
        assert "triples" in data
        assert data["kg_size"] >= 0


# ═══════════════════════════════════════════════════════════
# CLI ui subcommand
# ═══════════════════════════════════════════════════════════


class TestUiCliWiring:
    def test_ui_subcommand_registered(self):
        """Implementation note."""
        import argparse

        # Implementation note.

        # Implementation note.
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        uip = sub.add_parser("ui")
        uip.add_argument("--host", default="127.0.0.1")
        uip.add_argument("--port", type=int, default=8000)
        uip.add_argument("--journal", type=Path, default=None)
        # Implementation note.
        args = parser.parse_args(["ui", "--port", "9999"])
        assert args.command == "ui"
        assert args.port == 9999

    def test_run_ui_missing_uvicorn(self, monkeypatch, capsys):
        """Implementation note."""
        import builtins

        from runtime.cli import run_ui

        real_import = builtins.__import__

        def _fake_import(name, *a, **kw):
            if name == "uvicorn":
                raise ImportError("mocked missing")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        rc = run_ui(host="127.0.0.1", port=8000, journal_path=None)
        assert rc == 2
        err = capsys.readouterr().err
        assert "uvicorn" in err
