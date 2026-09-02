"""Implementation note."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from demos.bugfix_demo import build_safe_observation_graph
from demos.evolution_demo import run_demo
from runtime.safety.approval.approval_gate import is_dangerous_tool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("git") is None,
        reason="git not on PATH",
    ),
]


class TestEvolutionDemo:
    def test_forge_source_trajectory_is_read_only(self, tmp_path: Path):
        graph = build_safe_observation_graph(tmp_path)
        skills = [str(node.skill_ref) for node in graph.nodes]

        assert skills == ["list_cwd", "read_file", "read_file"]
        assert not any(is_dangerous_tool(skill) for skill in skills)

    def test_run_succeeds(self, tmp_path: Path):
        result = run_demo(
            workdir=tmp_path,
            runs=3,
            color=False,
            verbose=False,
        )
        assert result["success"] is True

    def test_forge_proposes_candidate(self, tmp_path: Path):
        result = run_demo(
            workdir=tmp_path,
            runs=3,
            color=False,
            verbose=False,
        )
        assert result["forge"]["candidates_total"] >= 1

    def test_new_skill_in_registry(self, tmp_path: Path):
        """Implementation note."""
        result = run_demo(
            workdir=tmp_path,
            runs=3,
            color=False,
            verbose=False,
        )
        assert result["skills_after"] > result["skills_before"]
        assert result["new_skill_count"] >= 1

    def test_new_skill_name_has_forged_prefix(self, tmp_path: Path):
        result = run_demo(
            workdir=tmp_path,
            runs=3,
            color=False,
            verbose=False,
        )
        new_names = result["new_skill_names"]
        assert len(new_names) >= 1
        assert all("forged" in n.lower() for n in new_names), (
            f"new skill names should indicate forged origin · got {new_names}"
        )

    def test_promoted_skill_is_callable(self, tmp_path: Path):
        """Implementation note."""
        result = run_demo(
            workdir=tmp_path,
            runs=3,
            color=False,
            verbose=False,
        )
        # Implementation note.
        assert result["invocations"], "no invocation attempted"
        ok_invocations = [i for i in result["invocations"] if i["ok"]]
        assert ok_invocations, (
            f"forged skill couldn't be invoked · invocations: {result['invocations']}"
        )

    def test_persisted_md_files(self, tmp_path: Path):
        """Implementation note."""
        result = run_demo(
            workdir=tmp_path,
            runs=3,
            color=False,
            verbose=False,
        )
        assert result["persisted_files"], "forge promoted but no .md persisted"
        for fname in result["persisted_files"]:
            assert fname.endswith(".md")

    def test_journal_accumulates_across_runs(self, tmp_path: Path):
        """Implementation note."""
        r1 = run_demo(workdir=tmp_path / "one", runs=1, color=False, verbose=False)
        r3 = run_demo(workdir=tmp_path / "three", runs=3, color=False, verbose=False)
        assert r3["event_count"] > r1["event_count"]

    def test_single_run_may_not_forge(self, tmp_path: Path):
        """Implementation note."""
        result = run_demo(
            workdir=tmp_path,
            runs=1,
            color=False,
            verbose=False,
        )
        # Implementation note.
        assert result["forge"]["candidates_total"] == 0
        assert result["new_skill_count"] == 0
