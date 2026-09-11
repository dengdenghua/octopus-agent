"""Codex task and Responses hotspot. Loopback transport; remote access via SSH."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.execution.codex_backend.hotspot import (
    CodexRemoteConfig,
    SubscriptionAuth,
    stream_codex,
)
from runtime.sensing.gateway.hotspot_store import HotspotStore
from runtime.sensing.gateway.workbuddy_bridge import WorkBuddyExecutor
from runtime.sensing.gateway.workbuddy_bridge import create_app as role_app

ROOT = Path.home() / ".octopus" / "codex-hotspot"
UPSTREAM = "https://chatgpt.com/backend-api/codex/responses"
MAX_BODY = 2 * 1024 * 1024


def owner_token(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "owner.token"
    if not path.exists():
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_urlsafe(48))
    return path.read_text().strip()


async def bounded_body(request: Request):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_BODY:
            raise HTTPException(413, "请求过大")
    try:
        request._body = bytes(chunks)
        value = json.loads(chunks)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "请求必须是 JSON") from None
    if not isinstance(value, dict):
        raise HTTPException(400, "请求必须是 JSON 对象")
    return value


def create_hotspot(
    root: Path = ROOT,
    source_home: Path | None = None,
    port: int = 8322,
    *,
    auth=None,
    transport=None,
    task_runner=stream_codex,
):
    root = root.resolve()
    store = HotspotStore(root)
    secret = owner_token(root)
    auth = auth or SubscriptionAuth(
        source_home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    )
    app = FastAPI(title="Echo AI Hotspot")
    roles = {}
    active = set()
    slots = asyncio.Semaphore(2)

    async def check(request: Request, *, reserve=False, body_digest=""):
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        request_key = request.headers.get("idempotency-key", "") if body_digest else ""
        if request_key and (
            len(request_key) > 200
            or not request_key.isascii()
            or any(not 33 <= ord(c) <= 126 for c in request_key)
        ):
            raise HTTPException(400, "Idempotency-Key 必须为 1 到 200 个可见 ASCII 字符")
        return store.authorize(
            token, reserve=reserve, request_key=request_key, body_digest=body_digest
        )

    def ensure_role(member: str):
        if member not in roles:
            engine = store.task_engine(member)
            label = "OpenCode" if engine == "opencode" else "Codex"
            runner = task_runner
            cfg = CodexRemoteConfig(root / "members" / member, auth.home, auth)
            if engine == "opencode":
                from runtime.execution.opencode_hotspot import OpenCodeRemoteConfig, stream_opencode

                cfg = OpenCodeRemoteConfig(root / "members" / member)
                runner = stream_opencode

            class AuditedExecutor(WorkBuddyExecutor):
                async def _run(self, prompt, key, task, updater):
                    store.audit(task.id, member, "task", "running")
                    try:
                        await super()._run(prompt, key, task, updater)
                    except BaseException:
                        store.audit(task.id, member, "task", "failed_or_cancelled")
                        raise
                    else:
                        store.audit(task.id, member, "task", "completed")

            executor = AuditedExecutor(cfg, label=label, runner=runner)
            executor.slots = slots
            subapp = role_app(
                cfg,
                public_url=f"http://127.0.0.1:{port}",
                executor=executor,
                label=label,
                path_prefix=f"/members/{member}",
            )
            app.mount(f"/members/{member}", subapp)
            roles[member] = (subapp, executor)

    for member in store.list():
        ensure_role(member["id"])

    @app.middleware("http")
    async def access(request, call_next):
        # Browser requests and DNS rebinding are not a trusted local control plane.
        if request.headers.get("origin") or request.url.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            return JSONResponse({"detail": "Use a loopback SSH tunnel"}, status_code=403)
        try:
            path = request.url.path
            if path.startswith("/admin/"):
                if not hmac.compare_digest(
                    request.headers.get("authorization", ""), "Bearer " + secret
                ):
                    raise HTTPException(401, "需要热点所有者凭证")
            elif path.startswith("/members/"):
                member = await check(request)
                parts = path.split("/")
                if len(parts) < 3 or member["id"] != parts[2]:
                    raise HTTPException(403, "不能访问其他成员的任务")
                if request.method == "POST":
                    body = await bounded_body(request)
                    if body.get("method") in {
                        "message/send",
                        "message/stream",
                        "SendMessage",
                        "SendStreamingMessage",
                    }:
                        await check(request, reserve=True)
                ensure_role(member["id"])
            elif path != "/health":
                await check(request)
            return await call_next(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    def health():
        return {"service": "echo-codex-hotspot", "status": "ready"}

    @app.get("/admin/status")
    def status():
        return {
            "enabled": store.enabled(),
            "members": store.list(),
            "usage": store.usage(),
            "port": port,
            "modes": ["task", "responses"],
            "billing": "chatgpt_subscription",
            "task_engines": ["codex", "opencode"],
            "model_provider": "codex",
            "limit_unit": "requests",
            "max_concurrency": 2,
        }

    @app.post("/admin/enabled")
    async def enabled(request: Request):
        body = await bounded_body(request)
        value = body.get("enabled")
        if type(value) is not bool:
            raise HTTPException(400, "enabled 必须是布尔值")
        engine = body.get("task_engine", "codex")
        if engine not in {"codex", "opencode"}:
            raise HTTPException(400, "不支持的任务引擎")
        if value and engine == "opencode":
            from runtime.execution.opencode_backend import executable

            if not executable():
                raise HTTPException(409, "未找到本机 OpenCode 引擎")
        if value and engine == "codex":
            try:
                await auth.refresh(force=True)
                auth.headers()
            except Exception:
                raise HTTPException(409, "本机 Codex 套餐登录不可用，请重新登录。") from None
        store.set_enabled(value)
        return status()

    @app.post("/admin/members")
    async def invite(request: Request):
        body = await bounded_body(request)
        engine = body.get("task_engine", "codex")
        if engine not in {"codex", "opencode"}:
            raise HTTPException(400, "不支持的任务引擎")
        if engine == "opencode":
            from runtime.execution.opencode_backend import executable

            if not executable():
                raise HTTPException(409, "未找到本机 OpenCode 引擎")
        try:
            member = store.invite(
                str(body.get("label") or ""),
                int(body.get("hours", 8)),
                int(body.get("max_requests", 100)),
            )
        except (TypeError, ValueError):
            raise HTTPException(400, "邀请参数无效") from None
        store.set_task_engine(member["id"], engine)
        ensure_role(member["id"])
        return {
            "task_engine": engine,
            **member,
            "task_url": f"http://127.0.0.1:{port}/members/{member['id']}",
            "base_url": f"http://127.0.0.1:{port}/v1",
        }

    @app.delete("/admin/members/{member}")
    def revoke(member: str):
        store.revoke(member)
        return {"ok": True}

    @app.get("/v1/models")
    async def models():
        from runtime.execution.codex_backend.client import CodexAppServerClient
        from runtime.execution.codex_backend.command import resolve_codex_app_server_command
        from runtime.execution.codex_backend.types import CodexAppServerConfig

        try:
            async with CodexAppServerClient(
                CodexAppServerConfig(
                    command=resolve_codex_app_server_command(),
                    env_overrides={"CODEX_HOME": str(auth.home)},
                )
            ) as client:
                result = await client.list_models()
            return {
                "object": "list",
                "data": [
                    {"id": m["model"], "object": "model", "owned_by": "openai"}
                    for m in result.get("data", [])
                    if m.get("model")
                ],
            }
        except Exception:
            raise HTTPException(502, "无法读取本机 Codex 模型列表") from None

    @app.post("/v1/responses")
    async def responses(request: Request):
        body = await bounded_body(request)
        if not isinstance(body.get("model"), str) or not body.get("input"):
            raise HTTPException(400, "需要 model 和 input")
        if body.get("previous_response_id") or body.get("conversation") or body.get("background"):
            raise HTTPException(400, "请发送完整 input 历史；热点不支持服务端会话或后台响应")
        if body.get("stream", True) is not True:
            raise HTTPException(400, "模型热点当前需要 stream=true")
        tools = body.get("tools", [])
        if not isinstance(tools, list) or any(
            not isinstance(tool, dict) or tool.get("type") not in {"function", "custom"}
            for tool in tools
        ):
            raise HTTPException(400, "模型热点仅支持客户端执行的 function/custom 工具")
        inputs = body.get("input")
        if isinstance(inputs, list) and any(
            isinstance(item, dict)
            and (
                item.get("type") == "item_reference"
                or any(
                    isinstance(part, dict) and part.get("file_id")
                    for part in (
                        item.get("content") if isinstance(item.get("content"), list) else []
                    )
                )
            )
            for item in inputs
        ):
            raise HTTPException(400, "请提供完整输入，不能引用提供方账号的已存储项目或文件")
        if slots.locked():
            raise HTTPException(429, "热点并发已满，请稍后重试")
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        member = await check(request, reserve=True, body_digest=digest)
        body = {**body, "stream": True, "store": False}
        # OpenCode's Responses SDK always supplies this field. The subscription
        # endpoint rejects it; output limits are controlled by the upstream model.
        body.pop("max_output_tokens", None)
        body.setdefault("instructions", "")
        # No account selection, cookies, provider URL, or host tool execution
        # comes from the guest. Function/custom tool schemas remain wire data.
        for field in ("metadata", "user", "prompt_cache_key", "safety_identifier"):
            body.pop(field, None)
        call_id = uuid.uuid4().hex
        await slots.acquire()
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=15), transport=transport, trust_env=False
        )
        upstream = None
        connecting_task = asyncio.current_task()
        active.add((member["id"], connecting_task))
        try:
            if not store.active(member["id"]):
                raise HTTPException(401, "邀请已失效")
            await auth.refresh()
            headers = {
                **auth.headers(),
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "originator": "codex_cli_rs",
                "session_id": uuid.uuid4().hex,
            }
            upstream = await client.send(
                client.build_request("POST", UPSTREAM, json=body, headers=headers), stream=True
            )
            if upstream.status_code >= 400:
                status_code = upstream.status_code
                await upstream.aclose()
                await client.aclose()
                slots.release()
                store.audit(call_id, member["id"], "responses", f"upstream_{status_code}")
                # Never echo upstream bodies that could include account metadata.
                return JSONResponse(
                    {
                        "error": {
                            "message": "Codex 套餐拒绝请求，请检查登录、额度或模型支持。",
                            "type": "upstream_error",
                        }
                    },
                    status_code=status_code,
                )
            if (
                upstream.headers.get("content-type")
                and "text/event-stream" not in upstream.headers["content-type"]
            ):
                raise ValueError("upstream did not return SSE")
        except (Exception, asyncio.CancelledError) as exc:
            logging.getLogger(__name__).warning(
                "Codex upstream connection failed: %s", type(exc).__name__
            )
            if upstream is not None:
                await upstream.aclose()
            await client.aclose()
            slots.release()
            store.audit(
                call_id,
                member["id"],
                "responses",
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "connection_failed",
            )
            if isinstance(exc, (asyncio.CancelledError, HTTPException)):
                raise
            raise HTTPException(502, "Codex 套餐连接失败") from None
        finally:
            active.discard((member["id"], connecting_task))

        async def stream():
            state, usage = "disconnected", None
            task = asyncio.current_task()
            active.add((member["id"], task))
            store.audit(call_id, member["id"], "responses", "running")
            buffer = b""
            total = 0
            try:
                async with asyncio.timeout(300):
                    async for chunk in upstream.aiter_bytes():
                        if not store.active(member["id"]):
                            state = "revoked"
                            break
                        total += len(chunk)
                        if total > 16 * 1024 * 1024:
                            state = "response_too_large"
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if line.startswith(b"data: "):
                                try:
                                    event = json.loads(line[6:])
                                    if event.get("type") == "response.completed":
                                        state = "completed"
                                        usage = (event.get("response") or {}).get("usage")
                                    elif event.get("type") in {"error", "response.failed"}:
                                        state = "failed"
                                except (ValueError, TypeError):
                                    pass
                        yield chunk
            finally:
                active.discard((member["id"], task))
                await upstream.aclose()
                await client.aclose()
                slots.release()
                store.audit(call_id, member["id"], "responses", state, usage)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    async def watch():
        while True:
            await asyncio.sleep(0.25)
            for member, task in list(active):
                if not store.active(member):
                    task.cancel()
            for member, (_, executor) in list(roles.items()):
                if not store.active(member):
                    for task in list(executor.running.values()):
                        if not task.cancelling():
                            task.cancel()

    @app.on_event("startup")
    async def startup():
        app.state.watch = asyncio.create_task(watch())

    @app.on_event("shutdown")
    async def shutdown():
        app.state.watch.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.watch
        for _, task in list(active):
            task.cancel()
        for subapp, executor in roles.values():
            for task in list(executor.running.values()):
                task.cancel()
            await subapp.state.a2a_handler.aclose()

    app.state.store = store
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8322)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--codex-home", type=Path)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(
        create_hotspot(args.data_dir, args.codex_home, args.port),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
