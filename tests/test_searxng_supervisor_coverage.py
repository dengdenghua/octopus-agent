"""Dense coverage for searxng_supervisor pure helpers (audit Q-05)."""

from __future__ import annotations

from runtime.sensing.gateway import searxng_supervisor as ss


def test_autostart_env(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_SEARXNG_AUTOSTART", "")
    assert ss._autostart_enabled() is False
    monkeypatch.setenv("OCTOPUS_SEARXNG_AUTOSTART", "1")
    assert ss._autostart_enabled() is True
    monkeypatch.setenv("OCTOPUS_SEARXNG_AUTOSTART", "off")
    assert ss._autostart_enabled() is False


def test_config_defaults_and_overrides(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_SEARXNG_PORT", raising=False)
    monkeypatch.delenv("OCTOPUS_SEARXNG_IMAGE", raising=False)
    monkeypatch.delenv("OCTOPUS_SEARXNG_CONTAINER", raising=False)
    assert ss._searxng_port() == ss._DEFAULT_PORT
    assert ss._image() == ss._DEFAULT_IMAGE
    assert ss._container_name() == ss._DEFAULT_CONTAINER
    assert ss._local_url() == f"http://127.0.0.1:{ss._DEFAULT_PORT}"

    monkeypatch.setenv("OCTOPUS_SEARXNG_PORT", "8888")
    monkeypatch.setenv("OCTOPUS_SEARXNG_IMAGE", "custom/searxng")
    monkeypatch.setenv("OCTOPUS_SEARXNG_CONTAINER", "my-searx")
    assert ss._searxng_port() == "8888"
    assert ss._image() == "custom/searxng"
    assert ss._container_name() == "my-searx"
    assert ss._local_url() == "http://127.0.0.1:8888"


def test_settings_dir_and_render(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ss._settings_dir() == tmp_path / ".octopus" / "searxng"
    rendered = ss._render_settings("sekrit")
    assert 'secret_key: "sekrit"' in rendered
    assert "- json" in rendered
    assert "limiter: false" in rendered


def test_run_argv_shape() -> None:
    argv = ss._run_argv(
        docker="docker",
        name="searx",
        port="8888",
        settings_file="/tmp/settings.yml",
        image="img/searx",
    )
    assert argv[0] == "docker"
    assert "--name" in argv and argv[argv.index("--name") + 1] == "searx"
    assert "127.0.0.1:8888:8080" in argv
    assert "/tmp/settings.yml:/etc/searxng/settings.yml:ro" in argv
    assert argv[-1] == "img/searx"


def test_should_restart_matrix() -> None:
    base = dict(
        up=False,
        managed=True,
        container_running=False,
        docker_present=True,
        now=100.0,
        last_restart=0.0,
        backoff_s=10.0,
    )
    assert ss._should_restart(**base) is True
    assert ss._should_restart(**{**base, "up": True}) is False
    assert ss._should_restart(**{**base, "managed": False}) is False
    assert ss._should_restart(**{**base, "docker_present": False}) is False
    assert ss._should_restart(**{**base, "container_running": True}) is False
    assert ss._should_restart(**{**base, "last_restart": 95.0}) is False  # in backoff


def _proc(returncode=0, stdout="", stderr=""):
    import subprocess

    # text=True callers expect str; the docker-info probe uses bytes but
    # never inspects stdout.
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_docker_probes(monkeypatch) -> None:
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "v25"))
    assert ss._docker_running("docker") is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1))
    assert ss._docker_running("docker") is False
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no docker"))
    )
    assert ss._docker_running("docker") is False

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "abc123\n"))
    assert ss._container_exists("docker", "searx") is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, ""))
    assert ss._container_exists("docker", "searx") is False

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "true"))
    assert ss._container_running("docker", "searx") is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "false"))
    assert ss._container_running("docker", "searx") is False


def test_already_up(monkeypatch) -> None:
    class _Up:
        def __init__(self, ok):
            self.ok = ok

        def get(self, url):
            if not self.ok:
                raise RuntimeError("down")
            return object()

    class _Client:
        def __init__(self, ok):
            self._ok = ok

        def __enter__(self):
            return _Up(self._ok)

        def __exit__(self, *a):
            return False

    import httpx

    monkeypatch.setattr(httpx, "Client", lambda timeout=1.5: _Client(True))
    assert ss._already_up() is True
    monkeypatch.setattr(httpx, "Client", lambda timeout=1.5: _Client(False))
    assert ss._already_up() is False


def test_ensure_settings_and_url_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    f = ss._ensure_settings()
    assert f.exists() and "secret_key" in f.read_text(encoding="utf-8")
    f2 = ss._ensure_settings()
    assert f == f2  # idempotent

    import os

    monkeypatch.delenv("SEARXNG_URL", raising=False)
    ss._set_url_env(force=False)
    assert os.environ.get("SEARXNG_URL", "") == ss._local_url()
    monkeypatch.setenv("SEARXNG_URL", "https://external")
    ss._set_url_env(force=False)
    assert os.environ["SEARXNG_URL"] == "https://external"
    ss._set_url_env(force=True)
    assert os.environ["SEARXNG_URL"] == ss._local_url()


def test_launch_branches(monkeypatch) -> None:
    import subprocess

    monkeypatch.setattr(ss, "_docker", lambda: "/usr/bin/docker")
    monkeypatch.setenv("HOME", "/tmp/searx-home")
    # running already
    monkeypatch.setattr(ss, "_container_running", lambda d, n: True)
    assert ss._launch() is True
    # exists but stopped -> docker start
    monkeypatch.setattr(ss, "_container_running", lambda d, n: False)
    monkeypatch.setattr(ss, "_container_exists", lambda d, n: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0))
    assert ss._launch() is True
    # no docker
    monkeypatch.setattr(ss, "_docker", lambda: None)
    assert ss._launch() is False
