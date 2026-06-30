"""Actor context for model-router calls — a provider-neutral home.

The ``current_actor`` ContextVar carries the human / API identity into the
model call path (so a router can attribute usage, enforce per-actor billing,
or refuse when login is required). It historically lived in ``molili_router``,
which coupled ~every model-call site to the Molili integration. It lives here
now so the runtime can drop Molili without touching the call path;
``molili_router`` re-exports this name for backwards compatibility.
"""

from __future__ import annotations

import contextvars

current_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "model_router_current_actor", default=None,
)
