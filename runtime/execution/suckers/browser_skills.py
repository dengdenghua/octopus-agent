from __future__ import annotations

import base64
import contextlib
import threading
from typing import Any

from .registry import Skill, SkillRegistry
from .testing import SkillExpect, SkillTestCase

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None  # type: ignore[assignment]


DEFAULT_TIMEOUT_MS = 10_000
MAX_TEXT_BYTES = 100_000
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024  # 10MB hard cap
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _has_agent_browser_session() -> bool:
    """Whether an agent turn can reuse the thread's persistent page."""
    if not PLAYWRIGHT_AVAILABLE:
        return False
    try:
        from runtime.platform.process.session import current_session

        return current_session() is not None
    except Exception:  # noqa: BLE001 - session support is optional
        return False


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _check_url_safe(url: str, allow_private: bool) -> str | None:
    if not url:
        return "missing url"
    from runtime.safety.auth.url_guard import check_url

    verdict = check_url(url, allow_private=allow_private)
    if not verdict.allow:
        return f"ssrf_blocked: {verdict.reason}"
    return None


# ═══════════════════════════════════════════════════════════
# browser_get
# ═══════════════════════════════════════════════════════════


def _browser_get(
    url: str = "",
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_ms: int = 0,
    max_bytes: int = MAX_TEXT_BYTES,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if page is None:
        if url:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}
        if not url:
            routed = _dispatch_higher_track("extract", {}, url="")
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}

    return _with_page(
        page,
        lambda current: _navigate_and_read(current, url, timeout_ms, wait_ms, max_bytes),
    )


def _navigate_and_read(
    page: Any, url: str, timeout_ms: int, wait_ms: int, max_bytes: int
) -> dict[str, Any]:
    resp = None
    if url:
        try:
            resp = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            return {"error": f"nav_error: {type(e).__name__}: {e}"}

    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)

    try:
        title = page.title()
        text = page.inner_text("body")
    except Exception as e:  # noqa: BLE001
        return {"error": f"read_error: {type(e).__name__}: {e}"}

    truncated = len(text) > max_bytes
    if truncated:
        text = text[:max_bytes]

    return {
        "url": page.url,
        "status_code": resp.status if resp else None,
        "title": title,
        "length": len(text),
        "truncated": truncated,
        "content": text,
        "frames": _child_frame_snapshots(page, max_bytes=max_bytes),
    }


def _child_frame_snapshots(page: Any, *, max_bytes: int) -> list[dict[str, Any]]:
    """Return readable evidence from child frames without failing the page read.

    ``body.innerText`` on the top page intentionally excludes iframe
    documents.  Browser tasks that must wait for an iframe confirmation would
    therefore have no observable success signal even though the UI completed.
    Keep this best-effort and bounded: cross-origin or detached frames may
    reject DOM access and should not make the whole browser observation fail.
    """

    frames_value = getattr(page, "frames", [])
    frames = frames_value() if callable(frames_value) else frames_value
    if not isinstance(frames, (list, tuple)):
        return []
    main_frame = getattr(page, "main_frame", None)
    snapshots: list[dict[str, Any]] = []
    remaining = max(0, int(max_bytes))
    for frame in frames:
        if frame is main_frame:
            continue
        try:
            frame_text = str(frame.inner_text("body") or "")
            frame_url = str(getattr(frame, "url", "") or "")
            frame_name = str(getattr(frame, "name", "") or "")
        except Exception:  # noqa: BLE001 - detached/cross-origin frame
            continue
        clipped = frame_text[:remaining]
        snapshots.append(
            {
                "url": frame_url,
                "name": frame_name,
                "content": clipped,
                "truncated": len(frame_text) > len(clipped),
            }
        )
        remaining = max(0, remaining - len(clipped))
        if remaining == 0:
            break
    return snapshots


# ═══════════════════════════════════════════════════════════
# browser_extract
# ═══════════════════════════════════════════════════════════


