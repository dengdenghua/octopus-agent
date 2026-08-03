"""Shared server options for every Uvicorn entrypoint."""

from typing import Any

import uvicorn

UVICORN_WEBSOCKET_PROTOCOL = "websockets-sansio"


def run_uvicorn(app: Any, **kwargs: Any) -> None:
    """Run Uvicorn on the maintained SansIO WebSocket implementation."""

    uvicorn.run(app, ws=UVICORN_WEBSOCKET_PROTOCOL, **kwargs)


__all__ = ["UVICORN_WEBSOCKET_PROTOCOL", "run_uvicorn"]
