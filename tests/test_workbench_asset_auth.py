import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.adapters.integrations.local_auth.router import create_local_auth_router
from runtime.platform.config.schema import LocalAuthConfig
from runtime.platform.plugins.workbench_package import WorkbenchPackageStore
from runtime.safety.auth.identity import IdentityStore
from runtime.sensing.gateway.workbench_packages_router import create_workbench_packages_router


def test_manifest_grants_only_authenticated_package_asset_access(tmp_path):
    for name in ("first", "second"):
        root = tmp_path / name
        (root / "dist").mkdir(parents=True)
        (root / "dist" / "index.html").write_text("<h1>Workbench</h1>")
        (root / "app.json").write_text(
            json.dumps(
                {
                    "schema": "octopus.workbench_app.v1",
                    "id": name,
                    "route": "/workspace/example",
                    "module_id": "example",
                    "entry": "dist/index.html",
                    "version": "1.0.0",
                }
            )
        )
    identities = IdentityStore()
    config = LocalAuthConfig(
        enabled=True, allow_any_username=True, jwt_secret="Test-Workbench-Auth-Secret-123456!"
    )
    app = FastAPI()
    app.include_router(create_local_auth_router(config=config, identity_store=identities))
    app.include_router(
        create_workbench_packages_router(
            WorkbenchPackageStore(tmp_path),
            identity_store=identities,
            require_auth=True,
            jwt_secret=config.jwt_secret,
            jwt_issuer=config.jwt_issuer,
        )
    )
    base = "/api/workbench-packages"
    with TestClient(app) as client:
        assert client.get(f"{base}/first/assets/dist/index.html").status_code == 401
        login = client.post("/api/auth/local/login", json={"username": "reader"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        manifest = client.get(f"{base}/first/manifest", headers=headers)
        assert manifest.status_code == 200
        assert "HttpOnly" in manifest.headers["set-cookie"]
        asset = client.get(f"{base}/first/assets/dist/index.html")
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "private, no-cache"
        capability = client.cookies.get("octopus_workbench_assets")
        cookie = {"Cookie": "octopus_workbench_assets=" + capability}
        assert (
            client.get(f"{base}/second/assets/dist/index.html", headers=cookie).status_code == 401
        )
        assert client.get(f"{base}/first/manifest", headers=cookie).status_code == 401
        assert (
            client.get(
                "/api/auth/local/whoami",
                headers={
                    "Authorization": "Bearer " + capability,
                },
            ).status_code
            == 401
        )
        bad_cookie = {"Cookie": "octopus_workbench_assets=" + capability + "tamper"}
        assert (
            client.get(f"{base}/first/assets/dist/index.html", headers=bad_cookie).status_code
            == 401
        )
