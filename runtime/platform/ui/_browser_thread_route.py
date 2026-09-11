"""Keep synchronous Playwright objects on one owner thread across requests."""

import asyncio
import functools
import inspect
from concurrent.futures import ThreadPoolExecutor

from fastapi.routing import APIRoute

_browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-browser")


class BrowserThreadRoute(APIRoute):
    def __init__(self, path, endpoint, **kwargs):
        # Relay requests wait for heartbeat delivery and must run concurrently.
        if "/relay/" not in path and not inspect.iscoroutinefunction(endpoint):
            original = endpoint

            @functools.wraps(original)
            async def on_browser_thread(*args, **values):
                return await asyncio.get_running_loop().run_in_executor(
                    _browser_executor, functools.partial(original, *args, **values)
                )

            on_browser_thread.__signature__ = inspect.signature(original, eval_str=True)
            endpoint = on_browser_thread
        super().__init__(path, endpoint, **kwargs)