def _browser_extract(
    url: str = "",
    selector: str = "",
    *,
    attr: str | None = None,
    limit: int = 20,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_ms: int = 0,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not selector:
        return {"error": "missing selector", "items": []}
    if page is None:
        if url:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_"), "items": []}
        elif not _has_agent_browser_session():
            return {"error": "missing url", "items": []}

    return _with_page(
        page,
        lambda current: _extract_from_page(
            current,
            url,
            selector,
            attr,
            limit,
            timeout_ms,
            wait_ms,
        ),
    )


def _extract_from_page(
    page: Any,
    url: str,
    selector: str,
    attr: str | None,
    limit: int,
    timeout_ms: int,
    wait_ms: int,
) -> dict[str, Any]:
    if url:
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            return {"error": f"nav_error: {type(e).__name__}: {e}", "items": []}

    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)

    try:
        handles = page.query_selector_all(selector)
    except Exception as e:  # noqa: BLE001
        return {"error": f"selector_error: {type(e).__name__}: {e}", "items": []}

    items: list[str] = []
    for h in handles[:limit]:
        try:
            val = h.inner_text() if attr is None else h.get_attribute(attr) or ""
        except (AttributeError, RuntimeError):  # noqa: BLE001
            val = ""
        items.append(val)

    return {
        "url": page.url,
        "selector": selector,
        "attr": attr,
        "count": len(items),
        "items": items,
    }


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _higher_track_backends() -> list[Any]:
    """Non-Playwright browser tracks, highest priority first: the user's
    extension and the desktop Electron browser. Built fresh each call so
    availability is re-probed (the relay / bridge can come and go). A test
    seam — monkeypatch to inject fakes."""
    from runtime.execution.suckers.browser_backends import (
        ElectronBackend,
        ExtensionBackend,
    )

    return [ExtensionBackend(), ElectronBackend()]


def _requested_browser_track() -> Any:
    """Resolve the trusted per-turn browser track preference, if present."""

    try:
        from runtime.execution.suckers.browser_backend import Track
        from runtime.platform.process.session import current_session

        session = current_session()
        metadata = getattr(session, "metadata", None) if session is not None else None
        raw = str((metadata or {}).get("browser_track_preference") or "").strip().lower()
        return Track(raw) if raw else None
    except (AttributeError, TypeError, ValueError, ImportError):
        return None


def _annotate_browser_track_result(
    payload: Any,
    *,
    served_track: Any,
) -> dict[str, Any]:
    """Expose whether an explicit @Chrome/@Browser track preference held.

    Previously an extension disconnect silently moved an @Chrome action onto
    Electron or Playwright.  The operation could succeed in the wrong browser
    while the model reported that it acted on the signed-in Chrome tab.  This
    receipt makes the selected track and any fallback explicit to the model,
    UI, trajectory recorder, and final-answer guards.

    ``payload`` is ideally a dict (the common case for browser actions that
    return structured results). Non-dict payloads (raw strings, bools, None
    from void actions) are wrapped under a ``"result"`` key so the track
    metadata can still be attached without losing the original value.
    """

    served = str(getattr(served_track, "value", served_track) or "")
    requested_track = _requested_browser_track()
    requested = str(getattr(requested_track, "value", requested_track) or "")
    result = dict(payload) if isinstance(payload, dict) else {"result": payload}
    if served:
        result.setdefault("track", served)
    if not requested:
        return result
    result["browser_track_preference"] = requested
    result["browser_track_preference_satisfied"] = served == requested
    if served != requested:
        result["browser_track_fallback"] = {
            "requested": requested,
            "served": served,
            "reason": f"{requested}_unavailable",
        }
    return result


def _dispatch_higher_track(
    verb: str,
    payload: dict[str, Any],
    *,
    url: str = "",
) -> dict[str, Any] | None:
    """Run ``verb`` on the highest-priority AVAILABLE non-Playwright track
    (extension → Electron), preserving the PW skills' "navigate then act"
    semantics so a flow stays on ONE browser. Returns the track's result dict,
    or ``None`` when no higher track is available (caller falls back to
    headless Playwright)."""
    try:
        from runtime.execution.suckers.browser_backend import resolve_backend

        chosen = resolve_backend(
            _higher_track_backends(),
            prefer=_requested_browser_track(),
        )
    except Exception:  # noqa: BLE001 — backend layer optional
        return None
    if chosen is None:
        return None
    try:
        # Match the stateless PW skills: each call navigates first (except the
        # navigate verb itself), then acts — so we never split a flow between
        # the real browser and headless PW.
        if url and verb != "navigate":
            nav = chosen.navigate(url)
            if not nav.ok:
                return _browser_result_payload(nav)
        res = _call_browser_backend(chosen, verb, payload, fallback_url=url)
        result = _annotate_browser_track_result(
            _browser_result_payload(res),
            served_track=getattr(chosen, "track", ""),
        )
        if verb == "screenshot" and "error" not in result:
            return _materialize_higher_track_screenshot(result, payload)
        return result
    except Exception as e:  # noqa: BLE001
        return {"error": f"browser_error: {type(e).__name__}: {e}"}


