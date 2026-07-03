"""One-click local SearXNG supervisor — pure-logic coverage.

The Docker calls need a daemon, but config resolution, the generated settings,
the ``docker run`` argv (a security surface: it must bind 127.0.0.1 only and
never interpolate a shell), and the restart decision are all pure and tested here.
"""

from __future__ import annotations

from runtime.sensing.gateway import searxng_supervisor as sx


def test_autostart_flag_truthy_variants(monkeypatch) -> None:
    for val in ("1", "true", "YES", "on", "On"):
        monkeypatch.setenv("OCTOPUS_SEARXNG_AUTOSTART", val)
        assert sx._autostart_enabled() is True
    for val in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("OCTOPUS_SEARXNG_AUTOSTART", val)
        assert sx._autostart_enabled() is False


def test_config_defaults_and_overrides(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_SEARXNG_PORT", raising=False)
    monkeypatch.delenv("OCTOPUS_SEARXNG_IMAGE", raising=False)
    monkeypatch.delenv("OCTOPUS_SEARXNG_CONTAINER", raising=False)
    assert sx._searxng_port() == sx._DEFAULT_PORT
    assert sx._image() == sx._DEFAULT_IMAGE
    assert sx._container_name() == sx._DEFAULT_CONTAINER
    assert sx._local_url() == f"http://127.0.0.1:{sx._DEFAULT_PORT}"

    monkeypatch.setenv("OCTOPUS_SEARXNG_PORT", "9001")
    monkeypatch.setenv("OCTOPUS_SEARXNG_IMAGE", "searxng/searxng:custom")
    monkeypatch.setenv("OCTOPUS_SEARXNG_CONTAINER", "my-sx")
    assert sx._searxng_port() == "9001"
    assert sx._image() == "searxng/searxng:custom"
    assert sx._container_name() == "my-sx"
    assert sx._local_url() == "http://127.0.0.1:9001"


def test_render_settings_enables_json_api_and_bakes_secret() -> None:
    out = sx._render_settings("deadbeef")
    assert "use_default_settings: true" in out
    assert 'secret_key: "deadbeef"' in out
    assert "limiter: false" in out
    # The agent reads JSON, not HTML — the format must be enabled or the API 403s.
    assert "- json" in out


def test_run_argv_binds_loopback_only_and_is_shell_free() -> None:
    argv = sx._run_argv(
        docker="/usr/bin/docker",
        name="octopus-searxng",
        port="8888",
        settings_file="/var/lib/octopus/searxng/settings.yml",
        image="searxng/searxng:pin",
    )
    assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
    # Security: published port is loopback-bound, never 0.0.0.0 / all-interfaces.
    pub = argv[argv.index("-p") + 1]
    assert pub == "127.0.0.1:8888:8080"
    assert not any(a == "0.0.0.0" or a.startswith("0.0.0.0:") for a in argv)
    # settings.yml is mounted read-only; image is the final positional arg.
    assert argv[argv.index("-v") + 1].endswith(":/etc/searxng/settings.yml:ro")
    assert argv[-1] == "searxng/searxng:pin"
    # No shell metacharacters smuggled into any token.
    assert not any(ch in tok for tok in argv for ch in ("&", "|", ";", "$", "`"))


def _restart(**over):
    base = dict(
        up=False,
        managed=True,
        container_running=False,
        docker_present=True,
        now=1000.0,
        last_restart=0.0,
        backoff_s=30.0,
    )
    base.update(over)
    return sx._should_restart(**base)


def test_should_restart_truth_table() -> None:
    # The one case that relaunches: down, managed, docker present, not running, past backoff.
    assert _restart() is True
    # Up → never restart.
    assert _restart(up=True) is False
    # Unmanaged (external SearXNG) → observe, don't touch.
    assert _restart(managed=False) is False
    # Container already (re)booting → don't double-launch.
    assert _restart(container_running=True) is False
    # No Docker → nothing to do.
    assert _restart(docker_present=False) is False
    # Within the backoff window → wait.
    assert _restart(now=1000.0, last_restart=980.0, backoff_s=30.0) is False
