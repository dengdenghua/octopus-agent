"""Standalone loopback A2A role backed by the installed WorkBuddy CLI.

Run: python -m runtime.sensing.gateway.workbuddy_bridge --port 8321
On a different machine use an SSH loopback tunnel, not a public listener.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
    Task,
    TaskState,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from runtime.execution.workbuddy_remote import (
    WorkBuddyConfig,
    WorkBuddyError,
    discover_command,
    stream_workbuddy,
)
from runtime.memory.a2a_inbound_task_store import A2ASqliteTaskStore
from runtime.platform.io import atomic_write_json

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:\-]{0,127}\Z")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _files(workspace: Path) -> dict[str, tuple[int, int]]:
    result = {}
    for file in workspace.rglob("*"):
        relative = file.relative_to(workspace)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if file.is_symlink() or not file.resolve().is_relative_to(workspace.resolve()):
            continue
        if file.is_file():
            info = file.stat()
            result[relative.as_posix()] = (info.st_mtime_ns, info.st_size)
    return result


class WorkBuddyExecutor(AgentExecutor):
    def __init__(self, config: WorkBuddyConfig, *, label: str = "WorkBuddy", runner=None) -> None:
        self.config = config
        self.label = label
        self.runner = runner or stream_workbuddy
        self.running: dict[str, asyncio.Task] = {}
        self.context_locks: dict[str, asyncio.Lock] = {}
        self.slots = asyncio.Semaphore(2)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = str(context.task_id), str(context.context_id)
        updater = TaskUpdater(event_queue, task_id, context_id)
        task = Task(id=task_id, context_id=context_id)
        if context.message is not None:
            task.history.append(context.message)
        task.status.state = TaskState.TASK_STATE_SUBMITTED
        task.status.timestamp.GetCurrentTime()
        await event_queue.enqueue_event(Task.FromString(task.SerializeToString()))
        current = asyncio.current_task()
        assert current is not None
        self.running[task_id] = current
        pulse = None
        try:
            prompt = context.get_user_input().strip()
            if not prompt or len(prompt) > 100_000:
                raise WorkBuddyError("请提供 1–100000 字符的任务文本。")
            # Caller context IDs are opaque identifiers, never filesystem paths
            # or native WorkBuddy session IDs.
            key = hashlib.sha256(context_id.encode()).hexdigest()
            lock = self.context_locks.setdefault(key, asyncio.Lock())
            async with lock, self.slots:
                await updater.start_work(
                    updater.new_agent_message([Part(text=f"{self.label} 正在执行任务。")])
                )

                async def heartbeat():
                    while True:
                        await asyncio.sleep(3)
                        await updater.start_work()

                pulse = asyncio.create_task(heartbeat())
                await self._run(prompt, key, task, updater)
        except asyncio.CancelledError:
            await updater.cancel(
                updater.new_agent_message([Part(text=f"{self.label} 任务已停止。")])
            )
        except WorkBuddyError as exc:
            await updater.failed(updater.new_agent_message([Part(text=str(exc))]))
        except Exception:
            # Native events, credentials, and local tracebacks must not leak.
            await updater.failed(
                updater.new_agent_message(
                    [Part(text=f"{self.label} 桥接执行失败，请检查本机 CLI 和工作目录。")]
                )
            )
        finally:
            if pulse is not None:
                pulse.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pulse
            self.running.pop(task_id, None)

    async def _run(
        self,
        prompt: str,
        key: str,
        task: Task,
        updater: TaskUpdater,
    ) -> None:
        root = self.config.data_dir / "contexts" / key
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        session_file = root / "session.json"
        resume = None
        if session_file.exists():
            value = json.loads(session_file.read_text(encoding="utf-8"))
            candidate = value.get("session_id", "")
            if isinstance(candidate, str) and _SESSION_ID.fullmatch(candidate):
                resume = candidate
        before = _files(workspace)
        result = None
        session_id = None
        text = ""
        # Coalesce partial text to avoid an unbounded number of SQLite events.
        published_length = 0
        async with contextlib.aclosing(
            self.runner(
                self.config,
                prompt=prompt,
                workspace=workspace,
                resume=resume,
            )
        ) as events:
            async for event in events:
                if event.get("type") == "system" and event.get("subtype") == "init":
                    candidate = event.get("session_id", "")
                    if isinstance(candidate, str) and _SESSION_ID.fullmatch(candidate):
                        session_id = candidate
                        atomic_write_json(session_file, {"session_id": session_id})
                elif event.get("type") == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text += str(delta.get("text") or "")
                        if len(text) - published_length >= 300:
                            await updater.start_work(
                                updater.new_agent_message([Part(text=text[-4000:])])
                            )
                            published_length = len(text)
                elif event.get("type") == "assistant":
                    blocks = (event.get("message") or {}).get("content") or []
                    for block in blocks:
                        if block.get("type") == "tool_use":
                            name = str(block.get("name") or "tool")[:100]
                            await updater.start_work(
                                updater.new_agent_message(
                                    [Part(text=f"{self.label} 正在调用 {name}。")]
                                )
                            )
                elif event.get("type") == "result":
                    result = event
        if result is None:
            raise WorkBuddyError(f"{self.label} 未返回完整结果。")
        if result.get("is_error") or result.get("subtype") != "success":
            raise WorkBuddyError(f"{self.label} 未完成任务，请检查登录、额度或执行权限后重试。")
        answer = str(result.get("result") or text).strip()
        if not answer:
            raise WorkBuddyError(f"{self.label} 返回了空结果。")
        reply = updater.new_agent_message([Part(text=answer)])
        task.history.append(reply)
        task.status.state = TaskState.TASK_STATE_COMPLETED
        task.status.message.CopyFrom(reply)
        task.status.timestamp.GetCurrentTime()
        task.artifacts.add(
            artifact_id="answer", name=f"{self.label} 回复", parts=[Part(text=answer)]
        )
        # Export only new/changed files in this dedicated role workspace, with
        # a bounded payload. Raw bytes travel via A2A; no arbitrary file server.
        total = 0
        omitted = []
        for relative, signature in _files(workspace).items():
            if before.get(relative) == signature:
                continue
            if total + signature[1] > 8 * 1024 * 1024 or len(task.artifacts) >= 17:
                omitted.append(relative)
                continue
            file = workspace / relative
            if not file.resolve().is_relative_to(workspace.resolve()) or file.is_symlink():
                continue
            payload = file.read_bytes()
            if total + len(payload) > 8 * 1024 * 1024:
                omitted.append(relative)
                continue
            total += len(payload)
            task.artifacts.add(
                artifact_id=hashlib.sha256(relative.encode()).hexdigest()[:24],
                name=relative,
                parts=[
                    Part(
                        raw=payload,
                        filename=relative,
                        media_type=mimetypes.guess_type(relative)[0] or "application/octet-stream",
                    )
                ],
            )
        task.metadata.update(
            {
                "executor": self.label.lower(),
                "workspace": str(workspace),
                "billing": "official_cli_account_not_verified",
                "omitted_files": omitted,
                "permission_denials": len(result.get("permission_denials") or []),
            }
        )
        for artifact in task.artifacts:
            await updater.add_artifact(
                parts=list(artifact.parts),
                artifact_id=artifact.artifact_id,
                name=artifact.name,
                last_chunk=True,
            )
        await updater.start_work(reply)
        await updater.update_status(
            TaskState.TASK_STATE_COMPLETED, message=reply, metadata=dict(task.metadata)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        running = self.running.get(str(context.task_id))
        if running is not None:
            if not running.cancelling():
                running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running
        # The cancel request can have a separate event queue. Publish its own
        # snapshot after the subprocess has actually stopped.
        task = Task(id=str(context.task_id), context_id=str(context.context_id))
        if context.current_task is not None:
            task.CopyFrom(context.current_task)
        task.status.state = TaskState.TASK_STATE_CANCELED
        task.status.timestamp.GetCurrentTime()
        await event_queue.enqueue_event(task)


def create_app(
    config: WorkBuddyConfig,
    *,
    public_url: str = "http://127.0.0.1:8321",
    executor: WorkBuddyExecutor | None = None,
    label: str = "WorkBuddy",
    path_prefix: str = "",
) -> FastAPI:
    parsed = urlsplit(public_url)
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK or parsed.path not in {"", "/"}:
        raise ValueError(
            "WorkBuddy bridge requires a loopback HTTP URL; use an SSH tunnel for remote hosts"
        )
    app = FastAPI(title="Echo WorkBuddy Remote Role")

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any):
        # Echo calls server-to-server. Reject browser origins and DNS rebinding.
        if request.headers.get("origin") or request.url.hostname not in _LOOPBACK:
            return JSONResponse({"detail": "Local server-to-server access only"}, status_code=403)
        return await call_next(request)

    executor = executor or WorkBuddyExecutor(config)
    card = AgentCard(
        name=label,
        description=f"{label} 远程角色：执行委派任务，返回进度、回复与文件产物。",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                url=public_url.rstrip("/") + path_prefix + "/a2a/rpc",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/octet-stream"],
        skills=[
            AgentSkill(
                id=label.lower() + "-task",
                name=label + " 任务执行",
                description="通过官方 CLI 执行独立任务；支持同一上下文继续对话。",
                tags=[label.lower(), "research", "writing", "coding"],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=A2ASqliteTaskStore(config.data_dir / "a2a"),
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a/rpc", enable_v0_3_compat=True),
    )
    app.state.workbuddy_executor = executor
    app.state.a2a_handler = handler
    app.router.add_event_handler("shutdown", handler.aclose)

    @app.get("/health")
    def health():
        return {
            "status": "ready",
            "role": label.lower(),
            "authentication": "verified_on_task",
            "permission_mode": config.permission_mode,
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8321)
    parser.add_argument("--cli", help="Path to codebuddy.js or native CLI executable")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".octopus/workbuddy-bridge")
    parser.add_argument("--model", default="auto")
    parser.add_argument(
        "--permission-mode", choices=["default", "acceptEdits", "plan"], default="default"
    )
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register the running local bridge in Echo, then exit",
    )
    args = parser.parse_args()
    if args.register:
        print(asyncio.run(register_local_role(args.port)))
        return
    config = WorkBuddyConfig(
        command=discover_command(args.cli),
        data_dir=args.data_dir.resolve(),
        model=args.model,
        permission_mode=args.permission_mode,
        timeout=args.timeout,
        max_turns=args.max_turns,
    )
    import uvicorn

    uvicorn.run(
        create_app(config, public_url=f"http://127.0.0.1:{args.port}"),
        host="127.0.0.1",
        port=args.port,
    )


async def register_local_role(port: int = 8321) -> str:
    """Register a running bridge in the existing local Echo role directory."""
    from runtime.sensing.gateway import a2a_router

    url = f"http://127.0.0.1:{port}"
    card = await a2a_router._resolve_agent_card(url)
    if card.get("name") != "WorkBuddy":
        raise WorkBuddyError("目标地址不是 WorkBuddy 桥接服务。")
    now = datetime.now(UTC).isoformat()
    with a2a_router._lock:
        registry = a2a_router._load_registry()
        entry = next((item for item in registry["agents"] if item.get("base_url") == url), None)
        if entry is None:
            entry = {
                "agent_id": f"a2a_{uuid.uuid4().hex[:12]}",
                "base_url": url,
                "registered_at": now,
            }
            registry["agents"].append(entry)
        entry.update({**card, "status": "active", "updated_at": now, "last_health_check": now})
        a2a_router._save_registry(registry["agents"])
    return f"WorkBuddy: {entry['agent_id']} ({url})"


if __name__ == "__main__":
    main()
