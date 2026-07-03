from __future__ import annotations

import logging

import runtime.platform.prompts as prompts_module
from runtime.platform.prompts import PromptLoader


def test_prompt_loader_reads_content_block_without_pyyaml(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "planner.yaml").write_text(
        "version: 1\ncontent: |\n  line one\n  line two\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts_module, "yaml", None)
    loader = PromptLoader([prompts_dir])

    with caplog.at_level(logging.WARNING):
        assert loader.get("planner") == "line one\nline two"

    assert "PyYAML is not installed" not in caplog.text


def test_prompt_loader_falls_back_to_builtin_for_complex_yaml_without_pyyaml(
    tmp_path,
    monkeypatch,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "planner_base.yaml").write_text(
        "version: 1\nmessages:\n  - role: system\n    content: unsupported shape\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts_module, "yaml", None)
    loader = PromptLoader([prompts_dir])

    assert "You are the planning module" in loader.get("planner_base")


def test_prompt_loader_supports_chomped_content_block_without_pyyaml(
    tmp_path,
    monkeypatch,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "compact.yaml").write_text(
        "content: |-\n  one\n  two\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts_module, "yaml", None)
    loader = PromptLoader([prompts_dir])

    assert loader.get("compact") == "one\ntwo"
