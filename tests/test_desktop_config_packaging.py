"""Desktop packaging must materialize a loadable per-install auth secret."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from runtime.platform.config import load_from_yaml

pytestmark = [pytest.mark.contract, pytest.mark.platform]

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging/desktop/config.desktop.yaml"
MATERIALIZER = ROOT / "frontend/electron/desktop-config.cjs"
MAIN = ROOT / "frontend/electron/main.cjs"
DESKTOP_PROTOCOL = ROOT / "frontend/electron/desktop-protocol.cjs"
BACKEND_RUNTIME = ROOT / "frontend/electron/backend-runtime.cjs"
BUILD_CONFIG = ROOT / "packaging/desktop/build.yml"
WINDOWS_WORKFLOW = ROOT / ".github/workflows/build-win.yml"
LINUX_WORKFLOW = ROOT / ".github/workflows/build-linux.yml"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
LEGACY_PACKAGE = ROOT / "extras/desktop/package.json"
FRONTEND_PACKAGE = ROOT / "frontend/package.json"
BACKEND_BUILD = ROOT / "extras/desktop/build-backend-win.cjs"
CODEX_PREPARE = ROOT / "extras/desktop/prepare-codex-win.cjs"
CODEX_LICENSE_GENERATOR = ROOT / "extras/desktop/generate-codex-third-party-licenses.py"
CODEX_NATIVE_LICENSE_GENERATOR = ROOT / "extras/desktop/generate-codex-native-notices.py"
FRONTEND_LOCK = ROOT / "frontend/pnpm-lock.yaml"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
ACTIONS_SETUP_NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
ACTIONS_SETUP_PYTHON = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
ASTRAL_SETUP_UV = "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86"
CODEX_BUNDLE_EXECUTABLES = (
    "bin/codex.exe",
    "bin/codex-code-mode-host.exe",
    "codex-resources/codex-command-runner.exe",
    "codex-resources/codex-windows-sandbox-setup.exe",
    "codex-path/rg.exe",
)
CODEX_BUNDLE_LICENSE_SOURCES = {
    "LICENSE": ROOT / "extras/desktop/licenses/codex-0.149.0/LICENSE",
    "NOTICE": ROOT / "extras/desktop/licenses/codex-0.149.0/NOTICE",
    "third-party/codex-rust/THIRD_PARTY_LICENSES-codex-cli.html": (
        ROOT / "extras/desktop/licenses/codex-0.149.0/THIRD_PARTY_LICENSES-codex-cli.html"
    ),
    "third-party/codex-rust/THIRD_PARTY_LICENSES-code-mode-host.html": (
        ROOT / "extras/desktop/licenses/codex-0.149.0/THIRD_PARTY_LICENSES-code-mode-host.html"
    ),
    "third-party/codex-rust/THIRD_PARTY_LICENSES-windows-sandbox.html": (
        ROOT / "extras/desktop/licenses/codex-0.149.0/THIRD_PARTY_LICENSES-windows-sandbox.html"
    ),
    "third-party/codex-rust/README.md": (
        ROOT / "extras/desktop/licenses/codex-0.149.0/THIRD_PARTY_LICENSES.md"
    ),
    "third-party/codex-native/NATIVE_PROVENANCE.json": (
        ROOT / "extras/desktop/licenses/codex-0.149.0/NATIVE_PROVENANCE.json"
    ),
    "third-party/codex-native/NATIVE_THIRD_PARTY_NOTICES.md": (
        ROOT / "extras/desktop/licenses/codex-0.149.0/NATIVE_THIRD_PARTY_NOTICES.md"
    ),
    "third-party/ratatui/LICENSE": (ROOT / "extras/desktop/licenses/ratatui-0.30.2/LICENSE"),
    "third-party/ripgrep/COPYING": (ROOT / "extras/desktop/licenses/ripgrep-15.2.0/COPYING"),
    "third-party/ripgrep/THIRD_PARTY_LICENSES.html": (
        ROOT / "extras/desktop/licenses/ripgrep-15.2.0/THIRD_PARTY_LICENSES-ripgrep.html"
    ),
    "third-party/ripgrep/THIRD_PARTY_LICENSES.md": (
        ROOT / "extras/desktop/licenses/ripgrep-15.2.0/THIRD_PARTY_LICENSES.md"
    ),
    "third-party/ripgrep/LICENSE-MIT": (
        ROOT / "extras/desktop/licenses/ripgrep-15.2.0/LICENSE-MIT"
    ),
    "third-party/ripgrep/UNLICENSE": (ROOT / "extras/desktop/licenses/ripgrep-15.2.0/UNLICENSE"),
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _materialize_packaged_codex_bundle(resources: Path) -> Path:
    codex_root = resources / "codex"
    payloads: dict[str, bytes] = {relative: b"MZfixture" for relative in CODEX_BUNDLE_EXECUTABLES}
    payloads["codex-package.json"] = b'{"name":"codex-test-fixture"}\n'
    payloads.update(
        {relative: source.read_bytes() for relative, source in CODEX_BUNDLE_LICENSE_SOURCES.items()}
    )
    for relative, payload in payloads.items():
        target = codex_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    manifest = {
        "schema": "octopus.codex_bundle.v1",
        "package": "@openai/codex",
        "version": "0.149.0",
        "platformPackage": "@openai/codex-win32-x64",
        "platformPackageIntegrity": (
            "sha512-qKbwSOOO/fdhQ5MlXE2fts6taPxRPZ/zqeC+eqHD72hLRymV9rFCUbUxOCquogn"
            "UPRPvS/2/kRCV0UVhoDd3yQ=="
        ),
        "target": "x86_64-pc-windows-msvc",
        "fileHashPhase": "pre-authenticode",
        "licenses": {
            "codex": {
                "version": "0.149.0",
                "sourceTag": "rust-v0.149.0",
                "sourceCommit": "758ef40f50c1a458425c7cfbf1eb12cbc07af0b0",
                "cargoLockSha256": (
                    "0c32858e9c47d0acf82735c8620c96840a5381152eec63acad15d1acadb9edad"
                ),
                "cargoAboutVersion": "0.9.2",
            },
            "native": {
                "schemaVersion": "codex-native-notices.v1",
                "provenanceSha256": (
                    "65e2c0c7f7b239ee758133ce17cfb680bc38aec84876ca81015458c41a988c7a"
                ),
                "noticeSha256": (
                    "da7997facd0e36f4ebca01594c60abdc1204f5421a35d28c4760b13addf247c5"
                ),
                "componentCount": 12,
                "licenseInputCount": 80,
            },
            "ratatui": {
                "version": "0.30.2",
                "crateSha256": ("3274ba0a2c5e1bcad2a2005d20f4dc59dad26b2eb0940fb094500dba4099d57d"),
            },
            "ripgrep": {
                "version": "15.2.0",
                "sourceTag": "15.2.0",
                "sourceCommit": "e89fff89ac9af12e8d4ce9d5fd07beb408ca730f",
                "cargoLockSha256": (
                    "7a7d39cda8a03930e578f1dbb724e055771901842eca239e03b01e19da946a64"
                ),
                "cargoAboutVersion": "0.9.2",
                "releaseFeatures": ["pcre2"],
                "windowsArchiveSha256": (
                    "71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5"
                ),
                "windowsExecutableSha256": (
                    "14231169855ec5205cf5a1b6f1db358ff4aed4247c86b69ce8aae647c77f6680"
                ),
            },
        },
        "files": {relative: _sha256(payload) for relative, payload in payloads.items()},
    }
    (codex_root / "octopus-codex-bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    return codex_root / "bin/codex.exe"


def _materialize(target: Path) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the Electron-to-Python config contract")
    script = (
        "const m=require(process.argv[1]);"
        "const result=m.ensureDesktopConfigFile({"
        "bundledPath:process.argv[2],targetPath:process.argv[3]});"
        "process.stdout.write(JSON.stringify(result));"
    )
    result = subprocess.run(
        [node, "-e", script, str(MATERIALIZER), str(TEMPLATE), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _seed_resources(target: Path) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the desktop resource contract")
    script = (
        "const m=require(process.argv[1]);"
        "const result=m.ensureDesktopResources({"
        "bundledRoot:process.argv[2],targetRoot:process.argv[3]});"
        "process.stdout.write(JSON.stringify(result));"
    )
    result = subprocess.run(
        [node, "-e", script, str(MATERIALIZER), str(ROOT), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _local_secret(path: Path) -> str:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return str(raw["local_auth"]["jwt_secret"])


def test_electron_materialized_desktop_config_loads_in_python(tmp_path: Path) -> None:
    target = tmp_path / "user-data/config.yaml"

    first = _materialize(target)
    first_secret = _local_secret(target)
    config = load_from_yaml(target)

    assert first == {"path": str(target), "changed": True}
    assert config.planner.model == "octopus-agent"
    assert config.oct.enabled is True
    assert config.oct.jwt_secret == first_secret
    assert config.local_auth.enabled is True
    assert config.local_auth.jwt_secret == first_secret
    assert len(first_secret) >= 64
    assert "change-me" not in first_secret
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    second = _materialize(target)
    assert second == {"path": str(target), "changed": False}
    assert _local_secret(target) == first_secret


def test_two_desktop_installations_never_share_a_template_secret(tmp_path: Path) -> None:
    left = tmp_path / "left/config.desktop.yaml"
    right = tmp_path / "right/config.desktop.yaml"

    _materialize(left)
    _materialize(right)

    assert _local_secret(left) != _local_secret(right)


def test_desktop_resources_are_seeded_into_writable_user_data(tmp_path: Path) -> None:
    target = tmp_path / "user-data/resources"

    result = _seed_resources(target)

    assert result == {"path": str(target)}
    assert (target / "skills.lock.json").is_file()
    assert any((target / "agents").glob("*/profile.jsonc"))
    assert any((target / "prompts").rglob("*.yaml"))
    assert not any((target / "agents").rglob("*.jsonl"))
    assert not any(path.name in {"sessions", "workspace"} for path in target.rglob("*"))


def test_desktop_resource_seed_never_overwrites_mutable_user_data(tmp_path: Path) -> None:
    target = tmp_path / "user-data/resources"
    source_agent_file = next((ROOT / "agents").glob("*/profile.jsonc"))
    relative_agent_file = source_agent_file.relative_to(ROOT)
    mutable_agent_file = target / relative_agent_file
    mutable_agent_file.parent.mkdir(parents=True)
    mutable_agent_file.write_text("user-owned-agent", encoding="utf-8")
    mutable_lock = target / "skills.lock.json"
    mutable_lock.write_text("user-owned-lock", encoding="utf-8")

    _seed_resources(target)

    assert mutable_agent_file.read_text(encoding="utf-8") == "user-owned-agent"
    assert mutable_lock.read_text(encoding="utf-8") == "user-owned-lock"
    assert any((target / "prompts").rglob("*.yaml"))


def test_existing_legacy_weak_desktop_secret_is_atomically_migrated(tmp_path: Path) -> None:
    target = tmp_path / "user-data/config.yaml"
    target.parent.mkdir(parents=True)
    legacy = TEMPLATE.read_text(encoding="utf-8").replace(
        "__OCTOPUS_DESKTOP_LOCAL_AUTH_JWT_SECRET__",
        "octopus-desktop-local-jwt-secret-change-me",
    )
    target.write_text(legacy.replace("name: octopus-desktop", "name: retained-name"))

    result = _materialize(target)
    config = load_from_yaml(target)

    assert result["changed"] is True
    assert config.name == "retained-name"
    assert config.local_auth.jwt_secret != "octopus-desktop-local-jwt-secret-change-me"
    assert not list(target.parent.glob("*.tmp"))
    assert not list(target.parent.glob(".*.tmp"))


def test_desktop_main_fails_closed_before_spawning_backend() -> None:
    source = MAIN.read_text(encoding="utf-8")
    lifecycle = source[source.index("app.whenReady().then") :]
    backend_path = source[
        source.index("function backendConfigPath") : source.index("function backendProgress")
    ]
    materialize = lifecycle.index("ensureDesktopConfig();")
    spawn = lifecycle.index("spawnBackend(backendConfigPath()")

    assert "ensureDesktopConfigFile" in source
    assert "ensurePackagedResources();" in lifecycle
    # Brand name changed from "Octopus 启动失败" to "EchoAI 启动失败"
    assert (
        'dialog.showErrorBox("Octopus 启动失败"' in source
        or 'dialog.showErrorBox("EchoAI 启动失败"' in source
    )
    assert "app.exit(1);" in source
    assert materialize < spawn
    assert 'app.setAppUserModelId("ai.octopus.desktop")' in source
    assert 'path.join(app.getPath("userData"), "config.yaml")' in backend_path
    assert "config.desktop.yaml" not in backend_path


def test_desktop_renderer_uses_a_fixed_secure_origin_and_loopback_proxy() -> None:
    source = MAIN.read_text(encoding="utf-8")
    protocol_source = DESKTOP_PROTOCOL.read_text(encoding="utf-8")

    assert "protocol.registerSchemesAsPrivileged" in source
    assert "installDesktopRendererProtocol();" in source
    assert "DESKTOP_APP_ENTRY_URL" in source
    assert "loadFile(" not in source
    assert "webSecurity: false" not in source
    assert 'DESKTOP_APP_SCHEME = "octopus-app"' in protocol_source
    assert "normalizeLoopbackBackendBaseURL" in protocol_source
    assert '"/api"' in protocol_source
    assert '"/community"' not in protocol_source  # renderer asset, never backend proxy
    assert "Access-Control-Allow-Origin" not in protocol_source


def test_desktop_backend_routes_mutable_state_to_user_data() -> None:
    source = BACKEND_RUNTIME.read_text(encoding="utf-8")
    build = yaml.safe_load(BUILD_CONFIG.read_text(encoding="utf-8"))
    resources = {(item["from"], item["to"]) for item in build["extraResources"]}

    assert 'OCTOPUS_DATA_DIR: path.join(app.getPath("userData"), "data")' in source
    assert 'OCTOPUS_RESOURCES_DIR: path.join(app.getPath("userData"), "resources")' in source
    assert "OCTOPUS_BROWSER_EXTENSION_DIR" in source
    assert (
        "../extensions/octopus-browser-relay",
        "extensions/octopus-browser-relay",
    ) in resources
    for name in ("agents", "prompts", "protocols"):
        assert (f"../{name}", name) in resources
    assert ("../skills.lock.json", "skills.lock.json") in resources
    for removed in ("runtime", "octopus_runtime", "tools", "pyproject.toml", "uv"):
        assert all(item["to"] != removed for item in build["extraResources"])
    assert build["appId"] == "ai.octopus.desktop"
    assert build["win"]["signExts"] == [".exe"]
    assert build["win"]["extraResources"] == [
        {
            "from": "../extras/desktop/build/backend/octopus-backend.exe",
            "to": "backend/octopus-backend.exe",
        },
        {
            "from": "../extras/desktop/build/codex",
            "to": "codex",
            "filter": ["**/*"],
        },
    ]
    agents = next(item for item in build["extraResources"] if item["to"] == "agents")
    for excluded in (
        "!**/sessions/**",
        "!**/workspace/**",
        "!**/*.jsonl",
        "!**/visuals/backups/**",
    ):
        assert excluded in agents["filter"]


def test_packaged_desktop_backend_has_no_uv_python_or_network_fallback() -> None:
    source = BACKEND_RUNTIME.read_text(encoding="utf-8")
    uv_function = source[
        source.index("function developmentUvCmd") : source.index("const CORE_DEPS")
    ]
    bootstrap = source[
        source.index("async function bootstrapCore") : source.index(
            "async function ensureOptionalDeps"
        )
    ]
    optional = source[
        source.index("async function ensureOptionalDeps") : source.index("let backendChild")
    ]
    spawn = source[
        source.index("async function spawnBackend") : source.index("function killBackend")
    ]

    assert 'path.join(resourcesPath(), "backend", exe)' in source
    assert "refusing system/runtime fallback" in source
    assert "if (app.isPackaged)" in uv_function
    assert "if (app.isPackaged)" in bootstrap
    assert "if (app.isPackaged)" in optional
    assert "const packaged = Boolean(app.isPackaged);" in spawn
    assert "if (!packaged) await bootstrapCore(onProgress);" in spawn
    assert "? requirePackagedBackendExecutable()" in spawn
    assert ": pythonExe();" in spawn
    assert "spawn(executable, args" in spawn
    if os.name == "nt":
        # The Windows profile materializes .exe executables; the darwin and Linux
        # profiles reuse the extension-less basename, so only assert the exact
        # codex executable path and the Windows inventory when running on Windows.
        assert 'path.join(resourcesPath(), "codex", "bin", "codex.exe")' in source
        for relative in (*CODEX_BUNDLE_EXECUTABLES, *CODEX_BUNDLE_LICENSE_SOURCES):
            assert f'"{relative}"' in source
    assert 'relative: "codex-package.json"' in source
    assert '"octopus-codex-bundle.json"' in source
    assert "required.expectedSha256 || sourceHash" in source
    assert "refusing PATH/network fallback" in source
    assert "env.OCTOPUS_CODEX_EXECUTABLE = requirePackagedCodexExecutable();" in spawn


def test_packaged_runtime_rejects_missing_backend_before_any_spawn(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the packaged backend contract")
    resources = tmp_path / "packaged-resources"
    user_data = tmp_path / "user-data"
    resources.mkdir()
    script = r"""
