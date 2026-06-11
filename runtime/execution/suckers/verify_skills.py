"""Project verification · detect project type and run checks.

Scans a workspace root for marker files (package.json, pyproject.toml,
Cargo.toml, go.mod, etc.) and returns the appropriate verification
commands. The runner executes them sequentially and returns structured
results so the frontend can show pass/fail per check.

Security: every ``check`` carries an ``argv`` (list of strings) that is
executed with ``shell=False``. The legacy ``cmd`` string field is still
read for backwards compatibility but is logged as a warning — new
entries must supply ``argv``.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class ProjectProfile:
    kind: str
    root: str
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    command: str
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


def _module_installed(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _tsc_installed(root: Path) -> bool:
    bin_dir = root / "node_modules" / ".bin"
    return (bin_dir / "tsc").exists() or (bin_dir / "tsc.cmd").exists()


def detect_project(workspace: str) -> ProjectProfile:
    root = Path(workspace)
    if not root.is_dir():
        return ProjectProfile(kind="unknown", root=workspace)

    checks: list[dict[str, Any]] = []

    if (root / "package.json").is_file():
        pkg = _read_json(root / "package.json")
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        has_ts = (root / "tsconfig.json").is_file()
        kind = "node-ts" if has_ts else "node"
        # Only offer typecheck when tsc is actually installed: a bare
        # ``npx tsc`` on a machine without the package may hit the
        # network to fetch it, and a missing binary would surface as a
        # bogus "typecheck failed" — these checks feed the agent's
        # auto-diagnostics, so a false failure sends it chasing
        # phantom errors.
        if has_ts and _tsc_installed(root):
            checks.append({
                "name": "typecheck",
                "argv": ["npx", "--no-install", "tsc", "--noEmit"],
                "display_cmd": "npx --no-install tsc --noEmit",
            })
        if "lint" in scripts:
            checks.append({
                "name": "lint",
                "argv": ["npm", "run", "lint"],
                "display_cmd": "npm run lint",
            })
        if "test" in scripts:
            # --run is the vitest convention; if the project uses a different
            # runner the extra flag is simply ignored.
            checks.append({
                "name": "test",
                "argv": ["npm", "test", "--", "--run"],
                "display_cmd": "npm test -- --run",
            })
        if "build" in scripts:
            checks.append({
                "name": "build",
                "argv": ["npm", "run", "build"],
                "display_cmd": "npm run build",
            })
        if not checks:
            checks.append({
                "name": "install-check",
                "argv": ["npm", "ls", "--depth=0"],
                "display_cmd": "npm ls --depth=0",
            })
        return ProjectProfile(kind=kind, root=workspace, checks=checks)

    if (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        kind = "python"
        # Same tool-presence gate as tsc above: without it, projects
        # that don't ship mypy (most of them) get "No module named
        # mypy" reported as a typecheck FAILURE after every file write.
        if (root / "pyproject.toml").is_file() and _module_installed("mypy"):
            checks.append({
                "name": "typecheck",
                "argv": [sys.executable, "-m", "mypy", ".", "--ignore-missing-imports"],
                "display_cmd": "python -m mypy . --ignore-missing-imports",
            })
        if _any_exists(root, ["pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"]):
            checks.append({
                "name": "test",
                "argv": [sys.executable, "-m", "pytest", "--tb=short", "-q"],
                "display_cmd": "python -m pytest --tb=short -q",
            })
        checks.append({
            "name": "syntax",
            "argv": [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path\n"
                    "import py_compile, sys\n"
                    "files = [p for p in Path('.').rglob('*.py') "
                    "if '.venv' not in p.parts and '__pycache__' not in p.parts][:20]\n"
                    "failed = 0\n"
                    "for p in files:\n"
                    "    try:\n"
                    "        py_compile.compile(str(p), doraise=True)\n"
                    "    except Exception as exc:\n"
                    "        failed += 1\n"
                    "        print(f'{p}: {exc}')\n"
                    "print(f'checked {len(files)} python files')\n"
                    "sys.exit(1 if failed else 0)\n"
                ),
            ],
            "display_cmd": 'python -c "compile up to 20 Python files"',
        })
        return ProjectProfile(kind=kind, root=workspace, checks=checks)

    if (root / "Cargo.toml").is_file():
        return ProjectProfile(kind="rust", root=workspace, checks=[
            {"name": "check", "argv": ["cargo", "check"], "display_cmd": "cargo check"},
            {"name": "test", "argv": ["cargo", "test", "--no-run"], "display_cmd": "cargo test --no-run"},
            {"name": "clippy", "argv": ["cargo", "clippy", "--", "-D", "warnings"], "display_cmd": "cargo clippy -- -D warnings"},
        ])

    if (root / "go.mod").is_file():
        return ProjectProfile(kind="go", root=workspace, checks=[
            {"name": "build", "argv": ["go", "build", "./..."], "display_cmd": "go build ./..."},
            {"name": "vet", "argv": ["go", "vet", "./..."], "display_cmd": "go vet ./..."},
            {"name": "test", "argv": ["go", "test", "./...", "-count=1", "-short"], "display_cmd": "go test ./... -count=1 -short"},
        ])

    return ProjectProfile(kind="unknown", root=workspace, checks=[
        {
            "name": "file-count",
            "argv": [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path\n"
                    "root = Path('.')\n"
                    "count = sum(1 for p in root.rglob('*') "
                    "if p.is_file() and len(p.relative_to(root).parts) <= 3)\n"
                    "print(count)\n"
                ),
            ],
            "display_cmd": 'python -c "count files up to depth 3"',
        },
    ])


def run_checks(
    profile: ProjectProfile,
    *,
    timeout_per_check: float = 60.0,
    max_output: int = 8000,
) -> list[CheckResult]:
    from runtime.platform.process.streaming import stream_run

    results: list[CheckResult] = []
    for check in profile.checks:
        argv = check.get("argv")
        display = check.get("display_cmd") or check.get("cmd") or ""
        legacy_cmd = check.get("cmd")
        t0 = time.monotonic()
        if isinstance(argv, list) and argv:
            r = stream_run(
                argv,
                cwd=str(profile.root),
                timeout=timeout_per_check,
                output_cap_bytes=max_output,
            )
        elif isinstance(legacy_cmd, str):
            _logger.warning(
                "verify_skills: legacy 'cmd' string check %r — switch to 'argv'",
                check.get("name"),
            )
            try:
                proc = subprocess.run(
                    legacy_cmd,
                    shell=True,  # legacy path only — new checks use argv
                    capture_output=True,
                    text=True,
                    cwd=profile.root,
                    timeout=timeout_per_check,
                )
            except FileNotFoundError as exc:
                duration = int((time.monotonic() - t0) * 1000)
                results.append(CheckResult(
                    name=check["name"], command=display, passed=False,
                    exit_code=-3, stdout="",
                    stderr=f"executable not found: {exc}",
                    duration_ms=duration,
                ))
                continue
            except subprocess.TimeoutExpired:
                duration = int((time.monotonic() - t0) * 1000)
                results.append(CheckResult(
                    name=check["name"], command=display, passed=False,
                    exit_code=-1, stdout="", stderr="timeout",
                    duration_ms=duration,
                ))
                continue
            r = {
                "stdout": proc.stdout[:max_output],
                "stderr": proc.stderr[:max_output],
                "exit_code": proc.returncode,
                "timed_out": False,
            }
        else:
            results.append(CheckResult(
                name=check.get("name", "?"),
                command=display,
                passed=False,
                exit_code=-2,
                stdout="",
                stderr="check is missing both 'argv' and 'cmd'",
                duration_ms=0,
            ))
            continue
        duration = int((time.monotonic() - t0) * 1000)
        if "error" in r and "exit_code" not in r:
            # FileNotFoundError surfaced through stream_run.
            results.append(CheckResult(
                name=check["name"], command=display, passed=False,
                exit_code=-3, stdout="",
                stderr=f"executable not found: {r['error']}",
                duration_ms=duration,
            ))
            continue
        if r.get("timed_out"):
            results.append(CheckResult(
                name=check["name"], command=display, passed=False,
                exit_code=-1, stdout="", stderr="timeout",
                duration_ms=duration,
            ))
            continue
        results.append(CheckResult(
            name=check["name"],
            command=display,
            passed=r["exit_code"] == 0,
            exit_code=r["exit_code"],
            stdout=r["stdout"][:max_output],
            stderr=r["stderr"][:max_output],
            duration_ms=duration,
        ))
    return results


def _read_json(path: Path) -> Any:
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _any_exists(root: Path, names: list[str]) -> bool:
    return any((root / n).is_file() for n in names)
