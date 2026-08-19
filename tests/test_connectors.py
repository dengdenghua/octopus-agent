"""连接器认证编排层测试:加密凭据库 + 注册表 + auth 编排器 + 网关路由。"""
from __future__ import annotations

import json
from pathlib import Path

from runtime.platform.connectors.auth_orchestrator import AuthOrchestrator
from runtime.platform.connectors.connector_registry import ConnectorRegistry
from runtime.platform.connectors.credential_store import CredentialStore

# 仓库内 WorkBuddy 连接器 fork(与 ConnectorRegistry 默认一致)
FORK = Path(__file__).resolve().parents[1] / "extensions" / "workbuddy-connectors"


class TestCredentialStore:
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
        assert r.json()["headers"].get("Authorization") == "Bearer abc"

        r = client.get("/api/connectors/nope")
        assert r.status_code == 404
