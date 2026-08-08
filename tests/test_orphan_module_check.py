"""orphan_module_check — the exported-but-unimported ratchet."""

import subprocess
import sys
from pathlib import Path

from tools.lint import orphan_module_check as check
from tools.lint.orphan_module_check import (
    _consumed_targets,
    _resolve_relative,
)

_REPO = Path(__file__).resolve().parent.parent


class TestRelativeResolution:
    def test_current_package(self):
        # `from . import x` inside package runtime.a.b → runtime.a.b.x
        assert _resolve_relative("runtime.a.b", 1, None) == "runtime.a.b"
        assert _resolve_relative("runtime.a.b", 1, "x") == "runtime.a.b.x"

    def test_parent_package(self):
        # `from ..c import y` inside runtime.a.b → runtime.a.c
        assert _resolve_relative("runtime.a.b", 2, "c") == "runtime.a.c"

    def test_overshoot_returns_none(self):
        assert _resolve_relative("runtime", 3, "x") is None


class TestConsumedTargets:
    def test_absolute_and_from_imports(self, tmp_path: Path):
        f = tmp_path / "m.py"
        f.write_text(
            "import runtime.a.b\nfrom runtime.c import d\nfrom runtime.e.f import G\n",
            encoding="utf-8",
        )
        got = _consumed_targets(f)
        assert "runtime.a.b" in got
        assert "runtime.c.d" in got  # submodule-or-symbol, over-marked (safe)
        assert "runtime.e.f" in got

    def test_lazy_import_in_function_counts(self, tmp_path: Path):
        f = tmp_path / "m.py"
        f.write_text(
            "def loader():\n    from runtime.deep.mod import thing\n    return thing\n",
            encoding="utf-8",
        )
        # A lazy import inside a body still marks the module consumed —
        # so the linter won't false-flag a module reached only lazily.
        assert "runtime.deep.mod" in _consumed_targets(f)


class TestBaselineGreen:
    def test_strict_is_green(self):
        r = subprocess.run(
            [sys.executable, "tools/lint/orphan_module_check.py", "--strict"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, (
            "orphan-module baseline drifted from reality:\n" + r.stdout + r.stderr
        )


def test_runtime_test_modules_are_not_orphan_candidates(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "tests").mkdir(parents=True)
    (runtime / "tests" / "test_example.py").write_text("def test_ok(): pass\n")

    monkeypatch.setattr(check, "_RUNTIME", runtime)
    monkeypatch.setattr(check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check, "_CONSUMER_ROOTS", ("runtime",))
    monkeypatch.setattr(check, "_script_entry_targets", lambda: set())
    monkeypatch.setattr(check, "_lazy_module_map", lambda: {})

    assert "runtime/tests/test_example.py" not in check._scan()
