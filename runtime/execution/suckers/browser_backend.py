"""Unified browser automation backend — the seam over three tracks.

Today browser automation lives in three parallel, partly-overlapping
implementations, and the agent picks one through scattered
``if window.octopus`` conditionals:

* **Playwright** (``browser_skills.py``) — headless, stateless, backend
  crawl/extract.
* **Electron webview** (``browser_act_skills.py``) — stateful, visible,
  driven over a local bridge inside the desktop app.
* **Extension relay** (``extensions/``) — acts on the user's own live
  browser tab; not yet wired into skills.

This module defines the contract all three should satisfy and a single
place to decide which one handles a call. It deliberately does NOT
rewrite the existing tracks — wrapping the live Playwright / Electron
code paths in real adapters needs a machine with those runtimes to
verify end-to-end. What lands here is the testable seam: the Protocol,
the priority resolver, and a Mock backend, so callers and tests can
target one interface now and the real adapters can slot in behind it
later without touching call sites.

Action results share the existing wire shape every track already
returns: ``{"ok": bool, ...}``. ``BrowserResult`` documents that shape
without forcing a migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

# The action vocabulary, intersection of what all three tracks expose.
# (Playwright ``browser_*`` and Electron ``live_browser_*`` already
# implement every verb here; the extension relay implements click/
# type/scroll/navigate.)
BrowserAction = str  # one of the _ACTIONS members below


class Track(StrEnum):
    """Which automation implementation served (or should serve) a call."""

    EXTENSION = "extension"
    ELECTRON = "electron"
    PLAYWRIGHT = "playwright"
    MOCK = "mock"


# Routing priority, highest first. The user's own live browser wins
# (the extension acts where the human is already looking); the desktop
# webview is next (visible, stateful); headless Playwright is the
# always-available fallback for backend/crawl use.
TRACK_PRIORITY: tuple[Track, ...] = (
    Track.EXTENSION,
    Track.ELECTRON,
    Track.PLAYWRIGHT,
)


@dataclass(frozen=True)
class BrowserResult:
    """Normalized action result. ``raw`` keeps the track's full dict so
    nothing is lost while call sites migrate."""

    ok: bool
    track: Track
    error: str | None = None
    data: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_track(cls, track: Track, response: dict[str, Any]) -> BrowserResult:
        ok = bool(response.get("ok", False))
        return cls(
            ok=ok,
            track=track,
            error=None if ok else str(response.get("error") or "unknown_error"),
            data={k: v for k, v in response.items() if k not in ("ok", "error")} or None,
            raw=response,
        )


@runtime_checkable
class BrowserBackend(Protocol):
    """The contract a unified browser track must satisfy.

    Every method returns a :class:`BrowserResult`. Implementations must
    not raise for ordinary action failures (element missing, timeout) —
    those are ``ok=False`` results so the agent loop can observe and
    react rather than crash.
    """

    track: Track

    def available(self) -> bool:
        """True when this backend can serve calls right now (runtime
        present, session live). The resolver skips unavailable
        backends."""
        ...

    def navigate(self, url: str) -> BrowserResult: ...
    def click(self, selector: str) -> BrowserResult: ...
    def type(self, selector: str, text: str, *, clear: bool = False) -> BrowserResult: ...
    def scroll(self, *, selector: str | None = None, delta_y: int = 0) -> BrowserResult: ...
    def wait(self, selector: str, *, timeout_ms: int = 10_000) -> BrowserResult: ...
    def state(self, *, max_items: int = 30) -> BrowserResult: ...
    def extract(self) -> BrowserResult: ...


def resolve_backend(
    backends: list[BrowserBackend],
    *,
    prefer: Track | None = None,
) -> BrowserBackend | None:
    """Pick the highest-priority *available* backend.

    ``prefer`` forces a specific track when it is present and available
    (an explicit caller override); otherwise TRACK_PRIORITY decides.
    Returns ``None`` when nothing is available — callers then surface a
    "no browser" result rather than guessing.
    """
    by_track = {b.track: b for b in backends}
    if prefer is not None:
        chosen = by_track.get(prefer)
        if chosen is not None and chosen.available():
            return chosen
    for track in TRACK_PRIORITY:
        candidate = by_track.get(track)
        if candidate is not None and candidate.available():
            return candidate
    # Mock is never in TRACK_PRIORITY (tests opt in explicitly via
    # ``prefer=Track.MOCK``); fall through to None for real callers.
    return None


__all__ = [
    "BrowserAction",
    "BrowserBackend",
    "BrowserResult",
    "Track",
    "TRACK_PRIORITY",
    "resolve_backend",
]
