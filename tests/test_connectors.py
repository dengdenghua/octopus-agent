"""连接器认证编排层测试:加密凭据库 + 注册表 + auth 编排器 + 网关路由。"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import stat
from pathlib import Path

import pytest

from runtime.platform.connectors.auth_orchestrator import AuthOrchestrator
from runtime.platform.connectors.connector_registry import ConnectorRegistry
from runtime.platform.connectors.credential_store import CredentialStore

# 仓库内 WorkBuddy 连接器 fork(与 ConnectorRegistry 默认一致)
FORK = Path(__file__).resolve().parents[1] / "extensions" / "workbuddy-connectors"


class TestCredentialStore:
    def test_root_override_owns_default_files(self, tmp_path):
        root = tmp_path / "isolated-connectors"

        store = CredentialStore(root=root)
        store.set_secret("x", "token", "secret")

        assert (root / "master.key").is_file()
        assert (root / "credentials.v1.json").is_file()
        assert store.get_secret("x", "token") == "secret"

    def test_roundtrip_encrypted(self, tmp_path):
        s = CredentialStore(
            root=tmp_path,
            master_key_file=tmp_path / "key",
            credentials_file=tmp_path / "cred.json",
        )
        s.set_secret("westock-mcp", "access_token", "top-secret-42")
        assert s.get_secret("westock-mcp", "access_token") == "top-secret-42"
        assert s.has_credentials("westock-mcp")
        assert s.list_secrets("westock-mcp") == ["access_token"]

    def test_no_plaintext_on_disk(self, tmp_path):
        s = CredentialStore(
            root=tmp_path,
            master_key_file=tmp_path / "key",
            credentials_file=tmp_path / "cred.json",
        )
        s.set_secret("x", "api_key", "SUPER-SECRET-VALUE")
        raw = (tmp_path / "cred.json").read_text()
        assert "SUPER-SECRET-VALUE" not in raw
        assert '"nonce"' in raw and '"ciphertext"' in raw

    def test_delete_and_clear(self, tmp_path):
        s = CredentialStore(
            root=tmp_path,
            master_key_file=tmp_path / "key",
            credentials_file=tmp_path / "cred.json",
        )
        s.set_secret("a", "k1", "v1")
        s.set_secret("a", "k2", "v2")
        assert s.delete_secret("a", "k1") is True
        assert s.list_secrets("a") == ["k2"]
        assert s.clear_connector("a") is True
        assert not s.has_credentials("a")

    def test_concurrent_updates_do_not_lose_secrets(self, tmp_path):
        store = CredentialStore(root=tmp_path)

        def write(index: int) -> None:
            store.set_secret("parallel", f"key-{index}", f"value-{index}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(write, range(40)))

        assert set(store.list_secrets("parallel")) == {f"key-{index}" for index in range(40)}
        for index in range(40):
            assert store.get_secret("parallel", f"key-{index}") == f"value-{index}"

    def test_failed_atomic_replace_preserves_original_file(self, tmp_path, monkeypatch):
        store = CredentialStore(root=tmp_path)
        store.set_secret("x", "first", "value-1")
        credential_file = tmp_path / "credentials.v1.json"
        original = credential_file.read_bytes()
        real_replace = os.replace

        def fail_credential_replace(source, destination):
            if Path(destination) == credential_file:
                raise OSError("injected replace failure")
            real_replace(source, destination)

        monkeypatch.setattr(os, "replace", fail_credential_replace)
        with pytest.raises(OSError, match="injected replace failure"):
            store.set_secret("x", "second", "value-2")

        assert credential_file.read_bytes() == original
        assert store.get_secret("x", "first") == "value-1"
        assert store.get_secret("x", "second") is None
        assert not list(tmp_path.glob(".credentials.v1.json.*.tmp"))

    def test_existing_files_are_tightened_to_owner_only(self, tmp_path):
        store = CredentialStore(root=tmp_path)
        store.set_secret("x", "token", "secret")
        key_file = tmp_path / "master.key"
        credential_file = tmp_path / "credentials.v1.json"
        key_file.chmod(0o666)
        credential_file.chmod(0o666)

        CredentialStore(root=tmp_path)

        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600

    @pytest.mark.parametrize(
        "encoded_key",
        [b"not-base64!", base64.b64encode(b"too-short")],
    )
    def test_invalid_existing_master_key_fails_closed(self, tmp_path, encoded_key):
        key_file = tmp_path / "master.key"
        key_file.write_bytes(encoded_key)

        with pytest.raises(RuntimeError, match="connector master key"):
            CredentialStore(root=tmp_path)

        assert key_file.read_bytes() == encoded_key
        assert not (tmp_path / "credentials.v1.json").exists()

    def test_missing_master_key_for_existing_credentials_fails_closed(self, tmp_path):
        credential_file = tmp_path / "credentials.v1.json"
        credential_file.write_text(
            '{"version": 1, "connectors": {"x": {}}}',
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="master key is missing"):
            CredentialStore(root=tmp_path)

        assert not (tmp_path / "master.key").exists()


class TestConnectorRegistry:
    def test_list_fork(self):
        reg = ConnectorRegistry(marketplace_root=FORK)
        conns = reg.list()
        assert len(conns) == 108
        types = {c["type"] for c in conns}
        assert {"mcp", "cli", "skill-only"} <= types

    def test_get_details(self):
        reg = ConnectorRegistry(marketplace_root=FORK)
        feishu = reg.get("feishu")
        assert feishu is not None
        assert feishu.type == "cli"
        assert feishu.skill_count() >= 1
        assert feishu.cli.get("auth")

        westock = reg.get("westock-mcp")
        assert westock is not None
        assert "westock-mcp" in westock.mcp_servers
        assert westock.mcp_servers["westock-mcp"]["type"] == "streamableHttp"

    def test_install_uninstall_skills(self, tmp_path):
        reg = ConnectorRegistry(
            marketplace_root=FORK, skills_root=tmp_path / "skills", state_file=tmp_path / "st.json"
        )
        res = reg.install("westock-mcp")
        assert res["installed"] is True
        assert res["copied_skills"], "should have copied skills"
        assert reg.installed_ids() == {"westock-mcp"}
        # registry.json 登记
        regfile = tmp_path / "skills" / "registry.json"
        assert regfile.exists()
        names = [e["name"] for e in json.loads(regfile.read_text("utf-8"))]
        assert names, "registry should be rebuilt"

        assert reg.uninstall("westock-mcp") is True
        assert reg.installed_ids() == set()


class TestAuthOrchestrator:
    def test_token_connect_and_header_injection(self, tmp_path):
        creds = CredentialStore(
            root=tmp_path,
            master_key_file=tmp_path / "key",
            credentials_file=tmp_path / "cred.json",
        )
        rules = [
            {
                "id": "tencent-docs-dual-token",
                "applies_to_connectors": ["tencent-docs", "tencent-docs-oa"],
                "inject": [
                    {
                        "from_connector": "tencent-docs",
                        "token_type": "access_token",
                        "header": "Authorization",
                        "value_template": "Bearer ${access_token}",
                    }
                ],
            }
        ]
        orch = AuthOrchestrator(credentials=creds, auth_injection_rules=rules)
        reg = ConnectorRegistry(marketplace_root=FORK)
        conn = reg.get("tencent-docs")
        assert conn is not None

        orch.connect(conn, tokens={"access_token": "tok-ABC"})
        assert orch.status(conn)["connected"] is True
        headers = orch.resolve_headers(conn)
        assert headers.get("Authorization") == "Bearer tok-ABC"

        orch.disconnect(conn)
        assert orch.resolve_headers(conn) == {}
        assert orch.status(conn)["connected"] is False

    def test_env_resolution(self, tmp_path):
        creds = CredentialStore(
            root=tmp_path,
            master_key_file=tmp_path / "key",
            credentials_file=tmp_path / "cred.json",
        )
        orch = AuthOrchestrator(credentials=creds)
        reg = ConnectorRegistry(marketplace_root=FORK)
        conn = reg.get("feishu")
        orch.connect(conn, tokens={"LARK_TOKEN": "env-val"})
        env = orch.resolve_env(conn)
        assert env.get("LARK_TOKEN") == "env-val"


class TestConnectorRouter:
    def test_router_endpoints(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime.sensing.gateway.connector_router import create_connector_router

        reg = ConnectorRegistry(
            marketplace_root=FORK, skills_root=tmp_path / "skills", state_file=tmp_path / "st.json"
        )
        creds = CredentialStore(
            root=tmp_path,
            master_key_file=tmp_path / "key",
            credentials_file=tmp_path / "cred.json",
        )
        orch = AuthOrchestrator(credentials=creds)
        app = FastAPI()
        app.include_router(create_connector_router(registry=reg, orchestrator=orch))
        client = TestClient(app)

        r = client.get("/api/connectors", params={"limit": 500})
        assert r.status_code == 200
        assert r.json()["total"] == 108

        r = client.post("/api/connectors/westock-mcp/install")
        assert r.status_code == 200 and r.json()["installed"] is True

        r = client.post(
            "/api/connectors/westock-mcp/connect", json={"tokens": {"access_token": "abc"}}
        )
        assert r.status_code == 200 and r.json()["connected"] is True

        r = client.get("/api/connectors/westock-mcp/headers")
        assert r.status_code == 200
        assert r.json() == {
            "configured": True,
            "header_names": ["Authorization"],
        }
        assert "abc" not in r.text

        r = client.get("/api/connectors/nope")
        assert r.status_code == 404
