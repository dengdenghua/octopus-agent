"""Shared server options for every Uvicorn entrypoint."""

from typing import Any

UVICORN_WEBSOCKET_PROTOCOL = "websockets-sansio"


def run_uvicorn(app: Any, **kwargs: Any) -> None:
    """Run Uvicorn on the maintained SansIO WebSocket implementation."""

    # Keep Uvicorn optional at module-import time.  CLI entrypoints perform
    # their own dependency check before building the application, while this
    # late import also keeps embedded/test callers deterministic.
    import uvicorn

    uvicorn.run(app, ws=UVICORN_WEBSOCKET_PROTOCOL, **kwargs)


__all__ = ["UVICORN_WEBSOCKET_PROTOCOL", "run_uvicorn"]
