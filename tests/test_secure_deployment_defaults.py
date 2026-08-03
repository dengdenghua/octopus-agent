"""Regression checks for safe, copy-pasteable deployment defaults."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_services_bind_control_plane_to_loopback_by_default() -> None:
    expected = "${OCTOPUS_BIND_IP:-127.0.0.1}:${PORT:-8000}:8000"
    for filename in ("docker-compose.yml", "docker-compose.full.yml"):
        compose = yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))
        assert expected in compose["services"]["octopus-agent"]["ports"]


def test_documented_docker_command_does_not_publish_on_all_interfaces() -> None:
    deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "docker run --rm -p 127.0.0.1:8000:8000" in deployment
    assert "docker run --rm -p 127.0.0.1:8000:8000" in dockerfile
    assert "docker run --rm -p 8000:8000" not in deployment


def test_example_local_auth_does_not_accept_arbitrary_usernames() -> None:
    config = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))

    assert config["local_auth"]["enabled"] is False
    assert config["local_auth"]["allow_any_username"] is False
    assert config["local_auth"]["allowed_usernames"] == []


def test_security_policy_contains_no_placeholder_contact_or_key() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "security@octopus-agent.local" not in policy
    assert "PGP key 待添加" not in policy
    assert "Report a vulnerability" in policy
