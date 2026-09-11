from __future__ import annotations

import base64
import importlib.util
import json
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime.platform.plugins.cloud_catalog import CloudCatalog
from runtime.platform.plugins.marketplace_package import verify_marketplace_package_trust

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "extensions"
    / "workbuddy-experts"
    / "scripts"
    / "build-cloud-bundles.py"
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("test_build_cloud_bundles", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_single_skill_packages_round_trip_without_full_catalog_download(tmp_path, monkeypatch):
    from runtime.platform.plugins import cloud_catalog

    builder = _load_builder()
    source = tmp_path / "source"
    store = tmp_path / "store"
    out = tmp_path / "out"
    store.mkdir()
    out.mkdir()
    rows = []
    for name in ("alpha", "beta"):
        skill = source / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n{name}", encoding="utf-8")
        rows.append({"name": name, "download_url": "https://example.com/releases/all.tar.gz"})
    (store / "skill-registry.json").write_text(json.dumps({"skills": rows}), encoding="utf-8")
    monkeypatch.setattr(builder, "STORE_DATA", store)
    monkeypatch.setattr(builder, "BUILTIN_SKILLS", source)
    monkeypatch.setattr(builder, "REPOSITORY_SKILL_TREES", ())
    monkeypatch.setenv("CI", "true")
    builder.build_skills(out)
    catalog = CloudCatalog("skills", use_remote=False, use_cache=False)
    catalog._store = json.loads((store / "skill-registry.json").read_text())
    monkeypatch.setattr(cloud_catalog, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(
        cloud_catalog,
        "fetch_public_https_bytes",
        lambda url, **kw: (out / url.rsplit("/", 1)[1]).read_bytes(),
    )
    catalog.install_skill("alpha", skills_dir=tmp_path / "installed")
    assert (tmp_path / "installed/alpha/SKILL.md").is_file()
    assert not (tmp_path / "installed/beta").exists()
    assert len(list((tmp_path / "cache/skills").glob("*.tar.gz"))) == 1
    first_hashes = [row["package_sha256"] for row in catalog._store["skills"]]
    import os

    os.utime(source / "alpha/SKILL.md", (1, 1))
    builder.build_skills(out)
    rebuilt = json.loads((store / "skill-registry.json").read_text())
    assert [row["package_sha256"] for row in rebuilt["skills"]] == first_hashes


def test_plugin_content_builder_signs_codex_and_connector_packages(
    tmp_path: Path, monkeypatch
) -> None:
    builder = _load_builder()
    codex = tmp_path / "codex" / "documents"
    codex_manifest = codex / ".codex-plugin" / "plugin.json"
    codex_manifest.parent.mkdir(parents=True)
    codex_manifest.write_text(
        json.dumps({"name": "documents", "version": "1.0.0"}),
        encoding="utf-8",
    )
    codex_content = codex / "content.txt"
    codex_content.write_text("codex content", encoding="utf-8")
    codex_content.chmod(0o755)
    connector = tmp_path / "connectors" / "documents"
    connector.mkdir(parents=True)
    (connector / "cli.json").write_text('{"command":"documents"}', encoding="utf-8")
    connector_catalog = tmp_path / "connector-catalog.json"
    connector_catalog.write_text(
        json.dumps(
            {
                "connectors": [
                    {
                        "id": "documents",
                        "type": "mcp",
                        "auth_mode": "token",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    workbenches = tmp_path / "workbenches"
    workbenches.mkdir()
    monkeypatch.setattr(builder, "REPO_CODEX_PLUGINS", codex.parent)
    monkeypatch.setattr(builder, "CODEX_CACHE", cache)
    monkeypatch.setattr(builder, "CONNECTOR_ROOT", connector.parent)
    monkeypatch.setattr(builder, "CONNECTOR_CATALOG", connector_catalog)
    monkeypatch.setattr(builder, "WORKBENCH_ROOT", workbenches)

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv(
        "OCTOPUS_PLUGIN_SIGNING_PRIVATE_KEY",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    monkeypatch.setenv("OCTOPUS_PLUGIN_SIGNING_PUBLISHER_ID", "echoai")
    monkeypatch.setenv("OCTOPUS_PLUGIN_SIGNING_KEY_ID", "release-1")
    trust_store = tmp_path / "plugin-publishers.json"
    trust_store.write_text(
        json.dumps(
            {
                "schema": "octopus.plugin_publisher_trust_store.v1",
                "publishers": [
                    {
                        "publisher_id": "echoai",
                        "keys": [
                            {
                                "key_id": "release-1",
                                "algorithm": "ed25519",
                                "status": "active",
                                "public_key": base64.b64encode(public_bytes).decode("ascii"),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()

    builder.build_plugins(output)

    runtime_extracted = tmp_path / "runtime-extracted"
    for kind in ("codex", "connector"):
        package = CloudCatalog._extract_member(
            output / "octopus-plugins.tar.gz",
            f"plugins/{kind}",
            runtime_extracted / kind,
            "documents",
        )
        assert package is not None
        runtime_trust = verify_marketplace_package_trust(
            package,
            package_kind=kind,
            plugin_id="documents",
            expected_version="1.0.0",
            trust_store_path=trust_store,
            require_trusted=True,
        )
        assert runtime_trust["publisher_verified"] is True
        assert runtime_trust["host_api"] == ">=0.2,<0.3"
    connector_trust = verify_marketplace_package_trust(
        runtime_extracted / "connector" / "documents",
        package_kind="connector",
        plugin_id="documents",
        trust_store_path=trust_store,
        require_trusted=True,
    )
    assert connector_trust["permissions"] == [
        "account.credentials",
        "network.remote",
        "process.local",
    ]
    assert connector_trust["auth_modes"] == ["token"]
    assert (
        runtime_extracted / "codex" / "documents" / "content.txt"
    ).stat().st_mode & 0o777 == 0o755

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(output / "octopus-plugins.tar.gz", "r:gz") as archive:
        archive.extractall(extracted, filter="data")
    for kind in ("codex", "connector"):
        trust = verify_marketplace_package_trust(
            extracted / "plugins" / kind / "documents",
            package_kind=kind,
            plugin_id="documents",
            expected_version="1.0.0",
            trust_store_path=trust_store,
            require_trusted=True,
        )
        assert trust["publisher_verified"] is True
        assert trust["publisher_id"] == "echoai"
        assert trust["release_summary"].startswith("1.0.0：")

    assert not (codex / ".codex-plugin" / "provenance.json").exists()
    assert not (connector / ".octopus-connector").exists()
