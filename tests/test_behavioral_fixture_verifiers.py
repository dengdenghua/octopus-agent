from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _verify(script: str, workspace: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "benchmarks" / "verifiers" / script), str(workspace)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_concurrent_cache_fixture_has_a_satisfiable_hidden_verifier(tmp_path) -> None:
    workspace = tmp_path / "cache"
    shutil.copytree(REPO_ROOT / "benchmarks" / "fixtures" / "coding.concurrent-cache", workspace)
    (workspace / "cache.py").write_text(
        """
from __future__ import annotations
import threading
import time

class TTLCache:
    def __init__(self, ttl_seconds, *, clock=time.monotonic):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._values = {}
        self._conditions = {}
        self._lock = threading.Lock()

    def get_or_load(self, key, loader):
        while True:
            with self._lock:
                cached = self._values.get(key)
                if cached is not None and cached[0] > self._clock():
                    return cached[1]
                condition = self._conditions.get(key)
                if condition is None:
                    condition = threading.Condition(self._lock)
                    self._conditions[key] = condition
                    break
                condition.wait()
        try:
            value = loader()
        except BaseException:
            with self._lock:
                self._conditions.pop(key).notify_all()
            raise
        with self._lock:
            self._values[key] = (self._clock() + self.ttl_seconds, value)
            self._conditions.pop(key).notify_all()
        return value
""".lstrip(),
        encoding="utf-8",
    )
    (workspace / "tests" / "test_cache.py").write_text("def test_regression(): assert True\n")

    result = _verify("verify_concurrent_cache.py", workspace)

    assert result["passed"] is True, result


def test_path_boundary_fixture_has_a_satisfiable_hidden_verifier(tmp_path) -> None:
    workspace = tmp_path / "paths"
    shutil.copytree(REPO_ROOT / "benchmarks" / "fixtures" / "coding.path-boundary", workspace)
    (workspace / "file_service.py").write_text(
        """
from __future__ import annotations
from pathlib import Path
from urllib.parse import unquote

class PathBoundaryError(ValueError):
    pass

class FileService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def read_text(self, user_path: str) -> str:
        decoded = user_path
        for _ in range(4):
            updated = unquote(decoded)
            if updated == decoded:
                break
            decoded = updated
        root = self.root.resolve()
        candidate = (root / decoded).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PathBoundaryError("path escapes root") from exc
        return candidate.read_text(encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )
    (workspace / "tests" / "test_paths.py").write_text("def test_regression(): assert True\n")

    result = _verify("verify_path_boundary.py", workspace)

    assert result["passed"] is True, result