def _call_browser_backend(
    backend: Any,
    verb: str,
    payload: dict[str, Any],
    *,
    fallback_url: str = "",
):
    if verb == "navigate":
        return backend.navigate(str(payload.get("url") or fallback_url))
    if verb == "click":
        return backend.click(str(payload.get("selector") or ""))
    if verb == "type":
        return backend.type(
            str(payload.get("selector") or ""),
            str(payload.get("text") or ""),
            clear=bool(payload.get("clear") or payload.get("clear_first")),
        )
    if verb == "scroll":
        delta_raw = payload.get("delta_y", payload.get("deltaY", 0))
        return backend.scroll(
            selector=payload.get("selector"),
            delta_y=int(delta_raw or 0),
        )
    if verb == "wait":
        timeout_raw = payload.get("timeout_ms", payload.get("timeout", 10_000))
        return backend.wait(
            str(payload.get("selector") or ""),
            timeout_ms=int(timeout_raw or 10_000),
        )
    if verb == "state":
        return backend.state(max_items=int(payload.get("max_items") or 30))
    if verb == "extract":
        return backend.extract()
    if verb == "screenshot":
        return backend.screenshot(
            str(payload.get("path") or ""),
            full_page=bool(payload.get("full_page")),
        )
    raise ValueError(f"unsupported browser backend verb: {verb}")


def _materialize_higher_track_screenshot(
    result: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    path = str(payload.get("path") or "").strip()
    if not path:
        return result
    raw_data = result.get("dataUrl") or result.get("data")
    if not isinstance(raw_data, str) or not raw_data.strip():
        return result
    data = raw_data.strip()
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(data)
    except (ValueError, TypeError):
        return result
    size = len(image_bytes)
    if size > MAX_SCREENSHOT_BYTES:
        return {
            "error": f"screenshot too large: {size} > {MAX_SCREENSHOT_BYTES}",
            "path": path,
        }
    from pathlib import Path as _P  # noqa: N814

    target = _P(path)
    with contextlib.suppress(OSError):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image_bytes)
    return {
        **result,
        "path": path,
        "size_bytes": size,
        "full_page": bool(payload.get("full_page")),
        "track": result.get("track", "extension"),
    }


def _find_matches_in_text(
    *,
    text: str,
    needle: str,
    url: str = "",
    title: str = "",
    case_sensitive: bool = False,
    max_results: int = 20,
    context_chars: int = 80,
) -> dict[str, Any]:
    haystack = text if case_sensitive else text.lower()
    target = needle if case_sensitive else needle.lower()
    matches: list[dict[str, Any]] = []
    start = 0
    while len(matches) < max_results:
        idx = haystack.find(target, start)
        if idx < 0:
            break
        left = max(0, idx - context_chars)
        right = min(len(text), idx + len(needle) + context_chars)
        matches.append(
            {
                "index": idx,
                "snippet": text[left:right].replace("\n", " ").strip(),
            }
        )
        start = idx + max(1, len(target))
    return {
        "url": url,
        "title": title,
        "text": needle,
        "count": len(matches),
        "truncated": len(matches) >= max_results,
        "matches": matches,
    }


def _browser_result_payload(result: Any) -> dict[str, Any]:
    raw = getattr(result, "raw", None)
    if isinstance(raw, dict):
        return raw
    ok = bool(getattr(result, "ok", False))
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return dict(data)
    if ok:
        return {}
    return {"error": str(getattr(result, "error", None) or "browser_error")}


