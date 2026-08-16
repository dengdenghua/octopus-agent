"""P-09: BackgroundRunner.stop orphan-callback handling (audit Q-05/P-09)."""

from __future__ import annotations

import logging
import threading
import time

from runtime.adapters.scheduler.runner import BackgroundRunner


def test_stop_returns_while_callback_stuck(caplog) -> None:
    """stop() must not hang on a stuck in-flight callback; it warns + returns."""
    inside = threading.Event()
    release = threading.Event()

    def stuck():
        inside.set()
        release.wait(timeout=30.0)  # never released within the stop budget

    runner = BackgroundRunner(max_workers=2)
    runner.add_periodic("stuck", 0.01, stuck, run_on_start=True)
    runner.start()
    assert inside.wait(timeout=2.0)

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="runtime.adapters.scheduler.runner"):
        runner.stop(timeout=0.5)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert not runner.is_running
    assert runner.state == "stopped"
    assert "still running" in caplog.text

    # Release the callback so the daemon worker can exit cleanly.
    release.set()


def test_stop_with_pool_drains_cleanly() -> None:
    """A fast callback on the worker pool stops without warnings."""
    ran = threading.Event()

    def quick():
        ran.set()

    runner = BackgroundRunner(max_workers=2)
    runner.add_periodic("quick", 0.01, quick, run_on_start=True)
    runner.start()
    assert ran.wait(timeout=2.0)
    runner.stop(timeout=2.0)
    assert runner.state == "stopped"
    assert runner.task_names() == ["quick"]


def test_daemon_pool_does_not_block_interpreter() -> None:
    """Worker threads of the pool are daemon, so a stuck callback cannot
    keep the interpreter alive after stop gives up on it."""
    import threading as _t

    runner = BackgroundRunner(max_workers=2)
    runner.start()
    pool = runner._pool
    assert pool is not None
    # Force a worker thread to spawn.
    done = threading.Event()
    pool.submit(done.set)
    assert done.wait(timeout=2.0)
    workers = list(pool._threads)
    assert workers, "pool should have spawned at least one worker thread"
    assert all(t.daemon for t in workers)
    runner.stop(timeout=2.0)
