"""Codex App Server execution backend primitives.

The package is an anti-corruption boundary around OpenAI's versioned App
Server protocol.  Octopus callers use the high-level execution session and
native event projection; transport details never become public gateway state.
"""

from __future__ import annotations

from .backend import (
    CodexBackendStateError,
    CodexBackendUnavailable,
    CodexExecutionRequest,
    CodexExecutionSession,
)
from .client import CodexAppServerClient
from .security import (
    CodexSecurityError,
    CodexSecurityPolicy,
    CodexSidecarContext,
    CodexSidecarSecurity,
    CodexThreadBinding,
)
from .types import (
    DEFAULT_ENV_ALLOWLIST,
    ApprovalHandler,
    ApprovalRequest,
    AppServerProcess,
    BackpressureError,
    CodexAppServerConfig,
    CodexAppServerError,
    ConfigurationError,
    JsonObject,
    JsonValue,
    MessageTooLargeError,
    Notification,
    ProcessFactory,
    ProcessLaunch,
    ProtocolError,
    RemoteError,
    RequestTimeoutError,
    TransportClosedError,
)

__all__ = [
    "ApprovalHandler",
    "ApprovalRequest",
    "AppServerProcess",
    "BackpressureError",
    "CodexBackendStateError",
    "CodexBackendUnavailable",
    "CodexAppServerClient",
    "CodexAppServerConfig",
    "CodexAppServerError",
    "CodexExecutionRequest",
    "CodexExecutionSession",
    "CodexSecurityError",
    "CodexSecurityPolicy",
    "CodexSidecarContext",
    "CodexSidecarSecurity",
    "CodexThreadBinding",
    "ConfigurationError",
    "DEFAULT_ENV_ALLOWLIST",
    "JsonObject",
    "JsonValue",
    "MessageTooLargeError",
    "Notification",
    "ProcessFactory",
    "ProcessLaunch",
    "ProtocolError",
    "RemoteError",
    "RequestTimeoutError",
    "TransportClosedError",
]
