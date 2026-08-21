"""Packaging regression (audit A-10): every shippable top-level package must
be matched by [tool.setuptools.packages.find] include patterns, or `pip
install` produces a wheel that silently drops runtime-imported packages."""

from __future__ import annotations

import fnmatch
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# Production modules introduced by behavior-preserving splits or routing fixes
# must be present in a clean, tracked-source wheel.  Importing only the CLI can
# miss lazy router/plugin imports, which previously allowed a developer Docker
# build to pass while the tag build from a clean checkout was incomplete.
_REQUIRED_RUNTIME_WHEEL_FILES = {
    "runtime/platform/models/custom_model_selection.py",
    "runtime/platform/plugins/_secure_fetch.py",
    "runtime/platform/plugins/bundled/paper_trading/_http_support.py",
    "runtime/platform/plugins/bundled/paper_trading/live_push.py",
    "runtime/platform/plugins/bundled/paper_trading/upstream_url.py",
    "runtime/sensing/gateway/_evolution_ops_insights.py",
    "runtime/sensing/gateway/_realtime_subagent_journal_items.py",
    "runtime/sensing/gateway/team_rooms_models.py",
    "runtime/sensing/gateway/thread_workspace.py",
}

_REQUIRED_TRACKED_RELEASE_FILES = _REQUIRED_RUNTIME_WHEEL_FILES | {
    ".github/workflows/behavioral-evidence.yml",
    "deploy/k8s/networkpolicy.yaml",
    "deploy/systemd-config.yaml",
    "deploy/systemd.env.example",
    "frontend/config/public-asset-dedup.ts",
    "frontend/electron/desktop-config.cjs",
    "frontend/electron/desktop-protocol.cjs",
    "frontend/src/components/workspace/community/community-assets.ts",
    "frontend/src/components/workspace/workspace-route-outlet.tsx",
    "tests/test_desktop_config_packaging.py",
}


def _find_include_patterns() -> list[str]:
    text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(
        r"\[tool\.setuptools\.packages\.find\](.*?)(?:\n\[|\Z)",
        text,
        re.DOTALL,
    )
    assert m, "packages.find section not found"
    section = m.group(1)
    include_m = re.search(r"include\s*=\s*\[(.*?)\]", section, re.DOTALL)
    assert include_m, "include patterns not found"
    return [s.strip().strip('"') for s in include_m.group(1).split(",") if s.strip()]


def _top_level_packages() -> list[str]:
    out = []
    for child in _REPO.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            out.append(child.name)
    return sorted(out)


def test_all_shippable_top_level_packages_are_included() -> None:
    """runtime, tools, octopus_runtime and demos are imported from shipped
    code; none of them may silently drop out of the wheel."""
    include = _find_include_patterns()
    for pkg in _top_level_packages():
        if pkg == "tests":  # excluded by design
            continue
        assert any(fnmatch.fnmatch(pkg, pattern) for pattern in include), (
            f"top-level package {pkg!r} is not matched by packages.find include={include}"
        )


def test_distribution_name_cannot_resolve_to_the_unrelated_pypi_project() -> None:
    project = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "octopus-agent-runtime"
    assert project["scripts"]["octopus-agent"] == "runtime.cli:main"

    install_surfaces = [
        _REPO / "docs" / "deployment.md",
        _REPO / "docs" / "roadmap.md",
        _REPO / "deploy" / "octopus-agent.service",
        _REPO / "runtime" / "sensing" / "_fastapi_guard.py",
        _REPO / "runtime" / "sensing" / "gateway" / "cron_router.py",
        _REPO / "runtime" / "platform" / "observability" / "health.py",
    ]
    for path in install_surfaces:
        text = path.read_text(encoding="utf-8")
        assert "octopus-agent[" not in text, path
    assert "octopus-agent-runtime[serve," in install_surfaces[0].read_text(encoding="utf-8")


