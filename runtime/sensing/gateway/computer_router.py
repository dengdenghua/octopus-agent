"""Computer automation API.

The surface is intentionally split into observe -> preview -> execute.
Mouse and keyboard actions are high-risk, so the UI must first create a
short-lived preview token and then send that token back for execution.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from runtime.execution.suckers import computer_skills, computer_uia_skills

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]


_VALID_ACTIONS = {"click", "move", "type", "key", "wait"}
_PENDING_TTL_SECONDS = 90
_LEASE_TTL_SECONDS = 30
_DEFAULT_LEASE_OWNER_ID = "default-computer-operator"
_DEFAULT_LEASE_OWNER_LABEL = "Default operator"


def create_computer_router() -> APIRouter:
    router = APIRouter(prefix="/api/computer", tags=["computer"])
    pending: dict[str, dict[str, Any]] = {}
    lease: dict[str, Any] = {}
    screenshot_root = Path("data/computer_automation/screenshots").resolve()

    def _cleanup_pending() -> None:
        now = time.time()
        expired = [
            token
            for token, item in pending.items()
            if now - float(item.get("created_at") or 0) > _PENDING_TTL_SECONDS
        ]
        for token in expired:
            pending.pop(token, None)

    def _cleanup_lease(now: float | None = None) -> None:
        if not lease:
            return
        current = time.time() if now is None else now
        if float(lease.get("expires_at") or 0) <= current:
            lease.clear()

    def _lease_from_body(body: dict[str, Any] | None) -> dict[str, str]:
        body = body or {}
        owner_id = str(
            body.get("lease_owner_id")
            or body.get("owner_id")
            or body.get("project_id")
            or _DEFAULT_LEASE_OWNER_ID
        ).strip()
        owner_label = str(
            body.get("lease_owner_label")
            or body.get("owner_label")
            or body.get("project_label")
            or _DEFAULT_LEASE_OWNER_LABEL
        ).strip()
        return {
            "owner_id": owner_id[:120] or _DEFAULT_LEASE_OWNER_ID,
            "owner_label": owner_label[:120] or _DEFAULT_LEASE_OWNER_LABEL,
        }

    def _public_lease(now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        _cleanup_lease(current)
        if not lease:
            return {
                "held": False,
                "ttl_seconds": 0,
                "lease_ttl_seconds": _LEASE_TTL_SECONDS,
            }
        return {
            "held": True,
            "owner_id": lease.get("owner_id"),
            "owner_label": lease.get("owner_label"),
            "acquired_at": lease.get("acquired_at"),
            "updated_at": lease.get("updated_at"),
            "expires_at": lease.get("expires_at"),
            "ttl_seconds": max(0, int(round(float(lease["expires_at"]) - current))),
            "lease_ttl_seconds": _LEASE_TTL_SECONDS,
        }

    def _claim_lease(owner: dict[str, str]) -> dict[str, Any]:
        now = time.time()
        _cleanup_lease(now)
        owner_id = owner["owner_id"]
        if lease and lease.get("owner_id") != owner_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "computer lease is held by another operator",
                    "lease": _public_lease(now),
                },
            )
        acquired_at = float(lease.get("acquired_at") or now) if lease else now
        lease.update({
            "owner_id": owner_id,
            "owner_label": owner["owner_label"],
            "acquired_at": acquired_at,
            "updated_at": now,
            "expires_at": now + _LEASE_TTL_SECONDS,
        })
        return _public_lease(now)

    def _release_lease(owner: dict[str, str], *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        _cleanup_lease(now)
        if lease and not force and lease.get("owner_id") != owner["owner_id"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "computer lease is held by another operator",
                    "lease": _public_lease(now),
                },
            )
        lease.clear()
        return _public_lease(now)

    def _normalize_action(body: dict[str, Any]) -> dict[str, Any]:
        action = str(body.get("action") or "").strip().lower()
        if action not in _VALID_ACTIONS:
            raise HTTPException(400, f"unsupported action: {action or '<empty>'}")

        if action in {"click", "move"}:
            return {
                "action": action,
                "x": int(body.get("x", -1)),
                "y": int(body.get("y", -1)),
                "button": str(body.get("button") or "left"),
                "clicks": int(body.get("clicks") or 1),
                "duration": float(body.get("duration") or 0.0),
            }
        if action == "type":
            return {
                "action": "type",
                "text": str(body.get("text") or ""),
                "interval": float(body.get("interval") or 0.01),
            }
        if action == "key":
            keys = body.get("keys")
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split("+") if k.strip()]
            if not isinstance(keys, list):
                raise HTTPException(400, "keys must be a list or + separated string")
            return {"action": "key", "keys": keys}
        return {"action": "wait", "ms": int(body.get("ms") or 500)}

    def _risk_for(action: dict[str, Any]) -> dict[str, str]:
        kind = action["action"]
        if kind == "type":
            return {
                "level": "high",
                "reason": "will type text into the currently focused application",
            }
        if kind in {"click", "key"}:
            return {
                "level": "medium",
                "reason": "can trigger UI actions in the active application",
            }
        return {"level": "low", "reason": "does not submit data by itself"}

    def _execute(action: dict[str, Any]) -> dict[str, Any]:
        kind = action["action"]
        if kind == "click":
            return computer_skills._mouse_click(
                x=int(action["x"]),
                y=int(action["y"]),
                button=str(action.get("button") or "left"),
                clicks=int(action.get("clicks") or 1),
                duration=float(action.get("duration") or 0.0),
            )
        if kind == "move":
            return computer_skills._mouse_move(
                x=int(action["x"]),
                y=int(action["y"]),
                duration=float(action.get("duration") or 0.2),
            )
        if kind == "type":
            return computer_skills._keyboard_type(
                text=str(action.get("text") or ""),
                interval=float(action.get("interval") or 0.01),
            )
        if kind == "key":
            return computer_skills._keyboard_press(keys=action.get("keys"))
        if kind == "wait":
            ms = int(action.get("ms") or 0)
            if ms < 0 or ms > 60_000:
                return {"error": f"wait ms out of range: {ms}"}
            time.sleep(ms / 1000)
            return {"waited_ms": ms}
        return {"error": f"unsupported action: {kind}"}

    def _queue_preview(action: dict[str, Any], owner: dict[str, str]) -> dict[str, Any]:
        token = uuid.uuid4().hex
        risk = _risk_for(action)
        pending[token] = {
            "token": token,
            "action": action,
            "risk": risk,
            "created_at": time.time(),
            "lease_owner": owner,
        }
        return {
            "token": token,
            "action": action,
            "risk": risk,
            "expires_in_seconds": _PENDING_TTL_SECONDS,
            "lease_owner": owner,
        }

    def _goal_uia_queries(goal: str) -> list[str]:
        text = goal.strip()
        if not text:
            return []
        candidates: list[str] = []
        for match in re.finditer(r"[\"'“”‘’]([^\"'“”‘’]{1,60})[\"'“”‘’]", text):
            candidates.append(match.group(1))
        patterns = (
            r"(?:click|press|select|open)\s+(?:the\s+)?(.{1,60})",
            r"(?:点击|单击|按下|选择|打开)\s*([^,，。；;:：\n\r]{1,40})",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                candidates.append(match.group(1))
        if (
            not candidates
            and len(text) <= 40
            and "http://" not in text
            and "https://" not in text
        ):
            candidates.append(text)

        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            item = candidate.strip(" \t\r\n'\"“”‘’()[]{}<>:：,，.。;；")
            item = re.sub(
                r"\b(button|control|field|link|menu)\b",
                "",
                item,
                flags=re.IGNORECASE,
            )
            item = item.replace("按钮", "").replace("控件", "").replace("菜单", "")
            item = " ".join(item.split()).strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                cleaned.append(item)
        return cleaned[:5]

    def _uia_actions_for_goal(goal: str) -> list[dict[str, Any]]:
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for query in _goal_uia_queries(goal):
            found = computer_uia_skills._computer_uia_find(
                query=query,
                max_results=5,
                max_depth=5,
                max_nodes=300,
            )
            if not found.get("ok"):
                continue
            for match in found.get("matches") or []:
                if not isinstance(match, dict):
                    continue
                if match.get("offscreen") or match.get("enabled") is False:
                    continue
                center = match.get("center")
                if not isinstance(center, dict):
                    continue
                try:
                    x = int(center["x"])
                    y = int(center["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                score = _uia_match_score(match, query)
                candidates.append((score, query, {
                    "action": "click",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clicks": 1,
                    "duration": 0.0,
                    "source": "uia",
                    "matched_control": {
                        "id": match.get("id"),
                        "name": match.get("name"),
                        "control_type": match.get("control_type"),
                        "class_name": match.get("class_name"),
                        "automation_id": match.get("automation_id"),
                        "center": center,
                        "rect": match.get("rect"),
                        "query": query,
                        "score": score,
                    },
                }))
        if not candidates:
            return []
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidates[0][2]]

    def _uia_match_score(match: dict[str, Any], query: str) -> int:
        needle = query.strip().lower()
        name = str(match.get("name") or "").strip().lower()
        automation_id = str(match.get("automation_id") or "").strip().lower()
        class_name = str(match.get("class_name") or "").strip().lower()
        control_type = str(match.get("control_type") or "").strip().lower()

        score = 0
        if bool(match.get("interactive")):
            score += 100
        if name == needle:
            score += 80
        elif name.startswith(needle):
            score += 60
        elif needle and needle in name:
            score += 40
        if automation_id == needle:
            score += 70
        elif needle and needle in automation_id:
            score += 35
        if needle and needle in class_name:
            score += 10
        if "button" in control_type or "menuitem" in control_type or "hyperlink" in control_type:
            score += 15
        if match.get("enabled") is not False:
            score += 5
        return score

    def _plan_actions(goal: str) -> list[dict[str, Any]]:
        text = goal.strip().lower()
        if not text:
            return []

        actions: list[dict[str, Any]] = []
        if "http://" in text or "https://" in text:
            url = goal.strip()
            for marker in ("http://", "https://"):
                idx = url.lower().find(marker)
                if idx >= 0:
                    url = url[idx:].split()[0]
                    break
            actions.extend([
                {"action": "key", "keys": ["ctrl", "l"]},
                {"action": "type", "text": url, "interval": 0.01},
                {"action": "key", "keys": ["enter"]},
            ])
        elif uia_actions := _uia_actions_for_goal(goal):
            actions.extend(uia_actions)
        elif any(word in text for word in ("browser", "chrome", "edge", "浏览器", "网页")):
            actions.extend([
                {"action": "key", "keys": ["win"]},
                {"action": "type", "text": "edge", "interval": 0.01},
                {"action": "key", "keys": ["enter"]},
            ])
        elif any(word in text for word in ("刷新", "reload", "refresh")):
            actions.append({"action": "key", "keys": ["ctrl", "r"]})
        elif any(word in text for word in ("关闭", "close")):
            actions.append({"action": "key", "keys": ["alt", "f4"]})
        else:
            actions.append({"action": "wait", "ms": 500})
        return actions[:5]

    def _extract_json_payload(text: str) -> Any:
        cleaned = text.strip()
        if not cleaned:
            raise HTTPException(400, "missing vision output")
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start_candidates = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx >= 0]
            if not start_candidates:
                raise HTTPException(400, "vision output does not contain JSON") from None
            start = min(start_candidates)
            end = max(cleaned.rfind("}"), cleaned.rfind("]"))
            if end <= start:
                raise HTTPException(400, "vision output JSON is incomplete") from None
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise HTTPException(400, f"invalid vision output JSON: {exc}") from None

    def _actions_from_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("actions"), list):
            raw_actions = payload["actions"]
        elif isinstance(payload, dict) and isinstance(payload.get("suggestions"), list):
            raw_actions = [
                item.get("action") if isinstance(item, dict) else item
                for item in payload["suggestions"]
            ]
        elif isinstance(payload, list):
            raw_actions = payload
        else:
            raw_actions = [payload]

        actions = []
        for raw in raw_actions[:5]:
            if not isinstance(raw, dict):
                continue
            normalized_input = dict(raw)
            if "action" not in normalized_input and "type" in normalized_input:
                normalized_input["action"] = normalized_input["type"]
            actions.append(_normalize_action(normalized_input))
        return actions

    def _load_custom_model(model_id: str) -> dict[str, Any] | None:
        if not model_id:
            return None
        path = Path("data/custom_models.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        entry = data.get(model_id)
        return entry if isinstance(entry, dict) else None

    def _vision_model_config(model_id: str) -> dict[str, Any] | None:
        import os

        selected = model_id or os.getenv("OCTOPUS_COMPUTER_VISION_MODEL", "")
        entry = _load_custom_model(selected)
        if entry:
            # Pick the first upstream model id from the new
            # ``models`` list, falling back to the legacy ``model``
            # field so pre-refactor entries keep working.
            upstream = ""
            raw_models = entry.get("models")
            if isinstance(raw_models, list):
                for m in raw_models:
                    if isinstance(m, str) and m.strip():
                        upstream = m.strip()
                        break
            if not upstream:
                legacy = entry.get("model")
                if isinstance(legacy, str) and legacy.strip():
                    upstream = legacy.strip()
            if not upstream:
                upstream = selected
            return {
                "id": selected,
                "provider": str(entry.get("provider") or "openai").lower(),
                "base_url": str(entry.get("base_url") or ""),
                "api_key": str(entry.get("api_key") or ""),
                "model": upstream,
                "default_headers": entry.get("default_headers") or {},
            }

        env_base = os.getenv("OCTOPUS_COMPUTER_VISION_BASE_URL", "")
        env_key = os.getenv("OCTOPUS_COMPUTER_VISION_API_KEY", "")
        env_model = selected or os.getenv("OCTOPUS_COMPUTER_VISION_UPSTREAM_MODEL", "")
        if env_base and env_model:
            return {
                "id": selected or env_model,
                "provider": "openai",
                "base_url": env_base,
                "api_key": env_key,
                "model": env_model,
                "default_headers": {},
            }
        return None

    def _call_openai_vision(
        *,
        config: dict[str, Any],
        goal: str,
        data_url: str,
    ) -> str:
        if not HTTPX_AVAILABLE or httpx is None:
            raise HTTPException(503, "httpx not installed")
        provider = str(config.get("provider") or "openai").lower()
        if provider not in {"openai", "openai-compatible", "custom"}:
            raise HTTPException(
                400,
                f"vision call currently supports openai-compatible models only, got {provider}",
            )
        base_url = str(config.get("base_url") or "").rstrip("/")
        model = str(config.get("model") or "")
        if not base_url or not model:
            raise HTTPException(400, "vision model base_url and model are required")
        headers = {
            "Content-Type": "application/json",
        }
        api_key = str(config.get("api_key") or "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        default_headers = config.get("default_headers") or {}
        if isinstance(default_headers, dict):
            headers.update({str(k): str(v) for k, v in default_headers.items()})

        prompt = (
            "You are a desktop UI grounding model. "
            "Inspect the screenshot and return only JSON. "
            "Schema: {\"actions\":[{\"action\":\"click\",\"x\":number,\"y\":number,"
            "\"button\":\"left\"}]} or type/key/wait actions. "
            "Coordinates must use the screenshot's native pixel coordinate system. "
            f"Task: {goal}"
        )
        payload = {
            "model": model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"vision upstream request failed: {exc}") from exc
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "vision upstream returned an error")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(502, "vision upstream returned non-JSON") from exc
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise HTTPException(502, "vision upstream returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            parts = [
                str(part.get("text"))
                for part in content
                if isinstance(part, dict) and part.get("type") in {None, "text"}
            ]
            content = "\n".join(parts)
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(502, "vision upstream returned empty content")
        return content

    @router.get("/status")
    def status() -> dict[str, Any]:
        _cleanup_pending()
        lease_state = _public_lease()
        info = computer_skills._screen_info()
        uia_status = computer_uia_skills._computer_uia_status()
        return {
            "ok": "error" not in info,
            "pyautogui_available": bool(computer_skills.PYAUTOGUI_AVAILABLE),
            "uia_available": bool(uia_status.get("available")),
            "uia": uia_status,
            "lease": lease_state,
            "screen": info,
            "skills": [
                "screen_capture",
                "screen_info",
                "mouse_click",
                "mouse_move",
                "keyboard_type",
                "keyboard_press",
                "computer_observe",
                "computer_plan_next",
                "computer_preview_action",
                "computer_execute_token",
                "computer_use_loop",
                "computer_uia_status",
                "computer_uia_tree",
                "computer_uia_find",
            ],
            "mode": "preview-confirm-execute-with-lease",
        }

    @router.post("/screenshot")
    def screenshot(body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        screenshot_root.mkdir(parents=True, exist_ok=True)
        shot_path = screenshot_root / f"{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        region = body.get("region")
        result = computer_skills._screen_capture(
            path=str(shot_path),
            sandbox_dir=str(screenshot_root),
            region=region if isinstance(region, list) else None,
        )
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        data = shot_path.read_bytes()
        return {
            "ok": True,
            "path": str(shot_path),
            "size_bytes": len(data),
            "data_url": "data:image/png;base64,"
            + base64.standard_b64encode(data).decode("ascii"),
            "created_at": time.time(),
        }

    @router.get("/uia/status")
    def uia_status() -> dict[str, Any]:
        return computer_uia_skills._computer_uia_status()

    @router.get("/uia/tree")
    def uia_tree(
        root: str = Query(default="foreground"),
        max_depth: int = Query(default=2, ge=0, le=8),
        max_nodes: int = Query(default=80, ge=1, le=1000),
        max_children: int = Query(default=30, ge=1, le=200),
        include_offscreen: bool = Query(default=False),
    ) -> dict[str, Any]:
        return computer_uia_skills._computer_uia_tree(
            root=root,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_children=max_children,
            include_offscreen=include_offscreen,
        )

    @router.get("/uia/find")
    def uia_find(
        query: str = Query(default=""),
        exact: bool = Query(default=False),
        root: str = Query(default="foreground"),
        max_results: int = Query(default=20, ge=1, le=100),
        max_depth: int = Query(default=5, ge=0, le=8),
        max_nodes: int = Query(default=300, ge=1, le=1000),
        include_offscreen: bool = Query(default=False),
    ) -> dict[str, Any]:
        return computer_uia_skills._computer_uia_find(
            query=query,
            exact=exact,
            root=root,
            max_results=max_results,
            max_depth=max_depth,
            max_nodes=max_nodes,
            include_offscreen=include_offscreen,
        )

    @router.post("/actions/preview")
    def preview_action(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        action = _normalize_action(body)
        preview = _queue_preview(action, owner)
        return {
            "ok": True,
            "lease": _public_lease(),
            **preview,
        }

    @router.post("/actions/plan")
    def plan_actions(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        goal = str(body.get("goal") or "")
        capture = bool(body.get("capture", True))
        screenshot_data: dict[str, Any] | None = None
        if capture:
            screenshot_data = screenshot({})

        suggestions = []
        for idx, action in enumerate(_plan_actions(goal), start=1):
            preview = _queue_preview(action, owner)
            suggestions.append({
                "id": f"step-{idx}",
                "title": f"Step {idx}: {action['action']}",
                "rationale": "Heuristic next action based on the task text and current screen observation.",
                **preview,
            })

        return {
            "ok": True,
            "goal": goal,
            "screenshot": screenshot_data,
            "suggestions": suggestions,
            "mode": "observe-plan-confirm",
            "lease": _public_lease(),
            "limitations": [
                "This first pass uses local heuristics and UIA semantic grounding when available.",
                "Visual screenshot grounding is only used by /actions/vision, not this local planner.",
                "Every suggested action still requires explicit user confirmation before execution.",
            ],
        }

    @router.post("/actions/ground")
    def ground_actions(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        goal = str(body.get("goal") or "")
        output = body.get("output")
        capture = bool(body.get("capture", True))
        screenshot_data: dict[str, Any] | None = None
        if capture:
            screenshot_data = screenshot({})

        if output is None:
            return {
                "ok": True,
                "goal": goal,
                "screenshot": screenshot_data,
                "suggestions": [],
                "mode": "vision-output-adapter",
                "lease": _public_lease(),
                "schema": {
                    "actions": [
                        {"action": "click", "x": 100, "y": 200, "button": "left"},
                        {"action": "type", "text": "hello"},
                        {"action": "key", "keys": ["enter"]},
                    ]
                },
                "limitations": [
                    "No vision model output was provided.",
                    "Paste a JSON action from any vision model to validate and queue it.",
                ],
            }

        payload = _extract_json_payload(output if isinstance(output, str) else json.dumps(output))
        actions = _actions_from_payload(payload)
        suggestions = []
        for idx, action in enumerate(actions, start=1):
            preview = _queue_preview(action, owner)
            suggestions.append({
                "id": f"vision-{idx}",
                "title": f"Vision {idx}: {action['action']}",
                "rationale": "Validated action parsed from vision model output.",
                **preview,
            })

        return {
            "ok": True,
            "goal": goal,
            "screenshot": screenshot_data,
            "suggestions": suggestions,
            "mode": "vision-output-adapter",
            "lease": _public_lease(),
            "limitations": [
                "This endpoint validates vision output but does not execute automatically.",
                "Every parsed action still requires explicit user confirmation.",
            ],
        }

    @router.post("/actions/vision")
    def vision_actions(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        goal = str(body.get("goal") or "")
        model_id = str(body.get("model_id") or "")
        config = _vision_model_config(model_id)
        screenshot_data = screenshot({})
        if not screenshot_data.get("ok"):
            return {
                "ok": False,
                "goal": goal,
                "screenshot": screenshot_data,
                "suggestions": [],
                "mode": "vision-model",
                "lease": _public_lease(),
                "error": screenshot_data.get("error") or "screenshot failed",
            }
        if not config:
            return {
                "ok": False,
                "goal": goal,
                "screenshot": screenshot_data,
                "suggestions": [],
                "mode": "vision-model",
                "lease": _public_lease(),
                "error": (
                    "vision model not configured · pass model_id for a custom openai-compatible "
                    "model or set OCTOPUS_COMPUTER_VISION_* env vars"
                ),
            }
        data_url = str(screenshot_data.get("data_url") or "")
        output = _call_openai_vision(config=config, goal=goal, data_url=data_url)
        payload = _extract_json_payload(output)
        actions = _actions_from_payload(payload)
        suggestions = []
        for idx, action in enumerate(actions, start=1):
            preview = _queue_preview(action, owner)
            suggestions.append({
                "id": f"vision-model-{idx}",
                "title": f"Vision model {idx}: {action['action']}",
                "rationale": "Grounded action returned by the configured vision model.",
                **preview,
            })
        return {
            "ok": True,
            "goal": goal,
            "model_id": str(config.get("id") or model_id),
            "screenshot": screenshot_data,
            "suggestions": suggestions,
            "mode": "vision-model",
            "lease": _public_lease(),
            "raw_output": output,
            "limitations": [
                "The screenshot is sent to the configured vision model provider.",
                "Returned actions are validated and require explicit user confirmation.",
            ],
        }

    @router.post("/actions/execute")
    def execute_action(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        token = str(body.get("token") or "")
        item = pending.pop(token, None)
        if not item:
            raise HTTPException(404, "preview token not found or expired")
        body_owner = _lease_from_body(body)
        item_owner = item.get("lease_owner")
        if isinstance(item_owner, dict):
            owner = {
                "owner_id": str(item_owner.get("owner_id") or body_owner["owner_id"]),
                "owner_label": str(item_owner.get("owner_label") or body_owner["owner_label"]),
            }
            if body.get("lease_owner_id") and body_owner["owner_id"] != owner["owner_id"]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "preview token belongs to another operator",
                        "lease_owner": owner,
                    },
                )
        else:
            owner = body_owner
        lease_state = _claim_lease(owner)
        action = item["action"]
        result = _execute(action)
        return {
            "ok": "error" not in result,
            "action": action,
            "risk": item["risk"],
            "result": result,
            "lease": lease_state,
            "executed_at": time.time(),
        }

    @router.post("/lease/release")
    def release_lease(body: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = _lease_from_body(body)
        force = bool((body or {}).get("force", False))
        return {
            "ok": True,
            "lease": _release_lease(owner, force=force),
        }

    return router