const Module = require("module");
const originalLoad = Module._load;
let spawnCalls = 0;
Module._load = function(request, parent, isMain) {
  if (request === "electron") {
    return { app: { isPackaged: true, getPath: () => process.argv[3] } };
  }
  if (request === "child_process") {
    return { spawn: () => { spawnCalls += 1; throw new Error("unexpected spawn"); } };
  }
  return originalLoad.call(this, request, parent, isMain);
};
Object.defineProperty(process, "resourcesPath", { value: process.argv[2] });
const runtime = require(process.argv[1]);
(async () => {
  try {
    await runtime.spawnBackend("ignored-config.yaml");
    process.exitCode = 2;
  } catch (error) {
    process.stdout.write(JSON.stringify({ message: error.message, spawnCalls }));
  }
})();
"""
    result = subprocess.run(
        [
            node,
            "-e",
            script,
            str(BACKEND_RUNTIME),
            str(resources),
            str(user_data),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["spawnCalls"] == 0
    assert "packaged backend executable is missing" in payload["message"]
    assert "refusing system/runtime fallback" in payload["message"]


def test_packaged_runtime_rejects_missing_codex_before_any_spawn(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the packaged Codex contract")
    resources = tmp_path / "packaged-resources"
    user_data = tmp_path / "user-data"
    backend = resources / "backend/octopus-backend"
    backend.parent.mkdir(parents=True)
    backend.write_bytes(b"backend")
    script = r"""
