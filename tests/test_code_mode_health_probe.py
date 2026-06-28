from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_probe(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/code_mode_health_probe.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_code_mode_health_probe_script_emits_ci_json():
    result = _run_probe()

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["name"] == "code_mode_runtime"
    assert payload["status"] == "pass"
    checks = payload["metadata"]["checks"]
    assert checks["react_empty_assistant_history"]["passed"] is True
    assert checks["openai_compat_payload_hygiene"]["passed"] is True


def test_code_mode_health_probe_text_format_is_human_readable():
    result = _run_probe("--format", "text")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "code_mode_runtime: pass" in result.stdout
    assert "react_empty_assistant_history: pass" in result.stdout
    assert "openai_compat_payload_hygiene: pass" in result.stdout
