from __future__ import annotations

import ast
from pathlib import Path

from runtime.core.cerebrum.react_loop import _model_recovery_timeout_s

REACT_LOOP = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "core"
    / "cerebrum"
    / "react_loop.py"
)


def _constant_dict_keys(node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _constant_dict_value(node: ast.Dict, name: str) -> object | None:
    for key, value in zip(node.keys, node.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == name:
            return value.value if isinstance(value, ast.Constant) else None
    return None


def test_every_react_commentary_event_declares_its_author() -> None:
    """Public model updates and runtime diagnostics must never be ambiguous.

    The realtime bridge intentionally keeps runtime-authored commentary out of
    the main conversation. An unlabelled event is treated as legacy public
    commentary, so one missing key would leak fixed recovery/opening prose back
    into the transcript.
    """

    tree = ast.parse(REACT_LOOP.read_text(encoding="utf-8"))
    missing_source = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and _constant_dict_value(node, "type") == "commentary_delta"
        and "progress_source" not in _constant_dict_keys(node)
    ]

    assert missing_source == [], (
        "Every commentary_delta must declare progress_source=model|runtime; "
        f"missing at react_loop.py lines {missing_source}"
    )


def test_recovery_round_uses_a_shorter_default_deadline(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_REACT_MODEL_RECOVERY_TIMEOUT_S", raising=False)

    assert _model_recovery_timeout_s(120.0) == 60.0


def test_recovery_deadline_never_lengthens_the_base_timeout(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_REACT_MODEL_RECOVERY_TIMEOUT_S", "600")

    assert _model_recovery_timeout_s(45.0) == 45.0
    assert _model_recovery_timeout_s(0.025) == 0.025