def _with_page(
    page: Any,
    action: Any,
    *,
    launch_timeout_ms: int = DEFAULT_TIMEOUT_MS,
    verb: str | None = None,
    payload: dict[str, Any] | None = None,
    url: str = "",
) -> dict[str, Any]:
    if page is not None:
        from runtime.execution.suckers.browser_backend import Track

        return _annotate_browser_track_result(action(page), served_track=Track.PLAYWRIGHT)

    # Prefer the user's real browser (extension > desktop Electron) when one is
    # live; fall back to headless Playwright. Unavailable tracks (the common
    # case — no desktop app running) resolve to None, so the PW path below is
    # unchanged. Only verbs the higher tracks implement pass ``verb``.
    if verb is not None:
        routed = _dispatch_higher_track(verb, payload or {}, url=url)
        if routed is not None:
            return routed

    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "playwright not installed"}

    # Inside an agent session, reuse a persistent per-session page so multi-step
    # flows (navigate → click → type) share state. The page lives on a dedicated
    # worker thread (Playwright sync is thread-affine) and ``action`` runs there.
    # Outside a session (direct / unit-test calls) keep the original stateless
    # throwaway-browser behaviour — no surprise persistence, no regression.
    try:
        from runtime.platform.process.session import current_session

        sess = current_session()
    except Exception:  # noqa: BLE001 — session module optional
        sess = None
    if sess is not None:
        try:
            from runtime.execution.suckers.browser_session_worker import (
                get_browser_session_pool,
            )

            pool = get_browser_session_pool()
            key = f"thr:{getattr(sess, 'thread_id', None) or threading.get_ident()}"
            try:
                from runtime.execution.suckers.browser_backend import Track

                return _annotate_browser_track_result(
                    pool.get_or_create(key).submit(action),
                    served_track=Track.PLAYWRIGHT,
                )
            except RuntimeError:
                # The worker was closed (reaper eviction / timeout retirement)
                # between get_or_create and submit — one fresh retry resolves
                # the race (get_or_create makes a new worker for a closed key).
                from runtime.execution.suckers.browser_backend import Track

                return _annotate_browser_track_result(
                    pool.get_or_create(key).submit(action),
                    served_track=Track.PLAYWRIGHT,
                )
        except Exception as e:  # noqa: BLE001
            return {"error": f"browser_error: {type(e).__name__}: {e}"}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context()
                new_page = ctx.new_page()
                from runtime.execution.suckers.browser_backend import Track

                return _annotate_browser_track_result(
                    action(new_page),
                    served_track=Track.PLAYWRIGHT,
                )
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        return {"error": f"browser_error: {type(e).__name__}: {e}"}


