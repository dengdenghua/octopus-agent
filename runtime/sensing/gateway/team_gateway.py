"""Standalone Echo team gateway. Run with python -m ...team_gateway."""

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import json
import re
import uuid
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .codex_hotspot import bounded_body, owner_token
from .hotspot_discovery import normalize_hotspot_url
from .team_store import TeamStore

ROOT = Path.home() / ".octopus" / "team-gateway"


class ModelConfig(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str
    api_key: str = Field(default="", max_length=4096)
    upstream_model: str = Field(min_length=1, max_length=200)
    wire_api: str = "chat_completions"


class Invitation(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    hours: int = Field(default=24, ge=1, le=168)
    max_requests: int = Field(default=100, ge=1, le=10000)
    models: list[str] = Field(min_length=1, max_length=100)
    concurrency: int = Field(default=2, ge=1, le=8)


def create_team_gateway(root=ROOT, *, transport=None):
    store = TeamStore(root)
    admin_key = owner_token(root)
    app = FastAPI(title="Echo Team Gateway", docs_url=None, redoc_url=None)
    app.state.store = store
    active = {}  # request id -> (member id, upstream task)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def admin(request: Request):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + admin_key):
            raise HTTPException(401, "需要网关管理员凭证")

    def member(request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(401, "需要成员凭证")
        grant = store.authorize(auth[7:])
        store.access(grant["id"])
        return grant, auth[7:]

    @app.get("/health")
    def health():
        return {"service": "echo-team-gateway"}

    @app.get("/admin/status", dependencies=[Depends(admin)])
    def status():
        return {
            "enabled": store.enabled(),
            "models": store.models(),
            "members": store.members(),
            "usage": store.usage(),
        }

    @app.put("/admin/models/{model_id}", dependencies=[Depends(admin)])
    def save(model_id: str, body: ModelConfig):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", model_id):
            raise HTTPException(400, "模型标识只能包含字母、数字、下划线和短横线")
        config = body.model_dump()
        config["base_url"] = normalize_hotspot_url(body.base_url)
        if body.wire_api not in {"responses", "chat_completions"}:
            raise HTTPException(400, "不支持的接口协议")
        if not body.api_key:
            previous = next((m for m in store.models(private=True) if m["id"] == model_id), {})
            config["api_key"] = previous.get("api_key", "")
        if not config["api_key"] or any(not 33 <= ord(c) <= 126 for c in config["api_key"]):
            raise HTTPException(400, "请填写有效的上游 Key 或热点凭证")
        store.save_model(model_id, config)
        return {"ok": True, "published": False}

    def endpoint(model):
        return model["base_url"] + (
            "/responses" if model["wire_api"] == "responses" else "/chat/completions"
        )

    @app.post("/admin/models/{model_id}/publish", dependencies=[Depends(admin)])
    async def publish(model_id: str):
        model = store.model(model_id)
        if model["wire_api"] == "responses":
            body = {
                "model": model["upstream_model"],
                "input": [{"role": "user", "content": "Reply with OK."}],
                "instructions": "",
                "stream": True,
                "store": False,
            }
        else:
            body = {
                "model": model["upstream_model"],
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "stream": False,
                "max_tokens": 16,
            }
        try:
            async with (
                httpx.AsyncClient(timeout=45, trust_env=False, transport=transport) as client,
                client.stream(
                    "POST",
                    endpoint(model),
                    json=body,
                    headers={"Authorization": "Bearer " + model["api_key"]},
                ) as response,
            ):
                if response.status_code != 200:
                    raise HTTPException(502, f"上游测试失败（HTTP {response.status_code}），未发布")
                data = bytearray()
                async with asyncio.timeout(45):
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 1024 * 1024:
                            raise HTTPException(502, "上游测试响应过大，未发布")
            if model["wire_api"] == "responses":
                events = [
                    json.loads(line[5:])
                    for line in data.decode().splitlines()
                    if line.startswith("data:") and line[5:].strip() != "[DONE]"
                ]
                valid = all(isinstance(e, dict) for e in events) and any(
                    e.get("type") == "response.completed"
                    and isinstance(e.get("response"), dict)
                    and e["response"].get("status") == "completed"
                    for e in events
                )
                valid = valid and not any(
                    e.get("type") in {"error", "response.failed", "response.incomplete"}
                    for e in events
                )
            else:
                payload = json.loads(data)
                choices = payload.get("choices") if isinstance(payload, dict) else None
                valid = (
                    isinstance(choices, list)
                    and bool(choices)
                    and all(
                        isinstance(choice, dict) and isinstance(choice.get("message"), dict)
                        for choice in choices
                    )
                    and not payload.get("error")
                )
            if not valid:
                raise HTTPException(502, "上游没有返回完整模型响应，未发布")
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise HTTPException(502, "连接测试失败，未发布；请检查地址、凭证和协议") from None
        store.publish(model_id, model["version"])
        return {"ok": True, "published": True}

    @app.post("/admin/models/{model_id}/pause", dependencies=[Depends(admin)])
    def pause(model_id: str):
        store.pause(model_id)
        return {"ok": True}

    @app.post("/admin/enabled", dependencies=[Depends(admin)])
    async def enabled(body: dict):
        if type(body.get("enabled")) is not bool:
            raise HTTPException(400, "enabled 必须为布尔值")
        store.set_enabled(body["enabled"])
        if not body["enabled"]:
            for _, task in list(active.values()):
                task.cancel()
        return {"enabled": store.enabled()}

    @app.post("/admin/invitations", dependencies=[Depends(admin)])
    def invite(body: Invitation):
        return store.invitation(**body.model_dump())

    @app.delete("/admin/members/{member_id}", dependencies=[Depends(admin)])
    async def revoke(member_id: str):
        store.revoke(member_id)
        for mid, task in list(active.values()):
            if mid == member_id:
                task.cancel()
        return {"ok": True}

    @app.post("/join")
    async def join(request: Request):
        body = await bounded_body(request)
        code = body.get("code", "")
        if not isinstance(code, str) or not 20 <= len(code) <= 200:
            raise HTTPException(400, "邀请兑换码格式无效")
        exchange_key = body.get("exchange_key", "")
        if not isinstance(exchange_key, str) or (
            exchange_key and not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", exchange_key)
        ):
            raise HTTPException(400, "兑换恢复凭证格式无效")
        result = store.exchange(code, exchange_key)
        return {**result, "models": store.catalog(result["member_id"])}

    @app.get("/v1/models")
    def catalog(request: Request):
        grant, _ = member(request)
        return {"object": "list", "data": store.catalog(grant["id"])}

    async def proxy(request: Request, protocol):
        body = await bounded_body(request)
        grant, token = member(request)
        selected = body.get("model")
        if not isinstance(selected, str):
            raise HTTPException(403, "模型未发布或未授权")
        model = store.permitted_model(grant["id"], selected)
        if model["wire_api"] != protocol:
            raise HTTPException(400, "请求协议与模型不一致")
        if protocol == "responses":
            if any(body.get(k) for k in ("previous_response_id", "conversation", "background")):
                raise HTTPException(400, "团队代理需要完整输入历史，不支持上游持久会话")
            body["store"] = False

            def has_reference(value):
                if isinstance(value, dict):
                    return (
                        "file_id" in value
                        or value.get("type") == "item_reference"
                        or any(has_reference(v) for v in value.values())
                    )
                return isinstance(value, list) and any(has_reference(v) for v in value)

            if has_reference(body):
                raise HTTPException(400, "不能引用上游账号存储的文件或会话项目")
        streaming = body.get("stream", False)
        if type(streaming) is not bool:
            raise HTTPException(400, "stream 必须为布尔值")
        _, limit = store.access(grant["id"])
        if len(active) >= 16 or sum(mid == grant["id"] for mid, _ in active.values()) >= limit:
            raise HTTPException(429, "并发请求已达上限，请稍后重试")
        request_key = request.headers.get("idempotency-key", "")
        if len(request_key) > 200 or any(not 33 <= ord(c) <= 126 for c in request_key):
            raise HTTPException(400, "请求标识无效")
        store.authorize(
            token,
            reserve=True,
            request_key=request_key,
            body_digest=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
        )
        body["model"] = model["upstream_model"]
        call_id = uuid.uuid4().hex
        queue = asyncio.Queue(maxsize=8)
        ready = asyncio.get_running_loop().create_future()
        store.audit(call_id, grant["id"], selected, "running")

        async def produce():
            state = "failed"
            stream_error = None
            try:
                if not store.active(grant["id"]):
                    raise HTTPException(403, "成员访问已停止")
                async with asyncio.timeout(300):
                    async with httpx.AsyncClient(
                        timeout=60, trust_env=False, transport=transport
                    ) as client:
                        async with client.stream(
                            "POST",
                            endpoint(model),
                            json=body,
                            headers={"Authorization": "Bearer " + model["api_key"]},
                        ) as response:
                            if response.status_code != 200:
                                raise HTTPException(
                                    502, f"上游请求失败（HTTP {response.status_code}）"
                                )
                            ready.set_result(True)
                            total = 0
                            async for chunk in response.aiter_bytes():
                                if not store.active(grant["id"]):
                                    raise HTTPException(403, "成员访问已停止")
                                total += len(chunk)
                                if total > 16 * 1024 * 1024:
                                    raise HTTPException(502, "响应超过大小限制")
                                await queue.put(chunk)
                            state = "forwarded"
            except asyncio.CancelledError:
                state = "cancelled"
                if not ready.done():
                    ready.set_exception(HTTPException(503, "请求已取消"))
                raise
            except Exception as exc:
                if not ready.done():
                    ready.set_exception(
                        exc
                        if isinstance(exc, HTTPException)
                        else HTTPException(502, "上游连接失败")
                    )
                else:
                    stream_error = RuntimeError("team upstream stream interrupted")
            finally:
                store.audit(call_id, grant["id"], selected, state)
                active.pop(call_id, None)
            await queue.put(stream_error)

        task = asyncio.create_task(produce())
        active[call_id] = (grant["id"], task)
        try:
            while not ready.done():
                if await request.is_disconnected():
                    raise HTTPException(499, "客户端已断开")
                await asyncio.wait({ready}, timeout=0.1)
            await ready
        except BaseException:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise

        async def chunks():
            try:
                while True:
                    get = asyncio.create_task(queue.get())
                    try:
                        await asyncio.wait(
                            {get, task}, return_when=asyncio.FIRST_COMPLETED
                        )
                        # The queue reader can finish after wait's snapshot but
                        # before this coroutine resumes; inspect its live state.
                        if get.done():
                            chunk = get.result()
                            if isinstance(chunk, Exception):
                                raise chunk
                            if chunk is None:
                                break
                            yield chunk
                        elif queue.empty():
                            if task.cancelled():
                                raise RuntimeError("team request cancelled")
                            break
                    finally:
                        get.cancel()
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        return StreamingResponse(
            chunks(),
            media_type="text/event-stream" if streaming else "application/json",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        return await proxy(request, "chat_completions")

    @app.post("/v1/responses")
    async def responses(request: Request):
        return await proxy(request, "responses")

    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8333)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    uvicorn.run(create_team_gateway(args.root), host=args.host, port=args.port, access_log=False)
