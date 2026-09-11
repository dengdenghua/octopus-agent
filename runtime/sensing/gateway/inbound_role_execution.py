"""Give an inbound role the same host task boundary as local delegation."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4


def execute_role(call, *, role_id, prompt, data_dir, actor_id):
    from runtime.execution.host_boundary import create_host_execution_boundary
    from runtime.execution.request import ExecutionRequest, execution_request_scope
    from runtime.platform.process.scope import ExecutionScope
    from runtime.platform.process.session import session_scope
    from runtime.safety.approval.approval_gate import AutoDenyProvider

    # No remote context/session/model identifiers become host task coordinates.
    task_id = "a2a_" + uuid4().hex
    root = Path(data_dir).resolve() / "workspaces" / task_id
    root.mkdir(parents=True, exist_ok=True)
    metadata = {
        "source": "a2a_inbound",
        "direct_conversation_reply": True,
        "context_steward_managed": True,
        "share_history": False,
        "tool_allowlist_read_only": True,
        "trust_score": 0.3,
        "_inherited_injection_taint": "medium",
        "workspace_path": str(root),
    }
    actor = actor_id if actor_id != "local-a2a" else None
    boundary = create_host_execution_boundary(
        task_id=task_id,
        thread_id=task_id,
        goal=prompt,
        timeout_s=120,
        actor_id=actor,
        tenant_id=actor,
        metadata=metadata,
    )
    task = replace(
        boundary.request.task,
        permissions=ExecutionScope(
            mode="read_only",
            requested_mode="read_only",
            readable_roots=(root,),
            writable_roots=(),
            approval_policy="never",
            shell_policy="deny",
            network_policy="deny",
            browser_policy="deny",
        ),
        approval_provider=AutoDenyProvider(),
    )
    session = replace(
        boundary.session, metadata={**boundary.session.metadata, "_execution_task": task}
    )
    with session_scope(session), execution_request_scope(ExecutionRequest(task, prompt)):
        return call(
            agent_id=role_id, prompt=prompt, context=metadata, session=session, timeout_s=120
        )
