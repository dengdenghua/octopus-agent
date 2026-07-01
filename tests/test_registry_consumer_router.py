from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from octopus_runtime.client import (  # noqa: E402
    AssetContent,
    AssetPayload,
    BundleRef,
    RegistryAsset,
)
from octopus_runtime.materialize import materialize_skill  # noqa: E402
from runtime.sensing.gateway.registry_consumer_router import (  # noqa: E402
    create_registry_consumer_router,
)


class FakeRegistryClient:
    def __init__(self, _base_url: str) -> None:
        pass

    def list_assets(self, type_: str | None = None) -> list[RegistryAsset]:
        assets = [
            RegistryAsset(
                id="role/researcher",
                type="role",
                kind="data",
                name="Researcher",
                description="Research role",
                category="research",
                tags=["analysis"],
            ),
            RegistryAsset(
                id="twin-role/operator",
                type="twin-role",
                kind="data",
                name="Operator",
                description="Operator role",
                category="ops",
                tags=["ops"],
            ),
            RegistryAsset(
                id="plugin/browser-tool",
                type="plugin",
                kind="code",
                name="Browser Tool",
                description="Executable plugin",
                category="browser",
            ),
        ]
        return [asset for asset in assets if type_ is None or asset.type == type_]

    def list_skills(self) -> list[RegistryAsset]:
        return []

    def fetch(self, asset_id: str) -> AssetPayload:
        if asset_id == "role/researcher":
            return AssetPayload(
                id="role/researcher",
                type="role",
                kind="data",
                name="Researcher",
                description="Research role",
                category="research",
                tags=["analysis"],
                body="You are a careful researcher.",
            )
        if asset_id == "role/not-really-role":
            return AssetPayload(
                id="plugin/not-really-role",
                type="plugin",
                kind="code",
                name="Executable Plugin",
                description="Plugin returned from a role-looking request",
                category="browser",
                body="plugin manifest",
            )
        if asset_id == "plugin/browser-tool":
            return AssetPayload(
                id="plugin/browser-tool",
                type="plugin",
                kind="code",
                name="Browser Tool",
                description="Executable plugin",
                category="browser",
                body="plugin manifest",
            )
        raise KeyError(asset_id)


class FakeBundleClient:
    def __init__(self, bundle: bytes) -> None:
        self.bundle = bundle

    def fetch_bundle(self, _asset_id: str) -> bytes:
        return self.bundle


def _tar_bytes(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, body in files.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    import octopus_runtime
    from runtime.execution.agents import loader

    monkeypatch.setattr(octopus_runtime, "RegistryClient", FakeRegistryClient)
    monkeypatch.setattr(loader, "default_agents_root", lambda: tmp_path / "agents")

    app = FastAPI()
    app.include_router(create_registry_consumer_router(registry_base="https://registry.test"))
    return TestClient(app)


def test_lists_registry_roles(client: TestClient) -> None:
    data = client.get("/api/registry/roles").json()

    assert data["source"] == "https://registry.test"
    assert data["total"] == 2
    assert {role["id"] for role in data["roles"]} == {
        "role/researcher",
        "twin-role/operator",
    }


def test_installs_registry_role_as_local_agent(client: TestClient, tmp_path) -> None:
    data = client.post("/api/registry/roles/role/researcher/install").json()

    assert data["installed"] is True
    assert data["agent_id"] == "registry_researcher"
    agent_root = tmp_path / "agents" / "registry_researcher"
    profile = json.loads((agent_root / "profile.jsonc").read_text(encoding="utf-8"))
    assert profile["source"] == "registry"
    assert profile["name"] == "Researcher"
    assert (agent_root / "agent-core" / "SOUL.md").read_text(
        encoding="utf-8"
    ) == "You are a careful researcher."


def test_rejects_role_install_for_non_role_asset(client: TestClient) -> None:
    resp = client.post("/api/registry/roles/roleplay/fake/install")

    assert resp.status_code == 400
    assert "not a role asset" in resp.json()["detail"]


def test_rejects_registry_payload_that_is_not_installable_role(
    client: TestClient, tmp_path
) -> None:
    resp = client.post("/api/registry/roles/role/not-really-role/install")

    assert resp.status_code == 400
    assert "not an installable role asset" in resp.json()["detail"]
    assert not (tmp_path / "agents" / "registry_not_really_role").exists()


def test_plugins_are_browsable_but_not_installable(client: TestClient) -> None:
    data = client.get("/api/registry/plugins").json()

    assert data["installable"] is False
    assert data["total"] == 1
    assert data["plugins"][0]["id"] == "plugin/browser-tool"

    detail = client.get("/api/registry/plugins/browser-tool").json()
    assert detail["installable"] is False
    assert detail["body_preview"] == "plugin manifest"


def test_materialize_skill_rejects_unsafe_registry_slug(tmp_path) -> None:
    payload = AssetPayload(
        id="skill/../../escape",
        type="skill",
        kind="data",
        name="Escape",
        description="unsafe path",
        body="never write outside skills root",
    )

    with pytest.raises(ValueError, match="unsafe skill (id|slug)"):
        materialize_skill(payload, tmp_path / "skills")

    assert not (tmp_path / "escape").exists()


def test_materialize_skill_extracts_full_bundle_under_matching_slug(tmp_path) -> None:
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="bundle",
        body="ignored when bundle exists",
        bundle=BundleRef(ref="bundle.tar.gz"),
    )
    bundle = _tar_bytes(
        {
            "research-pack/SKILL.md": "---\nname: Research Pack\n---\n\nUse sources.",
            "research-pack/references/source-policy.md": "cite primary sources",
        }
    )

    md = materialize_skill(payload, tmp_path / "skills", client=FakeBundleClient(bundle))

    assert md == tmp_path / "skills" / "research-pack" / "SKILL.md"
    assert md.read_text(encoding="utf-8").endswith("Use sources.")
    assert (
        tmp_path / "skills" / "research-pack" / "references" / "source-policy.md"
    ).read_text(encoding="utf-8") == "cite primary sources"


