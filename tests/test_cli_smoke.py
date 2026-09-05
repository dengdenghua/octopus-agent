"""Implementation note."""

from __future__ import annotations

import argparse
import contextlib
import io
import subprocess
import sys
from pathlib import Path

import pytest

from runtime._cli_parser import _CLI_COMMANDS, _build_parser

_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    """Implementation note."""
    return subprocess.run(
        [sys.executable, "-m", "runtime", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _subcommand_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Return the subparsers registered directly below *parser*."""
    actions = (
        action
        for action in parser._actions  # noqa: SLF001 - argparse has no public traversal API
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    )
    action = next(actions)
    return action.choices


def _assert_help_succeeds(parser: argparse.ArgumentParser, args: list[str]) -> None:
    """Exercise argparse's real help path without starting another interpreter."""
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), pytest.raises(SystemExit) as exc_info:
        parser.parse_args([*args, "--help"])

    assert exc_info.value.code == 0
    assert "usage:" in stdout.getvalue().lower()


_PARSER = _build_parser()
_TOP_LEVEL_PARSERS = _subcommand_parsers(_PARSER)
_SKILLS_SUBCOMMANDS = tuple(sorted(_subcommand_parsers(_TOP_LEVEL_PARSERS["skills"])))


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestTopLevelHelp:
    def test_top_level_help_succeeds(self):
        """Keep one subprocess check for packaging and ``python -m`` wiring."""
        r = _run_cli(["--help"])
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "octopus-agent" in r.stdout.lower() or "usage" in r.stdout.lower()
        for command in _CLI_COMMANDS:
            assert command in r.stdout, f"subcommand {command!r} missing from --help output"

    def test_parser_registers_every_canonical_subcommand(self):
        assert set(_TOP_LEVEL_PARSERS) == _CLI_COMMANDS


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestSubcommandHelp:
    @pytest.mark.parametrize("cmd", sorted(_CLI_COMMANDS))
    def test_subcommand_help_exits_zero(self, cmd: str):
        _assert_help_succeeds(_PARSER, [cmd])


class TestSkillsSubcommandHelp:
    @pytest.mark.parametrize("subcmd", _SKILLS_SUBCOMMANDS)
    def test_skills_subcommand_help(self, subcmd: str):
        _assert_help_succeeds(_PARSER, ["skills", subcmd])


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestInvalidInvocation:
    @pytest.mark.integration
    def test_no_args_shows_help_or_error(self):
        """Implementation note."""
        r = _run_cli([])
        # Implementation note.
        # Implementation note.
        assert "Traceback" not in r.stderr, f"unexpected traceback: {r.stderr}"

    @pytest.mark.integration
    def test_unknown_subcommand_treated_as_goal(self):
        """Product behavior: unknown args route to `code` as a goal."""
        r = _run_cli(["this-does-not-exist"])
        # CLI interprets "this-does-not-exist" as a coding goal, so it
        # launches a session (returncode 0) and prints session/plan output.
        assert r.returncode == 0
        # Should mention session ID or task output (not an argparse error).
        combined = (r.stdout + r.stderr).lower()
        assert "invalid choice" not in combined
        assert "unrecognized" not in combined


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestStatusRuns:
    @pytest.mark.integration
    def test_status_actually_runs(self):
        r = _run_cli(["status"])
        assert r.returncode == 0, f"status failed:\n{r.stderr}"
        # Implementation note.
        combined = r.stdout + r.stderr
        assert any(
            k in combined
            for k in [
                "skills",
                "capabilities",
                "opentelemetry",
                "httpx",
            ]
        ), f"status output missing key fields: {combined[:500]}"
        assert "market_skills: registered" not in combined

    def test_demo_no_color_does_not_override_global_flag(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), pytest.raises(SystemExit) as exc_info:
            _PARSER.parse_args(["--no-color", "bugfix-demo", "--help"])

        assert exc_info.value.code == 0
        assert "\x1b[" not in stdout.getvalue()


class TestQuickstart:
    @pytest.mark.integration
    def test_quickstart_bootstraps_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / "config.yaml"

        r = _run_cli(
            [
                "--no-color",
                "quickstart",
                "--output",
                str(config_path),
                "--non-interactive",
            ]
        )

        assert r.returncode == 0, f"quickstart failed:\nstdout={r.stdout}\nstderr={r.stderr}"
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "planner" in content
        assert "static" in content
        combined = (r.stdout + r.stderr).lower()
        assert "doctor" in combined or "health" in combined
