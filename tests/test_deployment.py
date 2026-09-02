"""Implementation note."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from runtime.platform.config import load_from_yaml

REPO = Path(__file__).parent.parent


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestDockerfile:
    def test_dockerfile_exists(self):
        assert (REPO / "Dockerfile").exists()

    def test_frontend_install_uses_supported_locked_pnpm_flags(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")

        assert "pnpm install --frozen-lockfile" in text
        assert "--no-fund" not in text
        assert "frontend/pnpm-workspace.yaml" in text
        assert (
            "COPY pet-sidecar/models/octopus/octopus.fbx /pet-sidecar/models/octopus/octopus.fbx"
        ) in text
        assert (
            "COPY pet-sidecar/models/character_rigged_clean.glb "
            "/pet-sidecar/models/character_rigged_clean.glb"
        ) in text

    def test_full_stack_state_cleanup_runs_once_before_backend_start(self):
        config = (REPO / "frontend/playwright.full.config.ts").read_text(encoding="utf-8")
        preparer = REPO / "frontend/e2e/prepare-full-stack-state.mjs"

        assert preparer.is_file()
        assert "rmSync(e2eStateRoot" not in config
        assert "prepare-full-stack-state.mjs" in config
        assert "Refusing to reset E2E state outside" in preparer.read_text(encoding="utf-8")

    def test_dockerignore_exists(self):
        assert (REPO / ".dockerignore").exists()

    def test_desktop_quickstart_matches_linux_build_status(self):
        quickstart = (REPO / "docs" / "DEPLOYMENT_QUICKSTART.md").read_text(encoding="utf-8")
        linux_workflow = (REPO / ".github" / "workflows" / "build-linux.yml").read_text(
            encoding="utf-8"
        )

        assert "Build Linux AppImage" in linux_workflow
        assert "Linux AppImage builds are also" in quickstart
        assert "verified CI artifact rather than a public" in quickstart
        assert "macOS/Linux desktop releases\nare disabled" not in quickstart

    def test_multi_stage_build(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        # Implementation note.
        assert "AS runtime" in text
        # Implementation note.
        assert "AS builder" in text or "AS py-builder" in text
        # Implementation note.
        assert "COPY --from=" in text

    def test_non_root_user(self):
        """Implementation note."""
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        assert "USER octopus" in text
        # Implementation note.
        assert "useradd" in text
        assert "--uid 10001" in text

    def test_exposes_port(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        assert "EXPOSE 8000" in text

    def test_entrypoint_is_cli(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        assert 'ENTRYPOINT ["octopus-agent"]' in text
        assert "serve" in text  # Implementation note.

    def test_release_inputs_are_locked_and_multiarch_safe(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]

        assert from_lines
        assert all("@sha256:" in line for line in from_lines)
        assert (
            "node:22.23.2-alpine@sha256:"
            "c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32"
        ) in text
        assert (
            "python:3.12.11-slim-bookworm@sha256:"
            "519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7"
        ) in text
        assert (
            "ghcr.io/astral-sh/uv:0.11.25@sha256:"
            "1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9"
        ) in text
        assert "COPY pyproject.toml uv.lock" in text
        assert "uv sync --locked --no-dev --no-editable --no-sources" in text
        assert "pip install" not in text
        assert "OCTOPUS_DEPLOYMENT_MODE=production" in text
        assert "PYTHONPATH=" not in text

    def test_bubblewrap_package_is_arch_specific_and_hash_verified(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")

        assert "ARG TARGETARCH" in text
        assert "bubblewrap_0.8.0-2+deb12u1_${TARGETARCH}.deb" in text
        assert "3cc9134a3286ad01a323dcd924ba123eb634cefaeec82d774257e06308aeaadb" in text
        assert "d044ba1d7961d835669035fcd1e11121f1dc960a1a2e1c6489a93ea44e083557" in text
        assert "sha256sum --check --strict" in text
        assert "unsupported TARGETARCH" in text
        assert "dpkg --install /tmp/bubblewrap.deb" in text
        assert '"0.8.0-2+deb12u1"' in text
        assert "apt-get install" not in text

    def test_dockerignore_excludes_data_and_env(self):
        text = (REPO / ".dockerignore").read_text(encoding="utf-8")
        # Implementation note.
        for pattern in ["data/", "*.jsonl", "*.sqlite", ".env"]:
            assert pattern in text, f"missing .dockerignore entry: {pattern}"
        # Runtime state is only the repository-root data directory. An
        # unanchored rule also removes product assets such as
        # extensions/*/storefront/data/icons from the build context.
        assert all(line != "data/" for line in text.splitlines())
        assert "/data/" in text.splitlines()
        assert "agents/*/sessions/" in text
        assert "agents/*/workspace/" in text
        for local_state in (
            ".octopus/",
            ".octopus-*/",
            ".codex-audits/",
            ".agents/",
            "deliverables/",
            "config.local*.yaml",
        ):
            assert local_state in text

    def test_dockerignore_keeps_readme(self):
        """Implementation note."""
        text = (REPO / ".dockerignore").read_text(encoding="utf-8")
        assert "!README.md" in text

    def test_ci_smokes_installed_image_and_bundled_skills(self):
        yaml = pytest.importorskip("yaml")
        workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        steps = workflow["jobs"]["docker-build"]["steps"]
        named = {step.get("name"): step for step in steps if step.get("name")}
        smoke = named["Smoke installed image and bundled skill catalog"]["run"]
        assert "/etc/octopus/docker-smoke.yaml" in smoke
        assert "tests/fixtures/docker_smoke_config.yaml" in smoke
        assert "/readyz" in smoke
        assert "/api/health" in smoke
        assert "payload['skills'] >= 3" in smoke
        assert "resolve_process_backend('strict')" in smoke
        assert "assert choice.hard" in smoke
        assert "docker inspect --format '{{json .State}}'" in smoke
        assert "production container exited before readiness" in smoke
        assert "docker rm --force" in smoke

    def test_docker_smoke_config_is_offline_and_production_strict(self):
        cfg = load_from_yaml(REPO / "tests" / "fixtures" / "docker_smoke_config.yaml")

        assert cfg.execution.deployment_mode == "production"
        assert cfg.execution.process_sandbox == "strict"
        assert cfg.planner.model.startswith("mock/")
        assert cfg.intel_sources == []
        assert cfg.enable_web_skills is False
        assert cfg.tentacle.enabled is False


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestDockerCompose:
    def test_lightweight_cloud_edge_compose_is_loopback_and_bounded(self):
        yaml = pytest.importorskip("yaml")
        path = REPO / "deploy" / "cloud-edge-compose.yml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        service = doc["services"]["account-message-service"]
        assert service["ports"] == [
            "${OCTOPUS_CLOUD_EDGE_BIND_IP:-127.0.0.1}:${OCTOPUS_CLOUD_EDGE_PORT:-8090}:8090"
        ]
        assert service["deploy"]["resources"]["limits"]["memory"] == "512M"
        assert "OCTOPUS_CLOUD_EDGE_TOKEN_SECRET" in service["environment"]
        assert "OCTOPUS_CLOUD_EDGE_ADMIN_KEY" in service["environment"]
        assert "OCTOPUS_CLOUD_REGISTRATION_CODE" in service["environment"]
        assert "OCTOPUS_CLOUD_SHARE_RELAY_KEY" in service["environment"]
        assert "OCTOPUS_PUBLIC_SHARE_BASE_URL" in service["environment"]
        assert "OCTOPUS_CLOUD_EDGE_SHARE_TTL_SECONDS" in service["environment"]
        assert "OCTOPUS_CLOUD_EDGE_SHARE_MAX_PER_OWNER" in service["environment"]
        assert "OCTOPUS_CLOUD_EDGE_SHARE_MAX_SNAPSHOT_BYTES" in service["environment"]
        assert "OCTOPUS_CLOUD_EDGE_SHARE_MAX_TOTAL_BYTES" in service["environment"]
        assert "../data/cloud-edge:/data" in service["volumes"]
        assert service["build"]["dockerfile"] == "deploy/cloud-service.Dockerfile"
        assert service["image"] == "octopus-cloud-service:latest"
        assert service["entrypoint"] == ["python", "-m", "uvicorn"]

    def test_public_share_vhost_uses_body_token_and_keeps_relay_loopback(self):
        text = (REPO / "deploy" / "share.echo-age.com.nginx.conf").read_text(encoding="utf-8")
        assert "location = /api/public/thread-shares/resolve" in text
        assert "location = /api/v1/public/thread-shares/resolve" in text
        assert "proxy_pass http://127.0.0.1:8090" in text
        assert "location ^~ /api/public/thread-shares/" in text
        assert "access_log off" in text
        assert "before following the redirect" in text
        assert "Content-Security-Policy" in text
        assert 'X-Robots-Tag "noindex, nofollow, noarchive"' in text
        assert "log_format octopus_share_safe" in text
        assert "share.echo-age.com.access.log octopus_share_safe" in text
        assert "limit_req_zone $binary_remote_addr zone=octopus_share_read_per_ip" in text
        assert "limit_req zone=octopus_share_read_per_ip" in text
        assert "limit_req zone=octopus_share_manage_per_ip" in text

    def test_compose_file_valid_yaml(self):
        yaml = pytest.importorskip("yaml")
        path = REPO / "docker-compose.yml"
        assert path.exists()
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(doc, dict)
        assert "services" in doc
        assert "octopus-agent" in doc["services"]

    def test_compose_mounts_data_volume(self):
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
        svc = doc["services"]["octopus-agent"]
        vols = svc.get("volumes", [])
        assert any("./data:/data" in v for v in vols), "需要把 ./data:/data 挂上做 journal 持久化"

    def test_compose_persists_mutable_resource_catalog(self):
        yaml = pytest.importorskip("yaml")
        for filename in ("docker-compose.yml", "docker-compose.full.yml"):
            doc = yaml.safe_load((REPO / filename).read_text(encoding="utf-8"))
            volumes = doc["services"]["octopus-agent"]["volumes"]
            assert "octopus-resources:/app/resources" in volumes
            assert doc["volumes"]["octopus-resources"]["name"] == "octopus-resources"

    def test_make_compose_bootstrap_does_not_start_unauthenticated_template(self):
        makefile = (REPO / "Makefile").read_text(encoding="utf-8")
        assert "enable oct or local_auth with a strong secret" in makefile
        assert "created config.yaml/.env" in makefile
        assert "test -f config.yaml || cp config.example.yaml config.yaml" not in makefile

    def test_compose_mounts_config_readonly(self):
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
        svc = doc["services"]["octopus-agent"]
        vols = svc.get("volumes", [])
        assert any(":ro" in v and "config" in v for v in vols)

    def test_compose_command_uses_serve(self):
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
        svc = doc["services"]["octopus-agent"]
        cmd = svc.get("command", [])
        # Implementation note.
        assert "serve" in cmd
        assert "--config" in cmd

    def test_compose_has_healthcheck(self):
        yaml = pytest.importorskip("yaml")
        for filename in ("docker-compose.yml", "docker-compose.full.yml"):
            doc = yaml.safe_load((REPO / filename).read_text(encoding="utf-8"))
            svc = doc["services"]["octopus-agent"]
            hc = svc.get("healthcheck")
            assert hc is not None
            assert "test" in hc
            test_cmd = " ".join(hc["test"]) if isinstance(hc["test"], list) else hc["test"]
            assert "/readyz" in test_cmd
            assert "/api/health" not in test_cmd

    def test_full_compose_redis_healthcheck_receives_required_secret(self):
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load((REPO / "docker-compose.full.yml").read_text(encoding="utf-8"))
        redis = doc["services"]["redis"]

        assert redis["environment"]["REDIS_PASSWORD"].startswith("${REDIS_PASSWORD:?")
        assert redis["environment"]["REDISCLI_AUTH"].startswith("${REDIS_PASSWORD:?")
        assert "environment" not in redis["healthcheck"]
        assert redis["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]

    def test_full_compose_redis_image_is_version_and_digest_pinned(self):
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load((REPO / "docker-compose.full.yml").read_text(encoding="utf-8"))

        assert doc["services"]["redis"]["image"] == (
            "redis:7.4.11-alpine@sha256:"
            "ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf"
        )

    def test_compose_forwards_config_auth_secrets(self):
        yaml = pytest.importorskip("yaml")
        for filename in ("docker-compose.yml", "docker-compose.full.yml"):
            doc = yaml.safe_load((REPO / filename).read_text(encoding="utf-8"))
            environment = doc["services"]["octopus-agent"]["environment"]
            assert environment["OCTOPUS_LOCAL_AUTH_JWT_SECRET"] == (
                "${OCTOPUS_LOCAL_AUTH_JWT_SECRET:-}"
            )
            assert environment["OCTOPUS_ADMIN_PASSWORD_HASH"] == (
                "${OCTOPUS_ADMIN_PASSWORD_HASH:-}"
            )
            assert environment["OCTOPUS_CLOUD_EDGE_TOKEN_SECRET"] == (
                "${OCTOPUS_CLOUD_EDGE_TOKEN_SECRET:-}"
            )
            assert environment["OCTOPUS_PUBLIC_SHARE_RELAY_URL"] == (
                "${OCTOPUS_PUBLIC_SHARE_RELAY_URL:-}"
            )
            assert environment["OCTOPUS_PUBLIC_SHARE_RELAY_API_KEY"] == (
                "${OCTOPUS_PUBLIC_SHARE_RELAY_API_KEY:-}"
            )
            assert environment["OCTOPUS_PUBLIC_SHARE_RELAY_BEARER_TOKEN"] == (
                "${OCTOPUS_PUBLIC_SHARE_RELAY_BEARER_TOKEN:-}"
            )

    def test_compose_restart_policy(self):
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
        svc = doc["services"]["octopus-agent"]
        assert svc.get("restart") in ("unless-stopped", "always", "on-failure")


# ═══════════════════════════════════════════════════════════
# pyproject · console_scripts + optional extras
# ═══════════════════════════════════════════════════════════


class TestPyproject:
    def test_release_coverage_gate_measures_shippable_runtime(self):
        project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

        assert project["tool"]["coverage"]["run"]["source"] == ["runtime"]
        assert project["tool"]["coverage"]["report"]["fail_under"] == 77.5

    def test_dev_extra_covers_unconditionally_collected_optional_surfaces(self):
        project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        dev = "\n".join(project["project"]["optional-dependencies"]["dev"])

        for dependency in (
            "a2a-sdk",
            "av",
            "bcrypt",
            "mcp",
            "opentelemetry-api",
            "opentelemetry-sdk",
            "playwright",
        ):
            assert dependency in dev

    def test_octopus_agent_script_registered(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert 'octopus-agent = "runtime.cli:main"' in text

    def test_serve_extra_declared(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "serve" in text
        assert "fastapi" in text
        assert "uvicorn" in text

    def test_anthropic_extra_declared(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "anthropic = [" in text

    def test_mcp_extra_declared(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "mcp = [" in text

    def test_browser_extra_declared(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "browser = [" in text
        assert "playwright" in text


# ═══════════════════════════════════════════════════════════
# .env.example + DEPLOY.md
# ═══════════════════════════════════════════════════════════


class TestDocumentation:
    def test_env_example_exists_and_has_placeholders(self):
        path = REPO / ".env.example"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" in text
        # Implementation note.
        for line in text.splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                assert line.endswith("=") or "sk-" not in line
        assert "REDIS_PASSWORD=\n" in text
        assert "GRAFANA_PASSWORD=\n" in text
        assert "change-me-redis" not in text
        assert "change-me-grafana" not in text
        assert "openssl rand -hex 32" in text

    def test_deploy_md_exists(self):
        # Implementation note.
        # Implementation note.
        path = REPO / "docs" / "deployment.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        for section in ["Docker", "docker compose", "/livez", "/readyz", "/api/health"]:
            assert section in text

    def test_license_present_and_apache2(self):
        """Implementation note."""
        path = REPO / "LICENSE"
        assert path.exists(), "LICENSE file missing"
        text = path.read_text(encoding="utf-8")
        assert "Apache License" in text
        assert "Version 2.0" in text

    def test_gitignore_present_and_excludes_secrets(self):
        path = REPO / ".gitignore"
        assert path.exists(), ".gitignore missing"
        text = path.read_text(encoding="utf-8")
        for pat in ["__pycache__/", ".env", "data/", "*.jsonl", "*.sqlite"]:
            assert pat in text, f"missing .gitignore entry: {pat}"
        # Implementation note.
        assert "!.env.example" in text
        assert "!config.example.yaml" in text

    def test_contributing_md_exists(self):
        path = REPO / "CONTRIBUTING.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        for section in ["pytest", "lint", "Apache-2.0"]:
            assert section in text

    def test_pyproject_urls_not_example(self):
        """Implementation note."""
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "github.com/example" not in text, (
            "pyproject.toml still has github.com/example placeholder URL"
        )

    def test_english_readme_present(self):
        """Implementation note."""
        path = REPO / "README.en.md"
        assert path.exists(), "README.en.md missing"
        text = path.read_text(encoding="utf-8")
        for section in [
            "Quick Start",
            "CLI",
            "Reflection closure",
            "Apache-2.0",
            "OpenAI",
        ]:
            assert section in text, f"README.en.md missing section: {section}"

    def test_chinese_readme_links_to_english(self):
        """Implementation note."""
        text = (REPO / "README.md").read_text(encoding="utf-8")
        assert "README.en.md" in text
