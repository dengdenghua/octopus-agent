"""DEPRECATED 2026-05 realtime migration.

Original bench script targeted the retired SSE endpoints
(``/api/threads/{id}/runs/stream`` etc.). The harness falls over on
connect. Re-enable once a realtime-WS bench entry point lands.
"""
from __future__ import annotations

import sys as _sys

_RETIRED_MSG = (
    "benchmarks/ is retired until the realtime-WS harness lands. "
    "See CHANGELOG [Unreleased] realtime WebSocket transport."
)
_sys.stderr.write(_RETIRED_MSG + "\n")
_sys.exit(2)
