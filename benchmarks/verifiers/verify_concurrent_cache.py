from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True

_EXPECTED_PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
_ALLOWED_FILES = {
    "cache.py",
    "pyproject.toml",
    "tests/.gitkeep",
    "tests/test_cache.py",
}


def _assert_no_unrelated_diff(workspace: Path) -> None:
    unexpected: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(workspace)
        relative = relative_path.as_posix()
        if set(relative_path.parts) & {
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        }:
            continue
        if relative not in _ALLOWED_FILES:
            unexpected.append(relative)
    if unexpected:
        raise AssertionError(f"unrelated files changed or added: {sorted(unexpected)}")
    if (workspace / "pyproject.toml").read_text(encoding="utf-8") != _EXPECTED_PYPROJECT:
        raise AssertionError("unrelated pyproject.toml was modified")


def _load_module(workspace: Path):
    spec = importlib.util.spec_from_file_location("candidate_cache", workspace / "cache.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load cache.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _run(workspace: Path) -> dict[str, object]:
    _assert_no_unrelated_diff(workspace)
    module = _load_module(workspace)
    cache_type = module.TTLCache
    checks: list[str] = ["no unrelated diff"]
    signature = inspect.signature(cache_type.get_or_load)
    if list(signature.parameters) != ["self", "key", "loader"]:
        raise AssertionError("TTLCache.get_or_load public signature changed")
    checks.append("public API unchanged")

    clock_value = [10.0]
    calls = 0
    calls_lock = threading.Lock()

    def loader() -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.04)
        return "value"

    cache = cache_type(5.0, clock=lambda: clock_value[0])
    barrier = threading.Barrier(8)
    values: list[str] = []

    def worker() -> None:
        barrier.wait(timeout=2)
        values.append(cache.get_or_load("shared", loader))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("concurrent callers deadlocked")
    if values != ["value"] * 8 or calls != 1:
        raise AssertionError(f"same-key loads were not coalesced: calls={calls}, values={values}")
    checks.append("same-key concurrent loads coalesced")

    clock_value[0] = 14.9
    if cache.get_or_load("shared", loader) != "value" or calls != 1:
        raise AssertionError("live cached value was not reused")
    clock_value[0] = 15.1
    if cache.get_or_load("shared", loader) != "value" or calls != 2:
        raise AssertionError("expired value was not refreshed")
    checks.append("TTL expiry enforced")

    failure_calls = 0

    def failing_loader() -> str:
        nonlocal failure_calls
        failure_calls += 1
        if failure_calls == 1:
            raise RuntimeError("seeded failure")
        return "recovered"

    try:
        cache.get_or_load("failure", failing_loader)
    except RuntimeError as exc:
        if str(exc) != "seeded failure":
            raise
    else:
        raise AssertionError("loader exception was swallowed")
    if cache.get_or_load("failure", failing_loader) != "recovered" or failure_calls != 2:
        raise AssertionError("loader exception was cached or left an in-flight tombstone")
    checks.append("exceptions are not cached")

    test_files = [path for path in (workspace / "tests").glob("test_*.py") if path.is_file()]
    if not test_files:
        raise AssertionError("focused regression tests were not added")
    checks.append("focused tests added")
    return {"passed": True, "score": 1.0, "reason": "all cache outcomes pass", "checks": checks}


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    try:
        result = _run(workspace)
    except Exception as exc:
        result = {"passed": False, "score": 0.0, "reason": str(exc), "checks": []}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