const Module = require("module");
const originalLoad = Module._load;
let spawnCalls = 0;
Module._load = function(request, parent, isMain) {
  if (request === "electron") {
    return { app: { isPackaged: true, getPath: () => process.argv[3] } };
  }
  if (request === "child_process") {
    return { spawn: () => { spawnCalls += 1; throw new Error("unexpected spawn"); } };
  }
  return originalLoad.call(this, request, parent, isMain);
};
Object.defineProperty(process, "resourcesPath", { value: process.argv[2] });
const runtime = require(process.argv[1]);
(async () => {
  try {
    await runtime.spawnBackend("ignored-config.yaml");
    process.exitCode = 2;
  } catch (error) {
    process.stdout.write(JSON.stringify({ message: error.message, spawnCalls }));
  }
})();
"""
    result = subprocess.run(
        [node, "-e", script, str(BACKEND_RUNTIME), str(resources), str(user_data)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["spawnCalls"] == 0
    assert "packaged Codex executable is missing" in payload["message"]
    assert "refusing PATH/network fallback" in payload["message"]


@pytest.mark.parametrize(
    "missing_relative",
    (
        *CODEX_BUNDLE_EXECUTABLES[1:],
        "codex-package.json",
        *CODEX_BUNDLE_LICENSE_SOURCES,
        "octopus-codex-bundle.json",
    ),
)
@pytest.mark.skipif(
    os.name != "nt",
    reason="materializes the Windows Codex bundle (bin/*.exe, pre-authenticode manifest)",
)
def test_packaged_runtime_requires_the_complete_codex_bundle_before_spawn(
    tmp_path: Path, missing_relative: str
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the packaged Codex contract")
    resources = tmp_path / "packaged-resources"
    user_data = tmp_path / "user-data"
    _materialize_packaged_codex_bundle(resources)
    (resources / "codex" / missing_relative).unlink()
    backend_name = "octopus-backend.exe" if os.name == "nt" else "octopus-backend"
    backend = resources / "backend" / backend_name
    backend.parent.mkdir(parents=True)
    backend.write_bytes(b"backend")
    script = r"""
