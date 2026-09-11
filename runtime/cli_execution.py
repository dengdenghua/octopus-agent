"""Shared CLI tool registry and trusted execution boundary."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def build_cli_tool_stack():
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.builtins import register_all
    from runtime.execution.suckers.write_skills import register_exec_skill
    from runtime.execution.tool_engine import ToolExecutor
    from runtime.memory.journal import InMemoryJournal
    from runtime.safety.auth import TrustEngine

    registry = SkillRegistry()
    register_all(registry, refresh_prompt_catalog=False)
    register_exec_skill(registry)
    journal = InMemoryJournal()
    executor = ToolExecutor(
        registry=registry,
        journal=journal,
        immunity=TrustEngine(trusted_sources=["skill://public/*"], unknown_policy="allow"),
    )
    return SimpleNamespace(executor=executor, journal=journal, approval_router=None)


def cli_execution_boundary(*, engine, agent, prompt, thread_id, metadata, provider, args):
    from runtime.execution.host_boundary import create_host_execution_boundary
    from runtime.execution.request import ExecutionRequest
    from runtime.platform.config.schema import BudgetConfig

    boundary = create_host_execution_boundary(
        task_id=f"cli-turn-{uuid4().hex}",
        thread_id=thread_id,
        goal=prompt,
        timeout_s=float(getattr(args, "timeout", 900)),
        metadata={**metadata, "_host_workspace_read_root": Path(metadata["workspace_path"])},
        budget=BudgetConfig(max_tokens=args.max_tokens, max_usd=args.max_usd),
    )
    task = replace(
        boundary.request.task,
        execution_engine=engine,
        approval_provider=provider,
        server_auto_approve=metadata["permission_mode"] == "bypassPermissions",
        authorization_intent=prompt,
    )
    session = replace(
        boundary.session,
        agent=agent,
        metadata={**boundary.session.metadata, "_execution_task": task},
    )
    return ExecutionRequest(task, prompt), session
