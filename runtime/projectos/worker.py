"""Run the synchronous project engine with host cancellation propagated."""

import asyncio
from contextlib import suppress

from runtime.safety.approval.cancellation import (
    CancellationSource,
    current_cancellation_token,
    scoped_cancellation,
)


async def run_project_worker(worker, interrupted):
    source = CancellationSource()
    unlink = current_cancellation_token().on_cancelled(lambda reason: source.cancel(reason=reason))
    if interrupted():
        source.cancel(reason="project turn interrupted")

    async def monitor():
        while True:
            if interrupted():
                source.cancel(reason="project turn interrupted")
                return
            await asyncio.sleep(0.1)

    def run():
        with scoped_cancellation(source.token):
            source.token.throw_if_cancelled()
            return worker()

    watcher = asyncio.create_task(monitor())
    try:
        return await asyncio.to_thread(run)
    finally:
        source.cancel(reason="project worker closed")
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        unlink()
