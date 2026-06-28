from __future__ import annotations

from pathlib import Path

from runtime.platform.process.paths import app_paths, project_root, resources_root


def _make_project(root: Path) -> Path:
    (root / "runtime").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'octopus-agent'\n", encoding="utf-8")
    return root


def test_app_paths_follow_octopus_data_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / "octopus-data"
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)

    paths = app_paths()

    assert paths.root == data_dir.resolve().parent
    assert paths.data_dir == data_dir.resolve()
    assert paths.threads_path == data_dir.resolve() / "threads.jsonl"
    assert paths.agent_trace_path == data_dir.resolve() / "agent_trace.sqlite"
    assert paths.permissions_path == data_dir.resolve() / "permissions.json"
    assert paths.browser_policy_path == data_dir.resolve() / "browser_policy.json"


def test_octopus_data_dir_wins_over_octopus_home(monkeypatch, tmp_path):
    data_dir = tmp_path / "data-dir"
    home = tmp_path / "home"
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OCTOPUS_HOME", str(home))

    paths = app_paths()

    assert paths.root == data_dir.resolve().parent
    assert paths.data_dir == data_dir.resolve()


def test_app_paths_follow_octopus_home_when_data_dir_missing(monkeypatch, tmp_path):
    home = tmp_path / "octopus-home"
    monkeypatch.delenv("OCTOPUS_DATA_DIR", raising=False)
    monkeypatch.setenv("OCTOPUS_HOME", str(home))

    paths = app_paths()

    assert paths.root == home.resolve()
    assert paths.data_dir == home.resolve() / "data"
    assert paths.permissions_path == home.resolve() / "data" / "permissions.json"


def test_project_root_discovers_repo_from_child_directory(monkeypatch, tmp_path):
    repo = _make_project(tmp_path / "repo")
    child = repo / "runtime" / "platform"
    child.mkdir(parents=True)
    monkeypatch.chdir(child)
    monkeypatch.delenv("OCTOPUS_DATA_DIR", raising=False)
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)

    assert project_root() == repo.resolve()
    assert app_paths().root == repo.resolve()
    assert app_paths().data_dir == repo.resolve() / "data"


def test_project_root_falls_back_to_cwd_without_sentinels(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    monkeypatch.delenv("OCTOPUS_DATA_DIR", raising=False)
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)

    assert project_root() == scratch.resolve()
    assert app_paths().data_dir == scratch.resolve() / "data"


def test_resources_root_honours_env(monkeypatch, tmp_path):
    # The Docker image pip-installs the code and runs from /data, so
    # project_root() can't find bundled skills/prompts/protocols. The
    # image sets OCTOPUS_RESOURCES_DIR=/app/resources; resources_root()
    # must honour it so the 87+ file-backed skills actually load.
    res = tmp_path / "resources"
    res.mkdir()
    monkeypatch.setenv("OCTOPUS_RESOURCES_DIR", str(res))
    assert resources_root() == res.resolve()


def test_resources_root_resolves_assets_when_cwd_outside_tree(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    monkeypatch.delenv("OCTOPUS_RESOURCES_DIR", raising=False)
    monkeypatch.delenv("OCTOPUS_DATA_DIR", raising=False)
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)
    # No env, cwd outside the source tree: project_root() can only degrade to
    # cwd, but resources_root() must still resolve to the real source-tree root
    # via the package location so bundled skills/ load regardless of cwd — the
    # whole reason the function exists (without this, tests/entrypoints that
    # chdir elsewhere silently lose the file-backed skill catalog).
    rr = resources_root()
    assert (rr / "pyproject.toml").is_file()
    assert (rr / "runtime").is_dir()
    assert (rr / "skills" / "public").is_dir()
    # project_root(), by contrast, degrades to cwd when no sentinel is found.
    assert project_root() == scratch.resolve()
