"""Tests for the repository-root hygiene guard.

The guard's job is to keep ROOT_LAYOUT.md honest about what may live at the
repository root. It was scoped to git-tracked entries, which left one class of
mess permanently invisible: a directory whose name is an environment variable
somebody forgot to expand. Its contents are usually gitignored (*.db, *.log),
so `git status` never mentions it, and the tracked-only scope never looked at
it either. These tests cover that case and the plain allow-list path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.lint import root_hygiene as guard


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)


def test_flags_an_unexpanded_environment_variable_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stray %SystemDrive% tree is exactly what this rule exists to name."""
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("*.db\n", encoding="utf-8")
    caches = tmp_path / "%SystemDrive%" / "ProgramData" / "Microsoft" / "Windows" / "Caches"
    caches.mkdir(parents=True)
    (caches / "cversions.2.db").write_bytes(b"\x00")

    assert guard.main(["--repo-root", str(tmp_path), "--strict"]) == 1
    assert "%SystemDrive%" in capsys.readouterr().out


def test_gitignored_contents_do_not_hide_the_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The tracked-only scope cannot see this; the filesystem scan must.

    ``git ls-files`` is empty here, so the allow-list half of the check reports
    nothing at all. Without the environment-variable rule the tree would sit at
    the root indefinitely while every guard reported green.
    """
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("*.db\n*.log\n", encoding="utf-8")
    leak = tmp_path / "%SystemDrive%" / "ProgramData"
    leak.mkdir(parents=True)
    (leak / "external-contact.log").write_text("", encoding="utf-8")

    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout.strip() == ""

    assert guard.main(["--repo-root", str(tmp_path), "--strict"]) == 1
    assert "%SystemDrive%" in capsys.readouterr().out


@pytest.mark.parametrize(
    "name",
    ["%SystemDrive%", "%TEMP%", "%USERPROFILE(x)%", "${HOME}", "$HOME"],
)
def test_detects_both_placeholder_dialects(tmp_path: Path, name: str) -> None:
    _init_repo(tmp_path)
    (tmp_path / name).mkdir()

    assert guard._unexpanded_env_entries(tmp_path) == [name]


@pytest.mark.parametrize("name", ["runtime", "docs", ".github", "README.md"])
def test_ordinary_root_entries_are_not_placeholders(tmp_path: Path, name: str) -> None:
    _init_repo(tmp_path)
    entry = tmp_path / name
    if "." in name and name != ".github":
        entry.write_text("x", encoding="utf-8")
    else:
        entry.mkdir()

    assert guard._unexpanded_env_entries(tmp_path) == []


def test_clean_root_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init_repo(tmp_path)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    assert guard.main(["--repo-root", str(tmp_path), "--strict"]) == 0
    assert "root is clean" in capsys.readouterr().out


def test_scan_defaults_to_this_checkout() -> None:
    """Without ``--repo-root`` the guard inspects the repo it lives in."""
    assert guard.main(["--print-allowlist"]) == 0
    assert guard.REPO_ROOT.is_dir()