def test_materialize_skill_rejects_bundle_that_writes_other_skill_dir(tmp_path) -> None:
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="bundle",
        bundle=BundleRef(ref="bundle.tar.gz"),
    )
    bundle = _tar_bytes(
        {
            "research-pack/SKILL.md": "safe skill",
            "other-pack/SKILL.md": "should not be written",
        }
    )

    with pytest.raises(ValueError, match="outside skill dir"):
        materialize_skill(payload, tmp_path / "skills", client=FakeBundleClient(bundle))

    assert not (tmp_path / "skills" / "research-pack").exists()
    assert not (tmp_path / "skills" / "other-pack").exists()


def test_materialize_skill_rejects_bundle_missing_skill_md_without_clobbering(
    tmp_path,
) -> None:
    existing = tmp_path / "skills" / "research-pack"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("old safe version", encoding="utf-8")
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="bundle",
        bundle=BundleRef(ref="bundle.tar.gz"),
    )
    bundle = _tar_bytes({"research-pack/README.md": "missing skill md"})

    with pytest.raises(ValueError, match="missing required file"):
        materialize_skill(payload, tmp_path / "skills", client=FakeBundleClient(bundle))

    assert (existing / "SKILL.md").read_text(encoding="utf-8") == "old safe version"


def test_materialize_skill_verifies_payload_bundle_checksum(tmp_path) -> None:
    bundle = _tar_bytes({"research-pack/SKILL.md": "new safe version"})
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="bundle",
        bundle=BundleRef(ref="bundle.tar.gz", checksum="sha256:" + ("0" * 64)),
    )

    with pytest.raises(ValueError, match="bundle checksum mismatch"):
        materialize_skill(payload, tmp_path / "skills", client=FakeBundleClient(bundle))

    assert not (tmp_path / "skills" / "research-pack").exists()


def test_materialize_skill_replaces_existing_bundle_after_checksum_match(tmp_path) -> None:
    existing = tmp_path / "skills" / "research-pack"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("old safe version", encoding="utf-8")
    bundle = _tar_bytes({"research-pack/SKILL.md": "new safe version"})
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="bundle",
        bundle=BundleRef(
            ref="bundle.tar.gz",
            checksum="sha256:" + hashlib.sha256(bundle).hexdigest(),
        ),
    )

    md = materialize_skill(payload, tmp_path / "skills", client=FakeBundleClient(bundle))

    assert md.read_text(encoding="utf-8") == "new safe version"


def test_materialize_skill_restores_existing_bundle_when_replace_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "skills" / "research-pack"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("old safe version", encoding="utf-8")
    bundle = _tar_bytes({"research-pack/SKILL.md": "new safe version"})
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="bundle",
        bundle=BundleRef(
            ref="bundle.tar.gz",
            checksum="sha256:" + hashlib.sha256(bundle).hexdigest(),
        ),
    )
    original_rename = Path.rename

    def fail_staged_replace(self: Path, target: Path) -> Path:
        if self.name == "research-pack" and self.parent.name.startswith(".research-pack."):
            raise OSError("replace failed")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_staged_replace)

    with pytest.raises(OSError, match="replace failed"):
        materialize_skill(payload, tmp_path / "skills", client=FakeBundleClient(bundle))

    assert (existing / "SKILL.md").read_text(encoding="utf-8") == "old safe version"


def test_materialize_skill_verifies_body_checksum_without_clobbering(tmp_path) -> None:
    existing = tmp_path / "skills" / "research-pack"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("old safe version", encoding="utf-8")
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="body only",
        body="new instructions",
        content=AssetContent(checksum="sha256:" + ("0" * 64)),
    )

    with pytest.raises(ValueError, match="checksum mismatch"):
        materialize_skill(payload, tmp_path / "skills")

    assert (existing / "SKILL.md").read_text(encoding="utf-8") == "old safe version"


def test_materialize_skill_writes_body_only_atomically_after_checksum_match(
    tmp_path,
) -> None:
    body = "new instructions"
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="body only",
        body=body,
        content=AssetContent(checksum="sha256:" + hashlib.sha256(body.encode()).hexdigest()),
    )

    md = materialize_skill(payload, tmp_path / "skills")

    assert md == tmp_path / "skills" / "research-pack" / "SKILL.md"
    text = md.read_text(encoding="utf-8")
    assert "source: registry" in text
    assert text.endswith("new instructions\n")


def test_materialize_skill_keeps_existing_body_only_file_when_replace_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "skills" / "research-pack"
    existing.mkdir(parents=True)
    md = existing / "SKILL.md"
    md.write_text("old safe version", encoding="utf-8")
    payload = AssetPayload(
        id="skill/research-pack",
        type="skill",
        kind="data",
        name="Research Pack",
        description="body only",
        body="new instructions",
    )
    original_replace = Path.replace

    def fail_temp_replace(self: Path, target: Path) -> Path:
        if self.name.startswith(".SKILL.md.") and target.name == "SKILL.md":
            raise OSError("atomic replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_temp_replace)

    with pytest.raises(OSError, match="atomic replace failed"):
        materialize_skill(payload, tmp_path / "skills")

    assert md.read_text(encoding="utf-8") == "old safe version"
    assert list(existing.glob(".SKILL.md.*")) == []