const Module = require("module");
const originalLoad = Module._load;
let spawnCalls = 0;
Module._load = function(request, parent, isMain) {
  if (request === "electron") {
    return { app: { isPackaged: true, getPath: () => process.argv[3] } };
  }
  if (request === "child_process") {
    return { spawn: () => { spawnCalls += 1; throw new Error("unexpected spawn"); } };
  }
  return originalLoad.call(this, request, parent, isMain);
};
Object.defineProperty(process, "resourcesPath", { value: process.argv[2] });
const runtime = require(process.argv[1]);
(async () => {
  try {
    await runtime.spawnBackend("ignored-config.yaml");
    process.exitCode = 2;
  } catch (error) {
    process.stdout.write(JSON.stringify({ message: error.message, spawnCalls }));
  }
})();
"""
    result = subprocess.run(
        [node, "-e", script, str(BACKEND_RUNTIME), str(resources), str(user_data)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["spawnCalls"] == 0
    assert Path(missing_relative).name in payload["message"]
    assert "refusing PATH/network fallback" in payload["message"]


@pytest.mark.skipif(
    os.name != "nt",
    reason="materializes the Windows Codex bundle (bin/*.exe, pre-authenticode manifest)",
)
def test_packaged_runtime_rejects_tampered_codex_license_before_spawn(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the packaged Codex contract")
    resources = tmp_path / "packaged-resources"
    user_data = tmp_path / "user-data"
    _materialize_packaged_codex_bundle(resources)
    (resources / "codex/NOTICE").write_text("tampered", encoding="utf-8")
    backend_name = "octopus-backend.exe" if os.name == "nt" else "octopus-backend"
    backend = resources / "backend" / backend_name
    backend.parent.mkdir(parents=True)
    backend.write_bytes(b"backend")
    script = r"""
const Module = require("module");
const originalLoad = Module._load;
let spawnCalls = 0;
Module._load = function(request, parent, isMain) {
  if (request === "electron") {
    return { app: { isPackaged: true, getPath: () => process.argv[3] } };
  }
  if (request === "child_process") {
    return { spawn: () => { spawnCalls += 1; throw new Error("unexpected spawn"); } };
  }
  return originalLoad.call(this, request, parent, isMain);
};
Object.defineProperty(process, "resourcesPath", { value: process.argv[2] });
const runtime = require(process.argv[1]);
(async () => {
  try {
    await runtime.spawnBackend("ignored-config.yaml");
    process.exitCode = 2;
  } catch (error) {
    process.stdout.write(JSON.stringify({ message: error.message, spawnCalls }));
  }
})();
"""
    result = subprocess.run(
        [node, "-e", script, str(BACKEND_RUNTIME), str(resources), str(user_data)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["spawnCalls"] == 0
    assert payload["message"] == "packaged Codex bundle hash mismatch: NOTICE"


@pytest.mark.skipif(
    os.name != "nt",
    reason="materializes the Windows Codex bundle (bin/*.exe, pre-authenticode manifest)",
)
def test_packaged_runtime_overrides_host_codex_with_bundled_absolute_path(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the packaged Codex contract")
    resources = tmp_path / "packaged-resources"
    user_data = tmp_path / "user-data"
    bundled_codex = _materialize_packaged_codex_bundle(resources)
    backend_name = "octopus-backend.exe" if os.name == "nt" else "octopus-backend"
    backend = resources / "backend" / backend_name
    backend.parent.mkdir(parents=True)
    backend.write_bytes(b"backend")
    script = r"""
