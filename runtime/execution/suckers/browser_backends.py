"""Real BrowserBackend adapters over the three automation tracks.

Each adapter is a thin, uniform shell over an existing track:

* :class:`ElectronBackend` → ``browser_act_skills._bridge_call`` (the
  desktop webview bridge; already returns ``{"ok": ...}``).
* :class:`PlaywrightBackend` → the stateless ``browser_skills._browser_*``
  handlers, threaded with a remembered ``current_url`` so click/type/…
  act on the page the agent last navigated to.
* :class:`ExtensionBackend` → the relay command queue in
  ``browser_router`` (acts on the user's own live tab).

Every adapter takes an injectable transport so its mapping logic is
unit-testable with a stub — no Electron app, Playwright install, or
connected extension required. The defaults bind to the real track
functions, so wiring is a one-liner at the call site:
``ElectronBackend()`` / ``PlaywrightBackend()`` / ``ExtensionBackend()``.

End-to-end verification of the live tracks needs their runtimes and is
out of scope here; what's tested is that each adapter maps the seven
``BrowserBackend`` verbs to the correct track action and normalises the
result.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.execution.suckers.browser_backend import BrowserResult, Track

# A transport takes (action, payload) and returns the track's native
# response dict. This is exactly the shape of Electron's _bridge_call;
# the other two adapters wrap their tracks into the same shape.
Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


# ── Electron webview ─────────────────────────────────────────────


class ElectronBackend:
    track = Track.ELECTRON

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        available_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._transport = transport or self._default_transport
        self._available_probe = available_probe or self._default_available

    @staticmethod
    def _default_transport(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        from runtime.execution.suckers.browser_act_skills import _bridge_call

        return _bridge_call(action, payload)

    @staticmethod
    def _default_available() -> bool:
        from runtime.execution.suckers.browser_act_skills import _load_bridge

        return _load_bridge() is not None

    def available(self) -> bool:
        return bool(self._available_probe())

    def _call(self, action: str, payload: dict[str, Any]) -> BrowserResult:
        return BrowserResult.from_track(self.track, self._transport(action, payload))

    def navigate(self, url: str) -> BrowserResult:
        return self._call("navigate", {"url": url})

    def click(self, selector: str) -> BrowserResult:
        return self._call("click", {"selector": selector})

    def type(self, selector: str, text: str, *, clear: bool = False) -> BrowserResult:
        return self._call("type", {"selector": selector, "text": text, "clear": clear})

    def scroll(self, *, selector: str | None = None, delta_y: int = 0) -> BrowserResult:
        payload: dict[str, Any] = {}
        if selector:
            payload["selector"] = selector
        if delta_y:
            payload["deltaY"] = int(delta_y)
        return self._call("scroll", payload)

    def wait(self, selector: str, *, timeout_ms: int = 10_000) -> BrowserResult:
        return self._call("wait", {"selector": selector, "timeout": int(timeout_ms)})

    def state(self, *, max_items: int = 30) -> BrowserResult:
        # The live bridge derives state via injected JS; the bridge
        # exposes it under the same "state" action used elsewhere.
        return self._call("state", {"max_items": int(max_items)})

    def extract(self) -> BrowserResult:
        return self._call("extract", {})


# ── Playwright (headless, stateless per call) ────────────────────


class PlaywrightBackend:
    track = Track.PLAYWRIGHT

    def __init__(
        self,
        dispatch: Transport | None = None,
        *,
        available_probe: Callable[[], bool] | None = None,
        start_url: str = "about:blank",
    ) -> None:
        self._dispatch = dispatch or self._default_dispatch
        self._available_probe = available_probe or self._default_available
        self._current_url = start_url

    @staticmethod
    def _default_available() -> bool:
        try:
            from runtime.execution.suckers.browser_skills import PLAYWRIGHT_AVAILABLE

            return bool(PLAYWRIGHT_AVAILABLE)
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _default_dispatch(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Route each verb to its stateless browser_skills handler. The
        # handlers take a ``url`` (the page to operate on) plus their
        # own kwargs and return a payload dict (``error`` key on fail).
        from runtime.execution.suckers import browser_skills as bs

        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "navigate": bs._browser_navigate,
            "click": bs._browser_click,
            "type": bs._browser_type,
            "scroll": bs._browser_scroll,
            "wait": bs._browser_wait,
            "state": bs._browser_state,
            # extract() means "read the page's text". _browser_extract is
            # a CSS-selector scraper that REQUIRES a selector and errors
            # without one; _browser_get returns title + inner text, which
            # is what the BrowserBackend.extract contract wants.
            "extract": bs._browser_get,
        }
        handler = handlers.get(action)
        if handler is None:
            return {"error": f"unsupported action: {action}"}
        return handler(**payload)

    def available(self) -> bool:
        return bool(self._available_probe())

    def _call(self, action: str, payload: dict[str, Any]) -> BrowserResult:
        result = BrowserResult.from_track(self.track, self._dispatch(action, payload))
        # Keep current_url fresh from whatever the handler reports.
        if result.data:
            new_url = result.data.get("final_url") or result.data.get("url")
            if isinstance(new_url, str) and new_url:
                self._current_url = new_url
        return result

    def navigate(self, url: str) -> BrowserResult:
        self._current_url = url
        return self._call("navigate", {"url": url})

    def click(self, selector: str) -> BrowserResult:
        return self._call("click", {"url": self._current_url, "selector": selector})

    def type(self, selector: str, text: str, *, clear: bool = False) -> BrowserResult:
        return self._call(
            "type",
            {"url": self._current_url, "selector": selector, "text": text, "clear_first": clear},
        )

    def scroll(self, *, selector: str | None = None, delta_y: int = 0) -> BrowserResult:
        payload: dict[str, Any] = {"url": self._current_url}
        if selector:
            payload["to_selector"] = selector
        if delta_y:
            payload["to_y"] = int(delta_y)
        return self._call("scroll", payload)

    def wait(self, selector: str, *, timeout_ms: int = 10_000) -> BrowserResult:
        return self._call(
            "wait",
            {"url": self._current_url, "selector": selector, "timeout_ms": int(timeout_ms)},
        )

    def state(self, *, max_items: int = 30) -> BrowserResult:
        return self._call("state", {"url": self._current_url, "max_items": int(max_items)})

    def extract(self) -> BrowserResult:
        return self._call("extract", {"url": self._current_url})


# ── Extension relay (the user's own live browser) ────────────────


class ExtensionBackend:
    track = Track.EXTENSION

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        available_probe: Callable[[], bool] | None = None,
    ) -> None:
        # No default transport binds automatically: the relay needs the
        # running server's command queue, which is supplied at wiring
        # time. Without it the backend reports unavailable rather than
        # guessing — the resolver then skips it.
        self._transport = transport
        self._available_probe = available_probe

    def available(self) -> bool:
        if self._available_probe is not None:
            return bool(self._available_probe())
        return self._transport is not None

    def _call(self, action: str, payload: dict[str, Any]) -> BrowserResult:
        if self._transport is None:
            return BrowserResult.from_track(
                self.track, {"ok": False, "error": "extension relay not wired"}
            )
        return BrowserResult.from_track(self.track, self._transport(action, payload))

    def navigate(self, url: str) -> BrowserResult:
        return self._call("navigate", {"url": url})

    def click(self, selector: str) -> BrowserResult:
        return self._call("click", {"selector": selector})

    def type(self, selector: str, text: str, *, clear: bool = False) -> BrowserResult:
        return self._call("type", {"selector": selector, "text": text, "clear": clear})

    def scroll(self, *, selector: str | None = None, delta_y: int = 0) -> BrowserResult:
        payload: dict[str, Any] = {}
        if selector:
            payload["selector"] = selector
        if delta_y:
            payload["deltaY"] = int(delta_y)
        return self._call("scroll", payload)

    def wait(self, selector: str, *, timeout_ms: int = 10_000) -> BrowserResult:
        return self._call("wait", {"selector": selector, "timeout": int(timeout_ms)})

    def state(self, *, max_items: int = 30) -> BrowserResult:
        return self._call("state", {"max_items": int(max_items)})

    def extract(self) -> BrowserResult:
        return self._call("extract", {})


__all__ = ["ElectronBackend", "PlaywrightBackend", "ExtensionBackend"]