def test_release_critical_new_files_are_tracked() -> None:
    """A local green build must not depend on files omitted by git archive."""

    tracked = set(
        subprocess.run(
            ["git", "ls-files", "--", *_REQUIRED_TRACKED_RELEASE_FILES],
            cwd=_REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    missing = sorted(_REQUIRED_TRACKED_RELEASE_FILES - tracked)
    assert not missing, "release-critical files are absent from git archive: " + ", ".join(missing)


def _clean_packaging_source(tmp_path: Path) -> Path:
    """Materialize only tracked package inputs, excluding ignored skill caches."""

    source = tmp_path / "source"
    source.mkdir()
    package_inputs = [
        "pyproject.toml",
        "README.md",
        "MANIFEST.in",
        "LICENSE",
        "NOTICE",
        "skills.lock.json",
        "runtime",
        "tools",
        "octopus_runtime",
        "demos",
    ]
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD", "--", *package_inputs],
        cwd=_REPO,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        root = source.resolve()
        for member in tar.getmembers():
            target = (source / member.name).resolve()
            assert target == root or root in target.parents, member.name
        tar.extractall(source, filter="data")  # noqa: S202 - trusted local git archive

    # Local verification runs before the fix is committed. Overlay modified
    # tracked package inputs so it exercises the working-tree implementation;
    # in CI the archive already contains those committed versions.
    changed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRTUXB",
            "HEAD",
            "--",
            *package_inputs,
        ],
        cwd=_REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for relative in changed:
        src = _REPO / relative
        if not src.is_file():
            continue
        dest = source / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    deleted = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=D",
            "HEAD",
            "--",
            *package_inputs,
        ],
        cwd=_REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for relative in deleted:
        dest = source / relative
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists() or dest.is_symlink():
            dest.unlink()
    return source


def test_clean_tracked_source_wheel_contains_bundled_market_skills(tmp_path: Path) -> None:
    """A clean wheel must retain an offline prompt catalog without skills/public."""

    source = _clean_packaging_source(tmp_path)
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"{build.stdout}\n{build.stderr}"
    wheel = next(wheel_dir.glob("octopus_agent_runtime-*.whl"))
    installed = tmp_path / "installed-wheel"
    with zipfile.ZipFile(wheel) as package:
        packaged_names = set(package.namelist())
        skill_files = {
            name
            for name in packaged_names
            if re.fullmatch(r"runtime/execution/all_skills/[^/]+/SKILL\.md", name)
        }
        package.extractall(installed)

    missing_runtime_files = sorted(_REQUIRED_RUNTIME_WHEEL_FILES - packaged_names)
    assert not missing_runtime_files, (
        "clean tracked-source wheel omitted production modules: " + ", ".join(missing_runtime_files)
    )
    assert len(skill_files) >= 3
    assert "runtime/execution/all_skills/database-inspector/SKILL.md" in skill_files
    assert "runtime/execution/all_skills/repo-audit/SKILL.md" in skill_files

    empty_resources = tmp_path / "empty-resources"
    empty_resources.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(installed)
    env["OCTOPUS_RESOURCES_DIR"] = str(empty_resources)
    installed_smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from runtime.execution.suckers import SkillRegistry; "
                "from runtime.execution.all_skills import register_all; "
                "registry = SkillRegistry(); "
                "register_all(registry); "
                "assert len(registry.all_names()) >= 3; "
                "assert registry.has('database-inspector')"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed_smoke.returncode == 0, f"{installed_smoke.stdout}\n{installed_smoke.stderr}"


def test_docker_distribution_copies_bootstrap_code_and_lockfile() -> None:
    dockerfile = (_REPO / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (_REPO / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY octopus_runtime/ ./octopus_runtime/" in dockerfile
    assert "COPY skills.lock.json /app/resources/skills.lock.json" in dockerfile
    assert (
        "COPY pyproject.toml uv.lock README.md MANIFEST.in LICENSE NOTICE skills.lock.json ./"
        in dockerfile
    )
    assert "skills/public/*/" in dockerignore
    assert "!runtime/execution/all_skills/**/*.md" in dockerignore
