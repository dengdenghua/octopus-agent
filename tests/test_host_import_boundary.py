"""Cold-process checks keep external host imports independent of native planning."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "target",
    [
        "runtime.platform.config.schema",
        "runtime.execution.request",
        "runtime.execution.opencode_backend",
        "runtime.sensing.gateway.realtime_opencode_backend",
        "runtime.execution.tool_engine.tool_protocol",
        "runtime.core.cerebrum.pause_control",
        "runtime.cli",
        "runtime.sensing.model_router",
        "runtime.memory",
    ],
)
def test_host_import_does_not_load_native_planner(target):
    code = (
        "import importlib,json,sys; "
        f"importlib.import_module({target!r}); "
        "print(json.dumps(list(sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    loaded = set(json.loads(result.stdout))
    assert "runtime.core.cerebrum.llm_planner" not in loaded
    assert "runtime.platform.config.builder" not in loaded
    if target == "runtime.cli":
        assert not loaded.intersection(
            {
                "runtime.cli_run",
                "runtime.cli_reflect",
                "runtime.cli_serve",
                "runtime.cli_core",
                "runtime.core.graph_runtime",
            }
        )
    if target == "runtime.execution.opencode_backend":
        assert "runtime.execution.tool_engine.host_mcp" not in loaded
        assert "uvicorn" not in loaded
        assert "mcp" not in loaded
    if target == "runtime.sensing.model_router":
        assert not any(name.startswith(target + ".") for name in loaded)
    if target == "runtime.memory":
        assert not any(name.startswith(target + ".") for name in loaded)


@pytest.mark.parametrize(
    "package,module,names",
    [
        (
            "runtime.platform.config",
            "runtime.platform.config.builder",
            ("BuiltStack", "build_from_config"),
        ),
        ("runtime.core.cerebrum", "runtime.core.cerebrum.llm_planner", ("LLMPlanner",)),
        (
            "runtime.sensing.model_router",
            "runtime.sensing.model_router.models",
            ("ModelRouter", "MockModelRouter", "ModelRequest"),
        ),
        (
            "runtime.sensing.model_router",
            "runtime.sensing.model_router.gemini_router",
            ("GeminiModelRouter", "GeminiRouterError"),
        ),
        (
            "runtime.sensing.model_router",
            "runtime.sensing.model_router.ollama_router",
            ("OllamaModelRouter", "OllamaRouterError"),
        ),
        (
            "runtime.sensing.model_router",
            "runtime.sensing.model_router.openai_router",
            ("OpenAIModelRouter", "OpenAIRouterError"),
        ),
        (
            "runtime.sensing.model_router",
            "runtime.sensing.model_router.pooled_router",
            ("PooledModelRouter",),
        ),
        ("runtime.cli", "runtime.cli_run", ("run_goal", "run_goal_from_config", "run_resume")),
        (
            "runtime.core.cerebrum",
            "runtime.core.cerebrum.planner",
            ("StaticPlanner", "PlannerError"),
        ),
        (
            "runtime.execution.tool_engine",
            "runtime.execution.tool_engine.executor",
            ("ToolExecutor", "StepExecutionError"),
        ),
    ],
)
def test_public_exports_remain_the_original_objects(package, module, names):
    import importlib

    public = importlib.import_module(package)
    implementation = importlib.import_module(module)
    for name in names:
        assert name in dir(public)
        assert getattr(public, name) is getattr(implementation, name)
    with pytest.raises(AttributeError):
        _ = public.missing_public_export


@pytest.mark.parametrize("argv", [["--help"], ["run", "--help"], ["serve", "--help"]])
def test_cli_help_does_not_construct_execution_dependencies(argv):
    code = f"""
import contextlib,io,json,sys
from runtime.cli import main
with contextlib.redirect_stdout(io.StringIO()) as output:
    try:
        result = main({argv!r})
    except SystemExit as exc:
        result = exc.code
assert result == 0
assert "usage:" in output.getvalue().lower()
print(json.dumps(list(sys.modules)))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    loaded = set(json.loads(result.stdout))
    assert not loaded.intersection(
        {
            "runtime.cli_run",
            "runtime.cli_reflect",
            "runtime.cli_serve",
            "runtime.cli_core",
            "runtime.core.graph_runtime",
        }
    )


def test_mcp_connection_reexport_preserves_identity_and_secret_redaction():
    from dataclasses import FrozenInstanceError

    from runtime.execution.host_mcp_connection import HostMCPConnection
    from runtime.execution.tool_engine.host_mcp import HostMCPConnection as LegacyConnection

    assert LegacyConnection is HostMCPConnection
    connection = LegacyConnection("http://127.0.0.1:12345/mcp", "secret-token")
    assert "secret-token" not in repr(connection)
    with pytest.raises(FrozenInstanceError):
        connection.token = "replacement"


@pytest.mark.parametrize(
    "alias,module",
    [
        ("trace_store", "diagnostics.trace_store"),
        ("deep_evolution", "learning.deep_evolution"),
        ("blackboard", "runtime_state.blackboard"),
        ("skill_library", "skills_lib.skill_library"),
        ("user_store", "users.user_store"),
        ("diagnostics", "diagnostics"),
    ],
)
def test_memory_legacy_module_exports_preserve_identity(alias, module):
    import importlib

    import runtime.memory as memory

    assert alias in dir(memory)
    assert getattr(memory, alias) is importlib.import_module(f"runtime.memory.{module}")


@pytest.mark.parametrize("configured", [False, True])
def test_native_provider_is_loaded_only_when_configured(configured):
    code = f"""
import os,sys,tempfile
from unittest.mock import patch
for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(key, None)
with tempfile.TemporaryDirectory() as root:
    os.environ["OCTOPUS_HOME"] = root
    os.environ["OCTOPUS_DATA_DIR"] = root
    from runtime.platform.config.builder import _build_planner
    from runtime.platform.config.schema import AgentConfig, PlannerConfig
    from runtime.execution.suckers import SkillRegistry
    from runtime.memory.journal import InMemoryJournal
    config = AgentConfig(planner=PlannerConfig(
        type="llm", model="claude-sonnet-4-6",
        anthropic_api_key="test-key" if {configured!r} else None,
    ))
    with patch(
        "runtime.sensing.model_router.openai_router.build_fallback_router_from_custom_models",
        return_value=None,
    ):
        planner = _build_planner(config, SkillRegistry(), InMemoryJournal())
    assert planner.router is not None
    assert ("runtime.sensing.model_router.anthropic_router" in sys.modules) is {configured!r}
    assert ("anthropic" in sys.modules) is {configured!r}
    for unused in ("gemini_router", "ollama_router", "pooled_router", "capability_probe"):
        assert f"runtime.sensing.model_router.{{unused}}" not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