const Module = require("module");
const originalLoad = Module._load;
let captured = null;
Module._load = function(request, parent, isMain) {
  if (request === "electron") {
    return { app: { isPackaged: true, getPath: () => process.argv[3] } };
  }
  if (request === "child_process") {
    return { spawn: (command, args, options) => {
      captured = { command, args, codex: options.env.OCTOPUS_CODEX_EXECUTABLE };
      return { on: () => {} };
    } };
  }
  return originalLoad.call(this, request, parent, isMain);
};
Object.defineProperty(process, "resourcesPath", { value: process.argv[2] });
process.env.OCTOPUS_CODEX_EXECUTABLE = "host-path-codex";
const runtime = require(process.argv[1]);
(async () => {
  await runtime.spawnBackend("fixed-config.yaml");
  process.stdout.write(JSON.stringify({
    ...captured,
    expectedCodex: runtime.packagedCodexExecutable(),
  }));
})();
"""
    result = subprocess.run(
        [node, "-e", script, str(BACKEND_RUNTIME), str(resources), str(user_data)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert Path(payload["command"]).is_absolute()
    assert payload["codex"] == payload["expectedCodex"]
    assert payload["codex"] == str(bundled_codex)
    assert Path(payload["codex"]).is_absolute()
    assert payload["codex"] != "host-path-codex"


def test_windows_workflow_builds_and_smokes_canonical_offline_shell() -> None:
    text = WINDOWS_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    ordered_steps = workflow["jobs"]["build-win"]["steps"]
    steps = {step.get("name"): step for step in ordered_steps if step.get("name")}
    step_names = [step.get("name") for step in ordered_steps]

    python_setup = next(step for step in ordered_steps if step.get("uses") == ACTIONS_SETUP_PYTHON)
    assert python_setup["with"]["python-version"] == "3.11.9"
    node_setup = next(step for step in ordered_steps if step.get("uses") == ACTIONS_SETUP_NODE)
    assert node_setup["with"]["node-version"] == "22.23.2"
    uv_setup = next(step for step in ordered_steps if step.get("uses") == ASTRAL_SETUP_UV)
    assert uv_setup["with"]["version"] == "0.11.25"
    python_install = steps["Sync locked desktop build dependencies"]["run"]
    assert "uv sync --locked --python 3.11.9" in python_install
    for extra in ("desktop-core", "desktop-build"):
        assert f"--extra {extra}" in python_install
    assert "--extra dev" not in python_install
    test_install = steps["Sync locked desktop test dependencies"]["run"]
    for extra in ("dev", "desktop-core", "desktop-build"):
        assert f"--extra {extra}" in test_install
    assert "pip install" not in text
    assert "--upgrade" not in text
    assert "choco install" not in text
    assert workflow["jobs"]["build-win"]["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    backend = steps["Build backend (PyInstaller)"]
    assert backend["working-directory"] == "extras/desktop"
    assert backend["env"]["PYTHON_EXE"].endswith("\\.venv\\Scripts\\python.exe")
    assert backend["run"] == "pnpm backend:build:win"
    codex_prepare = steps["Prepare pinned Codex Windows runtime"]
    assert codex_prepare["working-directory"] == "frontend"
    assert codex_prepare["run"] == "pnpm codex:prepare:win"
    codex_preflight = steps["Verify pinned Codex before packaging"]["run"]
    assert "extras/desktop/build/codex" in codex_preflight
    assert 'Join-Path $codexRoot "bin/codex.exe"' in codex_preflight
    assert "octopus.codex_bundle.v1" in codex_preflight
    assert "codex-native-notices.v1" in codex_preflight
    assert 'version -ne "0.149.0"' in codex_preflight
    for relative in CODEX_BUNDLE_EXECUTABLES:
        assert f'"{relative}"' in codex_preflight
    for relative in CODEX_BUNDLE_LICENSE_SOURCES:
        assert f'"{relative}"' in codex_preflight
    assert '"codex-package.json"' in codex_preflight
    assert "PSObject.Properties[$relative]" in codex_preflight
    assert "app-server --help" in codex_preflight
    preflight = steps["Verify PyInstaller backend before packaging"]["run"]
    assert "extras/desktop/build/backend/octopus-backend.exe" in preflight
    assert "--help" in preflight
    contracts = steps["Verify desktop first-launch and packaging contracts"]["run"]
    assert "./.venv/Scripts/python.exe -m pytest" in contracts
    assert "tests/test_desktop_config_packaging.py" in contracts
    electron = steps["Build canonical Electron EXE"]
    assert electron["working-directory"] == "frontend"
    assert electron["run"] == "pnpm electron:build:win"
    smoke = steps["Verify packaged backend and Codex are present and runnable"]["run"]
    assert "frontend/release/win-unpacked/resources/backend/octopus-backend.exe" in smoke
    assert '"frontend/release/win-unpacked/resources/codex"' in smoke
    assert 'Join-Path $codexRoot "bin/codex.exe"' in smoke
    for relative in CODEX_BUNDLE_LICENSE_SOURCES:
        assert f'"{relative}"' in smoke
    assert "codex-native-notices.v1" in smoke
    assert "OCTOPUS_CODEX_EXECUTABLE" in smoke
    assert "app-server --help" in smoke
    assert "ensureDesktopConfigFile" in smoke
    assert "ensureDesktopResources" in smoke
    assert "Start-Process" in smoke
    assert "/readyz" in smoke
    assert "uv" not in smoke.lower()
    assert "python" not in smoke.lower()

    signing_proof = steps["Verify Authenticode signatures and create commit-bound checksums"]["run"]
    for relative in CODEX_BUNDLE_EXECUTABLES:
        assert f'"win-unpacked/resources/codex/{relative}"' in signing_proof
    assert "OCTOPUS_WINDOWS_SIGNER_THUMBPRINT" in signing_proof
    assert "OCTOPUS_WINDOWS_SIGNER_SUBJECT_BASE64" in signing_proof
    assert "publisher = $publisher" in signing_proof
    assert "timestampSubject" in signing_proof

    setup_upload = steps["Upload EXE installer"]["with"]["path"]
    portable_upload = steps["Upload portable (unpacked)"]["with"]["path"]
    assert "frontend/release/" in setup_upload
    assert "extras/desktop/release/" not in setup_upload
    assert portable_upload == "frontend/release/win-unpacked/**"
    assert "frontend/uv_bin" not in text
    assert step_names.index("Build backend (PyInstaller)") < step_names.index(
        "Build canonical Electron EXE"
    )
    assert step_names.index("Prepare pinned Codex Windows runtime") < step_names.index(
        "Build canonical Electron EXE"
    )
    assert step_names.index("Build backend (PyInstaller)") < step_names.index(
        "Sync locked desktop test dependencies"
    )
    assert step_names.index("Sync locked desktop test dependencies") < step_names.index(
        "Verify desktop first-launch and packaging contracts"
    )
    assert step_names.index("Build canonical Electron EXE") < step_names.index(
        "Verify packaged backend and Codex are present and runnable"
    )
    assert step_names.index(
        "Verify packaged backend and Codex are present and runnable"
    ) < step_names.index("Upload EXE installer")


def test_release_reverifies_every_packaged_codex_executable_identity() -> None:
    source = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "$proofFiles.Count -ne 8" in source
    for relative in CODEX_BUNDLE_EXECUTABLES:
        assert f'"win-unpacked/resources/codex/{relative}"' in source
    assert "$proofEntry[0].publisher -ne $publisher" in source
    assert "$proofEntry[0].timestampSubject" in source


def test_windows_backend_builder_uses_only_the_locked_uv_interpreter() -> None:
    source = BACKEND_BUILD.read_text(encoding="utf-8")

    assert 'path.join(repoRoot, ".venv", "Scripts", "python.exe")' in source
    assert "const configuredPython = process.env.PYTHON_EXE;" in source
    assert "PYTHON_EXE must resolve to" in source
    assert "spawnSync(\n  lockedPython," in source
    assert "fs.existsSync(lockedPython)" in source
    assert "uv sync --locked --python 3.11.9" in source
    assert '|| "python"' not in source


def test_windows_desktop_build_toolchain_is_declared_and_locked() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert project["project"]["optional-dependencies"]["desktop-build"] == ["pyinstaller==6.16.0"]

    locked = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in locked["package"]}
    assert packages["pyinstaller"]["version"] == "6.16.0"
    root_package = packages["octopus-agent-runtime"]
    assert root_package["optional-dependencies"]["desktop-build"] == [{"name": "pyinstaller"}]

    frontend = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))
    assert frontend["devDependencies"]["@openai/codex"] == "0.149.0"
    lock = FRONTEND_LOCK.read_text(encoding="utf-8")
    assert "'@openai/codex@0.149.0-win32-x64':" in lock
    assert "'@openai/codex-win32-x64': '@openai/codex@0.149.0-win32-x64'" in lock


def test_windows_codex_preparer_copies_only_the_locked_official_platform_package() -> None:
    source = CODEX_PREPARE.read_text(encoding="utf-8")

    assert 'const CODEX_VERSION = "0.149.0";' in source
    assert 'const PLATFORM_PACKAGE = "@openai/codex-win32-x64";' in source
    assert "PLATFORM_PACKAGE_INTEGRITY" in source
    assert 'const TARGET_TRIPLE = "x86_64-pc-windows-msvc";' in source
    assert 'const CODEX_SOURCE_COMMIT = "758ef40f50c1a458425c7cfbf1eb12cbc07af0b0";' in source
    assert 'const CARGO_ABOUT_VERSION = "0.9.2";' in source
    assert "65e2c0c7f7b239ee758133ce17cfb680bc38aec84876ca81015458c41a988c7a" in source
    assert "da7997facd0e36f4ebca01594c60abdc1204f5421a35d28c4760b13addf247c5" in source
    assert 'const RATATUI_VERSION = "0.30.2";' in source
    assert "3274ba0a2c5e1bcad2a2005d20f4dc59dad26b2eb0940fb094500dba4099d57d" in source
    assert 'const RIPGREP_VERSION = "15.2.0";' in source
    assert "71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5" in source
    assert "14231169855ec5205cf5a1b6f1db358ff4aed4247c86b69ce8aae647c77f6680" in source
    assert 'frontendRequire.resolve(\n    "@openai/codex/package.json",' in source
    assert "wrapperRequire.resolve(\n    `${PLATFORM_PACKAGE}/package.json`," in source
    assert '"bin/codex.exe"' in source
    assert 'schema: "octopus.codex_bundle.v1"' in source
    assert 'fileHashPhase: "pre-authenticode"' in source
    for relative in CODEX_BUNDLE_LICENSE_SOURCES:
        assert f'"{relative}"' in source
    assert "bundled license text failed its source hash" in source
    assert "fs.copyFileSync(license.source, destination)" in source
    assert "fs.cpSync(sourceRoot, outputRoot" in source
    assert "https:" not in source
    assert "fetch(" not in source
    assert "npm install" not in source


def test_windows_codex_third_party_reports_are_reproducibly_pinned() -> None:
    generator = CODEX_LICENSE_GENERATOR.read_text(encoding="utf-8")
    reports = {
        "THIRD_PARTY_LICENSES-codex-cli.html": (
            "841d5072916479fc3d6fbe8c4b240b66d468de9f625a2fcb658c34fe1a4ec771"
        ),
        "THIRD_PARTY_LICENSES-code-mode-host.html": (
            "6b562200ef39938051e8eca39ce61a4d032752e04e1d21ba0fe216bd0ad91434"
        ),
        "THIRD_PARTY_LICENSES-windows-sandbox.html": (
            "8858ef427eb901498d06d12d14ce6c3ef53fdeb352251006276dac8ec53ac5e4"
        ),
    }

    assert 'CODEX_VERSION = "0.149.0"' in generator
    assert 'CODEX_COMMIT = "758ef40f50c1a458425c7cfbf1eb12cbc07af0b0"' in generator
    assert 'RIPGREP_COMMIT = "e89fff89ac9af12e8d4ce9d5fd07beb408ca730f"' in generator
    assert 'CARGO_ABOUT_VERSION = "0.9.2"' in generator
    assert 'TARGET = "x86_64-pc-windows-msvc"' in generator
    assert '"--locked"' in generator
    assert '"--fail"' in generator
    assert 'git", "archive"' in generator
    assert 'version = "0.0.0"' in generator

    license_root = ROOT / "extras/desktop/licenses/codex-0.149.0"
    for filename, expected_hash in reports.items():
        report = license_root / filename
        payload = report.read_bytes()
        assert _sha256(payload) == expected_hash
        assert b"OpenAI Codex 0.149.0 Third-Party Licenses" in payload

    config = (license_root / "cargo-about.toml").read_text(encoding="utf-8")
    assert 'targets = ["x86_64-pc-windows-msvc"]' in config
    assert "ignore-transitive-dependencies = false" in config

    ripgrep_root = ROOT / "extras/desktop/licenses/ripgrep-15.2.0"
    ripgrep_report = (ripgrep_root / "THIRD_PARTY_LICENSES-ripgrep.html").read_bytes()
    assert _sha256(ripgrep_report) == (
        "d55f9ff28424dafc02ff01c2c054cb6bde273c904d6e13708d4ace1ab27b56a5"
    )
    assert b"ripgrep 15.2.0 Third-Party Licenses" in ripgrep_report
    ripgrep_config = (ripgrep_root / "cargo-about.toml").read_text(encoding="utf-8")
    assert 'targets = ["x86_64-pc-windows-msvc"]' in ripgrep_config
    assert "ignore-transitive-dependencies = false" in ripgrep_config

    native_generator = CODEX_NATIVE_LICENSE_GENERATOR.read_text(encoding="utf-8")
    assert 'CODEX_COMMIT = "758ef40f50c1a458425c7cfbf1eb12cbc07af0b0"' in native_generator
    assert 'RUSTY_V8_COMMIT = "5c15a6995c9bb4bacd3e341b59fff32c909c80bf"' in native_generator
    assert 'V8_COMMIT = "ac1e23989121713ca642f6650b34deff7b686896"' in native_generator
    assert 'ICU_COMMIT = "ee5f27adc28bd3f15b2c293f726d14d2e336cbd5"' in native_generator
    assert "downloads a file" in native_generator
    assert "urlopen" not in native_generator


def test_legacy_desktop_package_delegates_and_cannot_publish_old_shell() -> None:
    package = json.loads(LEGACY_PACKAGE.read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert "main" not in package
    assert "build" not in package
    assert "electron-builder" not in LEGACY_PACKAGE.read_text(encoding="utf-8")
    assert scripts["backend:build:win"] == "node build-backend-win.cjs"
    assert scripts["codex:prepare:win"] == "node prepare-codex-win.cjs"
    assert "../../frontend electron:build:win" in scripts["electron:build:win"]
    assert "../../frontend electron:dev" in scripts["electron:dev"]
    assert scripts["backend:build:mac"] == "node build-backend-mac.cjs"
    assert scripts["codex:prepare:mac"] == "node prepare-codex-mac.cjs"
    assert "backend:build:mac" in scripts["electron:build:mac"]
    assert "../../frontend electron:build:mac" in scripts["electron:build:mac"]
    assert scripts["backend:build:linux"] == "node build-backend-linux.cjs"
    assert scripts["codex:prepare:linux"] == "node prepare-codex-linux.cjs"
    assert "backend:build:linux" in scripts["electron:build:linux"]
    assert "../../frontend electron:build:linux" in scripts["electron:build:linux"]

    frontend_scripts = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))["scripts"]
    assert frontend_scripts["codex:prepare:win"] == ("node ../extras/desktop/prepare-codex-win.cjs")
    assert frontend_scripts["electron:build:win"].startswith(
        "pnpm build && pnpm codex:prepare:win && electron-builder"
    )
    assert "--win --x64 --publish never" in frontend_scripts["electron:build:win"]
    assert "electron-builder" in frontend_scripts["electron:build:win"]
    assert frontend_scripts["codex:prepare:mac"] == ("node ../extras/desktop/prepare-codex-mac.cjs")
    assert "codex:prepare:mac" in frontend_scripts["electron:build:mac"]
    assert "--mac --arm64 --publish never" in frontend_scripts["electron:build:mac"]
    assert "electron-builder" in frontend_scripts["electron:build:mac"]
    assert frontend_scripts["codex:prepare:linux"] == (
        "node ../extras/desktop/prepare-codex-linux.cjs"
    )
    assert "codex:prepare:linux" in frontend_scripts["electron:build:linux"]
    assert "--linux --x64 --publish never" in frontend_scripts["electron:build:linux"]
    assert "electron-builder" in frontend_scripts["electron:build:linux"]


def test_linux_workflow_builds_and_smokes_canonical_linux_shell() -> None:
    text = LINUX_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    ordered_steps = workflow["jobs"]["build-linux"]["steps"]
    steps = {step.get("name"): step for step in ordered_steps if step.get("name")}
    step_names = [step.get("name") for step in ordered_steps]

    assert workflow["jobs"]["build-linux"]["runs-on"] == "ubuntu-24.04"
    assert "windows-code-signing" not in workflow["jobs"]["build-linux"]

    python_setup = next(step for step in ordered_steps if step.get("uses") == ACTIONS_SETUP_PYTHON)
    assert python_setup["with"]["python-version"] == "3.11.9"
    node_setup = next(step for step in ordered_steps if step.get("uses") == ACTIONS_SETUP_NODE)
    assert node_setup["with"]["node-version"] == "22.23.2"
    uv_setup = next(step for step in ordered_steps if step.get("uses") == ASTRAL_SETUP_UV)
    assert uv_setup["with"]["version"] == "0.11.25"
    assert workflow["jobs"]["build-linux"]["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert "pip install" not in text
    assert "--upgrade" not in text

    python_install = steps["Sync locked desktop build dependencies"]["run"]
    for extra in ("desktop-core", "desktop-build"):
        assert f"--extra {extra}" in python_install
    assert "--extra dev" not in python_install
    test_install = steps["Sync locked desktop test dependencies"]["run"]
    for extra in ("dev", "desktop-core", "desktop-build"):
        assert f"--extra {extra}" in test_install

    backend = steps["Build backend (PyInstaller)"]
    assert backend["working-directory"] == "extras/desktop"
    assert backend["env"]["PYTHON_EXE"].endswith("/.venv/bin/python")
    assert backend["run"] == "pnpm backend:build:linux"
    codex_prepare = steps["Prepare pinned Codex Linux runtime"]
    assert codex_prepare["working-directory"] == "frontend"
    assert codex_prepare["run"] == "pnpm codex:prepare:linux"

    codex_preflight = steps["Verify pinned Codex before packaging"]["run"]
    assert "extras/desktop/build/codex" in codex_preflight
    assert '"bin/codex"' in codex_preflight
    assert '"bin/codex-code-mode-host"' in codex_preflight
    assert '"codex-path/rg"' in codex_preflight
    assert '"codex-resources/zsh/bin/zsh"' in codex_preflight
    assert '"codex-resources/bwrap"' in codex_preflight
    assert '"codex-package.json"' in codex_preflight
    assert "octopus.codex_bundle.v1" in codex_preflight
    assert "7f454c46" in codex_preflight  # ELF magic
    assert "app-server --help" in codex_preflight
    # Linux keeps no windows-native provenance artifacts.
    assert "windows-sandbox" not in codex_preflight
    assert "NATIVE_PROVENANCE.json" not in codex_preflight

    preflight = steps["Verify PyInstaller backend before packaging"]["run"]
    assert "extras/desktop/build/backend/octopus-backend" in preflight
    assert "7f454c46" in preflight
    assert "--help" in preflight

    contracts = steps["Verify desktop packaging contracts"]["run"]
    assert "tests/test_desktop_config_packaging.py" in contracts

    electron = steps["Build canonical Electron AppImage"]
    assert electron["working-directory"] == "frontend"
    assert electron["run"] == "pnpm electron:build:linux"

    smoke = steps["Verify packaged backend and Codex are present and runnable"]["run"]
    assert "EchoAI-Setup-Linux-*.AppImage" in smoke
    assert "frontend/release" in smoke
    assert "app-server --help" in smoke
    assert "octopus-codex-bundle.json" in smoke
    assert '/readyz"' in smoke or "/readyz" in smoke
    assert "uv" not in smoke.lower()
    assert "python3 -c" in smoke
    assert "ensureDesktopConfigFile" in smoke

    checksum = steps["Create commit-bound checksum"]["run"]
    assert "SHA256SUMS" in checksum
    assert "sha256sum" in checksum

    setup_upload = steps["Upload AppImage"]["with"]["path"]
    assert "frontend/release/" in setup_upload
    assert "EchoAI-Setup-Linux-*.AppImage" in setup_upload
    portable_upload = steps["Upload portable (unpacked)"]["with"]["path"]
    assert portable_upload == "frontend/release/linux-unpacked/**"

    assert step_names.index("Build backend (PyInstaller)") < step_names.index(
        "Build canonical Electron AppImage"
    )
    assert step_names.index("Prepare pinned Codex Linux runtime") < step_names.index(
        "Build canonical Electron AppImage"
    )
    assert step_names.index("Build canonical Electron AppImage") < step_names.index(
        "Verify packaged backend and Codex are present and runnable"
    )
    assert step_names.index(
        "Verify packaged backend and Codex are present and runnable"
    ) < step_names.index("Create commit-bound checksum")


def test_linux_backend_builder_uses_only_the_locked_uv_interpreter() -> None:
    source = (ROOT / "extras/desktop/build-backend-linux.cjs").read_text(encoding="utf-8")

    assert 'path.join(repoRoot, ".venv", "bin", "python")' in source
    assert "const configuredPython = process.env.PYTHON_EXE;" in source
    assert "PYTHON_EXE must resolve to" in source
    assert "fs.existsSync(lockedPython)" in source
    assert "uv sync --locked --python 3.11.9" in source
    assert '|| "python"' not in source


def test_linux_backend_spec_mirrors_darwin_entry() -> None:
    linux_spec = (ROOT / "packaging/linux/octopus-backend.spec").read_text(encoding="utf-8")
    darwin_spec = (ROOT / "packaging/macos/octopus-backend.spec").read_text(encoding="utf-8")

    assert "octopus_backend_entry.py" in linux_spec
    assert linux_spec.split("name=")[1].split('"')[1] == "octopus-backend"
    assert "upx=False" in linux_spec
    assert "console=True" in linux_spec
    assert "reflex_rules.yaml" in linux_spec
    # Linux and macOS share the same platform-neutral CLI entry contract.
    assert "octopus_backend_entry.py" in darwin_spec


def test_linux_codex_preparer_pins_only_the_locked_linux_packages() -> None:
    source = (ROOT / "extras/desktop/prepare-codex-linux.cjs").read_text(encoding="utf-8")

    assert 'const CODEX_VERSION = "0.149.0";' in source
    assert 'platformPackage: "@openai/codex-linux-x64"' in source
    assert 'platformPackage: "@openai/codex-linux-arm64"' in source
    assert 'targetTriple: "x86_64-unknown-linux-musl"' in source
    assert 'targetTriple: "aarch64-unknown-linux-musl"' in source
    assert (
        "sha512-uZXaN9JPxu0/jjnqqJeTd4kRYPnjVZK3MiVndfG1mHhEaoDKL7ScWHfPqvAEOjwsSDEmQSlMfUkmvYp/CHciYw=="
        in source
    )
    assert (
        "sha512-fAXPpvIob+11RNZJS9CVVTsKb+V4Hw3woGFPj42D7fU2wBJUKI2jfAc4fLJNtrpwRecLeW601mtkMHOSIbWuuA=="
        in source
    )
    assert '"codex-resources/bwrap"' in source
    assert 'EXECUTABLE_MAGIC = "7f454c46"' in source
    assert 'schema: "octopus.codex_bundle.v1"' in source
    assert 'fileHashPhase: "pre-package"' in source
    # Linux binary is filtered from node_modules on every non-Linux host, so the
    # preparer must be able to fetch the registry tarball pinned by the lock's
    # integrity (verified byte-for-byte before extraction). Offline never applies
    # here; the runtime bundle is fully materialized before electron-builder.
    assert "tarballUrl:" in source
    assert "registry.npmjs.org/@openai/codex" in source
    assert "pnpm" in source
    assert "npm install" not in source


def test_linux_backend_runtime_profile_is_selected_on_linux() -> None:
    source = BACKEND_RUNTIME.read_text(encoding="utf-8")

    assert "LINUX_ARM64_PROFILE" in source
    assert "LINUX_X64_PROFILE" in source
    assert '"@openai/codex-linux-arm64"' in source
    assert '"@openai/codex-linux-x64"' in source
    assert '"aarch64-unknown-linux-musl"' in source
    assert '"x86_64-unknown-linux-musl"' in source
    assert 'executableMagic: "7f454c46"' in source
    assert "profiled deep" not in source
    # Linux must not regress the darwin/Windows selection under any arch.
    assert 'process.platform === "linux"' in source


def test_linux_resources_are_declared_in_build_config() -> None:
    text = BUILD_CONFIG.read_text(encoding="utf-8")
    segment = text.split("linux:", 1)[1].split("nsis:", 1)[0]

    assert "AppImage" in segment
    assert "extras/desktop/build/backend/octopus-backend" in segment
    assert "extras/desktop/build/codex" in segment
    assert "to: codex" in segment
    assert "GITHUB_SHA" in segment