def _browser_navigate(
    url: str = "",
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_ms: int = 0,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if page is None:
        err = _check_url_safe(url, allow_private)
        if err:
            return {"error": err, "blocked": err.startswith("ssrf_")}
    elif not url:
        return {"error": "missing url"}

    def _act(p: Any) -> dict[str, Any]:
        try:
            resp = p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            return {"error": f"nav_error: {type(e).__name__}: {e}"}
        if wait_ms > 0:
            p.wait_for_timeout(wait_ms)
        try:
            title = p.title()
        except (AttributeError, RuntimeError):  # noqa: BLE001
            title = ""
        return {
            "url": p.url,
            "status_code": resp.status if resp else None,
            "title": title,
        }

    return _with_page(page, _act, verb="navigate", payload={"url": url}, url=url)


def _browser_find(
    url: str = "",
    text: str = "",
    *,
    query: str | None = None,
    case_sensitive: bool = False,
    max_results: int = 20,
    context_chars: int = 80,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_ms: int = 0,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    needle = str(query if query is not None else text).strip()
    if not needle:
        return {"error": "missing text", "matches": []}
    max_results = max(1, min(int(max_results), 100))
    context_chars = max(20, min(int(context_chars), 500))
    if page is None:
        if not url:
            routed = _dispatch_higher_track("extract", {}, url="")
            if routed is not None:
                if "error" in routed:
                    return {**routed, "matches": []}
                text_value = routed.get("text") or routed.get("content") or ""
                return _find_matches_in_text(
                    text=str(text_value or ""),
                    needle=needle,
                    url=str(routed.get("url") or ""),
                    title=str(routed.get("title") or ""),
                    case_sensitive=case_sensitive,
                    max_results=max_results,
                    context_chars=context_chars,
                )
            if not _has_agent_browser_session():
                return {"error": "missing url", "matches": []}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_"), "matches": []}
            routed = _dispatch_higher_track("extract", {}, url=url)
            if routed is not None:
                if "error" in routed:
                    return {**routed, "matches": []}
                text_value = routed.get("text") or routed.get("content") or ""
                return _find_matches_in_text(
                    text=str(text_value or ""),
                    needle=needle,
                    url=str(routed.get("url") or url),
                    title=str(routed.get("title") or ""),
                    case_sensitive=case_sensitive,
                    max_results=max_results,
                    context_chars=context_chars,
                )

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}", "matches": []}
        if wait_ms > 0:
            p.wait_for_timeout(wait_ms)
        try:
            body_text = p.inner_text("body")
        except Exception as e:  # noqa: BLE001
            return {"error": f"read_error: {type(e).__name__}: {e}", "matches": []}

        return _find_matches_in_text(
            text=body_text,
            needle=needle,
            url=p.url,
            title=p.title(),
            case_sensitive=case_sensitive,
            max_results=max_results,
            context_chars=context_chars,
        )

    return _with_page(page, _act)


def _browser_state(
    url: str = "",
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_ms: int = 0,
    allow_private: bool = False,
    max_items: int = 30,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    max_items = max(1, min(int(max_items), 100))
    if page is None:
        if not url:
            routed = _dispatch_higher_track("state", {"max_items": max_items}, url="")
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        resp = None
        if url:
            try:
                resp = p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}"}
        if wait_ms > 0:
            p.wait_for_timeout(wait_ms)
        try:
            text = p.inner_text("body")
        except Exception:  # noqa: BLE001 — best-effort; fail-open
            text = ""
        try:
            from runtime.execution.suckers.browser_dom_js import (
                dom_snapshot_function_js,
            )

            snapshot = p.evaluate(dom_snapshot_function_js(), max_items)
        except Exception as e:  # noqa: BLE001
            return {"error": f"state_error: {type(e).__name__}: {e}"}
        return {
            "url": p.url,
            "status_code": resp.status if resp else None,
            "title": p.title(),
            "text_length": len(text),
            "frames": _child_frame_snapshots(p, max_bytes=MAX_TEXT_BYTES),
            **snapshot,
        }

    return _with_page(
        page,
        _act,
        verb="state",
        payload={"max_items": max_items},
        url=url,
    )


def _browser_click(
    url: str = "",
    selector: str = "",
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_after_ms: int = 0,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not selector:
        return {"error": "missing selector"}
    if page is None:
        if not url:
            routed = _dispatch_higher_track(
                "click",
                {"selector": selector},
                url="",
            )
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}"}
        try:
            p.click(selector, timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            return {"error": f"click_error: {type(e).__name__}: {e}"}
        if wait_after_ms > 0:
            p.wait_for_timeout(wait_after_ms)
        try:
            title = p.title()
        except (AttributeError, RuntimeError):  # noqa: BLE001
            title = ""
        return {
            "clicked": selector,
            "final_url": p.url,
            "title": title,
        }

    return _with_page(
        page,
        _act,
        verb="click",
        payload={"selector": selector},
        url=url,
    )


def _browser_type(
    url: str = "",
    selector: str = "",
    text: str = "",
    *,
    value: str | None = None,
    option_label: str | None = None,
    press_enter: bool = False,
    clear_first: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not selector:
        return {"error": "missing selector"}
    # Native tool-capable models commonly use DOM-oriented ``value`` for
    # inputs and ``option_label`` for selects.  Keep ``text`` canonical while
    # accepting both explicit schema aliases instead of silently filling an
    # empty string through ``**_kw``.
    text = text or option_label or value or ""
    if page is None:
        if not url:
            routed = _dispatch_higher_track(
                "type",
                {"selector": selector, "text": text, "clear": clear_first},
                url="",
            )
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}"}
        try:
            locator = p.locator(selector)
            try:
                tag_name = locator.evaluate("element => element.tagName")
            except AttributeError:
                # Lightweight/test backends may expose the older page-level
                # fill/press API without a full Locator implementation.
                if clear_first:
                    p.fill(selector, "", timeout=timeout_ms)
                p.fill(selector, text, timeout=timeout_ms)
                if press_enter:
                    p.press(selector, "Enter", timeout=timeout_ms)
                input_kind = "text"
            else:
                if str(tag_name).upper() == "SELECT":
                    # Keep one generic form-entry primitive while still handling
                    # native selects correctly. Prefer the visible label, then
                    # fall back to the value for machine-oriented forms.
                    try:
                        locator.select_option(label=text, timeout=timeout_ms)
                    except Exception:  # noqa: BLE001
                        locator.select_option(value=text, timeout=timeout_ms)
                    input_kind = "select"
                else:
                    if clear_first:
                        locator.fill("", timeout=timeout_ms)
                    locator.fill(text, timeout=timeout_ms)
                    input_kind = "text"
                if press_enter:
                    locator.press("Enter", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            return {"error": f"type_error: {type(e).__name__}: {e}"}
        return {
            "filled": selector,
            "text_len": len(text),
            "input_kind": input_kind,
            "pressed_enter": press_enter,
            "final_url": p.url,
        }

    return _with_page(
        page,
        _act,
        verb="type",
        payload={"selector": selector, "text": text, "clear": clear_first},
        url=url,
    )


def _browser_scroll(
    url: str = "",
    *,
    to_selector: str | None = None,
    to_y: int | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if (to_selector is None) == (to_y is None):
        return {"error": "provide exactly one of to_selector / to_y"}
    if page is None:
        if not url:
            payload: dict[str, Any] = {}
            if to_selector is not None:
                payload["selector"] = to_selector
            if to_y is not None:
                payload["delta_y"] = int(to_y)
            routed = _dispatch_higher_track("scroll", payload, url="")
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}"}
        try:
            if to_selector is not None:
                p.locator(to_selector).scroll_into_view_if_needed(
                    timeout=timeout_ms,
                )
                scrolled_to = {"selector": to_selector}
            else:
                p.evaluate(f"window.scrollTo(0, {int(to_y)})")
                scrolled_to = {"y": int(to_y)}
        except Exception as e:  # noqa: BLE001
            return {"error": f"scroll_error: {type(e).__name__}: {e}"}
        return {"scrolled_to": scrolled_to, "final_url": p.url}

    return _with_page(
        page,
        _act,
        verb="scroll",
        payload={
            "selector": to_selector,
            "delta_y": int(to_y) if to_y is not None else 0,
        },
        url=url,
    )


def _browser_upload(
    url: str = "",
    selector: str = "",
    path: str = "",
    *,
    sandbox_dir: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Set a file input from a path confined by the current workspace."""
    if not selector:
        return {"error": "missing selector"}
    if not path:
        return {"error": "missing path"}

    from pathlib import Path

    from runtime.safety.auth.path_guard import check_path

    verdict = check_path(path, sandbox_dir=sandbox_dir, must_exist=True)
    if not verdict.allow:
        return {"error": f"path_blocked: {verdict.reason}"}
    resolved = Path(verdict.resolved or path)
    try:
        if not resolved.is_file():
            return {"error": "upload path is not a file"}
        size = resolved.stat().st_size
    except OSError as exc:
        return {"error": f"upload_path_error: {type(exc).__name__}: {exc}"}
    if size > MAX_UPLOAD_BYTES:
        return {"error": f"upload too large: {size} > {MAX_UPLOAD_BYTES}"}

    if page is None:
        if not url:
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as exc:  # noqa: BLE001
                return {"error": f"nav_error: {type(exc).__name__}: {exc}"}
        try:
            p.locator(selector).set_input_files(str(resolved), timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"upload_error: {type(exc).__name__}: {exc}"}
        return {
            "uploaded": selector,
            "file_name": resolved.name,
            "size_bytes": size,
            "final_url": p.url,
        }

    return _with_page(
        page,
        _act,
    )


def _browser_wait(
    url: str = "",
    selector: str = "",
    *,
    state: str = "visible",  # visible / hidden / attached / detached
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not selector:
        return {"error": "missing selector"}
    if state not in {"visible", "hidden", "attached", "detached"}:
        return {"error": f"invalid state: {state!r}"}
    if page is None:
        if not url:
            routed = _dispatch_higher_track(
                "wait",
                {"selector": selector, "timeout": timeout_ms},
                url="",
            )
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}"}
        try:
            p.wait_for_selector(selector, state=state, timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            return {
                "error": f"wait_timeout: {type(e).__name__}: {e}",
                "timed_out": True,
                "selector": selector,
                "state": state,
            }
        return {"waited_for": selector, "state": state, "final_url": p.url}

    return _with_page(
        page,
        _act,
        verb="wait",
        payload={"selector": selector, "timeout": timeout_ms},
        url=url,
    )


def _browser_screenshot(
    url: str = "",
    path: str = "",
    *,
    full_page: bool = False,
    sandbox_dir: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_ms: int = 0,
    allow_private: bool = False,
    page: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}

    from runtime.safety.auth.path_guard import check_path

    verdict = check_path(path, sandbox_dir=sandbox_dir)
    if not verdict.allow:
        return {"error": f"path_blocked: {verdict.reason}"}
    resolved = verdict.resolved or path

    if page is None:
        if not url:
            routed = _dispatch_higher_track(
                "screenshot",
                {"path": str(resolved), "full_page": bool(full_page)},
                url="",
            )
            if routed is not None:
                return routed
            if not _has_agent_browser_session():
                return {"error": "missing url", "blocked": False}
        else:
            err = _check_url_safe(url, allow_private)
            if err:
                return {"error": err, "blocked": err.startswith("ssrf_")}

    def _act(p: Any) -> dict[str, Any]:
        if url:
            try:
                p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                return {"error": f"nav_error: {type(e).__name__}: {e}"}
        if wait_ms > 0:
            p.wait_for_timeout(wait_ms)
        try:
            p.screenshot(path=str(resolved), full_page=full_page)
        except Exception as e:  # noqa: BLE001
            return {"error": f"screenshot_error: {type(e).__name__}: {e}"}

        from pathlib import Path as _P  # noqa: N814

        size = 0
        with contextlib.suppress(OSError):
            size = _P(str(resolved)).stat().st_size
        if size > MAX_SCREENSHOT_BYTES:
            with contextlib.suppress(OSError):
                _P(str(resolved)).unlink()
            return {
                "error": f"screenshot too large: {size} > {MAX_SCREENSHOT_BYTES}",
                "path": str(resolved),
            }
        return {
            "path": str(resolved),
            "size_bytes": size,
            "full_page": full_page,
        }

    return _with_page(
        page,
        _act,
        verb="screenshot",
        payload={"path": str(resolved), "full_page": bool(full_page)},
        url=url,
    )


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


BROWSER_SKILL_NAMES = [
    "browser_get",
    "browser_extract",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_upload",
    "browser_scroll",
    "browser_wait",
    "browser_screenshot",
    "browser_find",
    "browser_state",
]


def register_browser_skills(
    registry: SkillRegistry,
    *,
    verify_tests: bool = True,
) -> int:
    if not PLAYWRIGHT_AVAILABLE:
        return 0

    def _register(skill: Skill) -> None:
        registry.register(skill, verify_tests=verify_tests)

    _register(
        Skill(
            name="browser_get",
            description=(
                "Read rendered title, body text, and child-frame text. Pass url to navigate "
                "first, or omit url to read the current persistent agent browser page; use "
                "wait_ms before reading delayed UI or iframe confirmations."
            ),
            affinity=["web", "browser", "io"],
            cost_profile="high",
            trusted_source="skill://public/browser_get",
            handler=_browser_get,
            tests=[
                SkillTestCase(
                    name="missing_url_returns_error",
                    tier="golden",
                    args={"url": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_extract",
            description=(
                "Extract CSS matches (text or attr). Pass url to navigate, or omit it to "
                "use the current persistent agent browser page."
            ),
            affinity=["web", "browser", "scrape"],
            cost_profile="high",
            trusted_source="skill://public/browser_extract",
            handler=_browser_extract,
            tests=[
                SkillTestCase(
                    name="missing_selector_returns_error",
                    tier="golden",
                    args={"url": "https://example.com", "selector": ""},
                    expect=SkillExpect(schema_keys=["error", "items"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_navigate",
            description=(
                "Navigate the persistent agent browser page to a URL and return final URL + status."
            ),
            affinity=["web", "browser", "nav"],
            cost_profile="high",
            trusted_source="skill://public/browser_navigate",
            handler=_browser_navigate,
            tests=[
                SkillTestCase(
                    name="missing_url_error",
                    tier="golden",
                    args={"url": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_click",
            description=(
                "Click a CSS selector on the current persistent page; url is optional and "
                "navigates first when supplied."
            ),
            affinity=["web", "browser", "interact"],
            cost_profile="high",
            trusted_source="skill://public/browser_click",
            handler=_browser_click,
            tests=[
                SkillTestCase(
                    name="missing_selector_error",
                    tier="golden",
                    args={"url": "https://example.com", "selector": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_type",
            description=(
                "Fill an input/contenteditable or choose a native select option by visible "
                "label/value on the current persistent page; url is optional and navigates "
                "first when supplied. Pass content as text (value and option_label are also "
                "accepted aliases)."
            ),
            affinity=["web", "browser", "interact"],
            cost_profile="high",
            trusted_source="skill://public/browser_type",
            handler=_browser_type,
            tests=[
                SkillTestCase(
                    name="missing_selector_error",
                    tier="golden",
                    args={
                        "url": "https://example.com",
                        "selector": "",
                        "text": "x",
                    },
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_upload",
            description=(
                "Upload a workspace file into a CSS-selected file input on the current "
                "persistent page. Pass selector and path; url is optional after navigation."
            ),
            affinity=["web", "browser", "interact", "read"],
            cost_profile="high",
            trusted_source="skill://public/browser_upload",
            handler=_browser_upload,
            tests=[
                SkillTestCase(
                    name="missing_path_error",
                    tier="golden",
                    args={"selector": "#file", "path": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_scroll",
            description="Navigate and scroll to element or Y coordinate.",
            affinity=["web", "browser", "interact"],
            cost_profile="high",
            trusted_source="skill://public/browser_scroll",
            handler=_browser_scroll,
            tests=[
                SkillTestCase(
                    name="missing_target_error",
                    tier="golden",
                    args={"url": "https://example.com"},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_wait",
            description=(
                "Wait on the current persistent page for a CSS selector state; url is optional."
            ),
            affinity=["web", "browser", "interact"],
            cost_profile="high",
            trusted_source="skill://public/browser_wait",
            handler=_browser_wait,
            tests=[
                SkillTestCase(
                    name="bad_state_error",
                    tier="golden",
                    args={
                        "url": "https://example.com",
                        "selector": "body",
                        "state": "floating",
                    },
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_screenshot",
            description="Navigate and save a page screenshot (path_guard enforced).",
            affinity=["web", "browser", "capture"],
            cost_profile="high",
            trusted_source="skill://public/browser_screenshot",
            handler=_browser_screenshot,
            tests=[
                SkillTestCase(
                    name="missing_path_error",
                    tier="golden",
                    args={"url": "https://example.com", "path": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_find",
            description="Navigate to a page and find text, returning match snippets.",
            affinity=["web", "browser", "find"],
            cost_profile="high",
            trusted_source="skill://public/browser_find",
            handler=_browser_find,
            tests=[
                SkillTestCase(
                    name="missing_text_error",
                    tier="golden",
                    args={"url": "https://example.com", "text": ""},
                    expect=SkillExpect(schema_keys=["error", "matches"]),
                ),
            ],
        )
    )
    _register(
        Skill(
            name="browser_state",
            description=(
                "Return persistent browser state (optionally navigate with url): title, URL, "
                "viewport, scroll, child-frame text, and visible links/buttons/inputs/headings."
            ),
            affinity=["web", "browser", "observe"],
            cost_profile="high",
            trusted_source="skill://public/browser_state",
            handler=_browser_state,
            tests=[
                SkillTestCase(
                    name="missing_url_error",
                    tier="golden",
                    args={"url": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    return 11
