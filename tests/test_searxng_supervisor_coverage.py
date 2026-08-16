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
    assert "secret_key: \"sekrit\"" in rendered
    assert "- json" in rendered
    assert "limiter: false" in rendered


def test_run_argv_shape() -> None:
    argv = ss._run_argv(
        docker="docker", name="searx", port="8888",
        settings_file="/tmp/settings.yml", image="img/searx",
    )
    assert argv[0] == "docker"
    assert "--name" in argv and argv[argv.index("--name") + 1] == "searx"
    assert "127.0.0.1:8888:8080" in argv
    assert "/tmp/settings.yml:/etc/searxng/settings.yml:ro" in argv
    assert argv[-1] == "img/searx"


def test_should_restart_matrix() -> None:
    base = dict(up=False, managed=True, container_running=False, docker_present=True, now=100.0, last_restart=0.0, backoff_s=10.0)
    assert ss._should_restart(**base) is True
    assert ss._should_restart(**{**base, "up": True}) is False
    assert ss._should_restart(**{**base, "managed": False}) is False
    assert ss._should_restart(**{**base, "docker_present": False}) is False
    assert ss._should_restart(**{**base, "container_running": True}) is False
    assert ss._should_restart(**{**base, "last_restart": 95.0}) is False  # in backoff
