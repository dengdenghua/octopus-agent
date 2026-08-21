"""Desktop packaging must materialize a loadable per-install auth secret."""

from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging/desktop/config.desktop.yaml"
MATERIALIZER = ROOT / "frontend/electron/desktop-config.cjs"
MAIN = ROOT / "frontend/electron/main.cjs"
DESKTOP_PROTOCOL = ROOT / "frontend/electron/desktop-protocol.cjs"
BACKEND_RUNTIME = ROOT / "frontend/electron/backend-runtime.cjs"
BUILD_CONFIG = ROOT / "packaging/desktop/build.yml"
WINDOWS_WORKFLOW = ROOT / ".github/workflows/build-win.yml"
LEGACY_PACKAGE = ROOT / "extras/desktop/package.json"
FRONTEND_PACKAGE = ROOT / "frontend/package.json"
BACKEND_BUILD = ROOT / "extras/desktop/build-backend-win.cjs"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
ACTIONS_SETUP_NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
ACTIONS_SETUP_PYTHON = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
ASTRAL_SETUP_UV = "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86"


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
    assert 'dialog.showErrorBox("Octopus 启动失败"' in source
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
    for name in ("agents", "prompts", "protocols"):
        assert (f"../{name}", name) in resources
    assert ("../skills.lock.json", "skills.lock.json") in resources
    for removed in ("runtime", "octopus_runtime", "tools", "pyproject.toml", "uv"):
        assert all(item["to"] != removed for item in build["extraResources"])
    assert build["appId"] == "ai.octopus.desktop"
    assert build["win"]["extraResources"] == [
        {
            "from": "../extras/desktop/build/backend/octopus-backend.exe",
            "to": "backend/octopus-backend.exe",
        }
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
    preflight = steps["Verify PyInstaller backend before packaging"]["run"]
    assert "extras/desktop/build/backend/octopus-backend.exe" in preflight
    assert "--help" in preflight
    contracts = steps["Verify desktop first-launch and packaging contracts"]["run"]
    assert "./.venv/Scripts/python.exe -m pytest" in contracts
    assert "tests/test_desktop_config_packaging.py" in contracts
    electron = steps["Build canonical Electron EXE"]
    assert electron["working-directory"] == "frontend"
    assert electron["run"] == "pnpm electron:build:win"
    smoke = steps["Verify packaged backend is present and reaches readiness"]["run"]
    assert "frontend/release/win-unpacked/resources/backend/octopus-backend.exe" in smoke
    assert "ensureDesktopConfigFile" in smoke
    assert "ensureDesktopResources" in smoke
    assert "Start-Process" in smoke
    assert "/readyz" in smoke
    assert "uv" not in smoke.lower()
    assert "python" not in smoke.lower()

    setup_upload = steps["Upload EXE installer"]["with"]["path"]
    portable_upload = steps["Upload portable (unpacked)"]["with"]["path"]
    assert "frontend/release/" in setup_upload
    assert "extras/desktop/release/" not in setup_upload
    assert portable_upload == "frontend/release/win-unpacked/**"
    assert "frontend/uv_bin" not in text
    assert step_names.index("Build backend (PyInstaller)") < step_names.index(
        "Build canonical Electron EXE"
    )
    assert step_names.index("Build backend (PyInstaller)") < step_names.index(
        "Sync locked desktop test dependencies"
    )
    assert step_names.index("Sync locked desktop test dependencies") < step_names.index(
        "Verify desktop first-launch and packaging contracts"
    )
    assert step_names.index("Build canonical Electron EXE") < step_names.index(
        "Verify packaged backend is present and reaches readiness"
    )
    assert step_names.index(
        "Verify packaged backend is present and reaches readiness"
    ) < step_names.index("Upload EXE installer")


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


def test_legacy_desktop_package_delegates_and_cannot_publish_old_shell() -> None:
    package = json.loads(LEGACY_PACKAGE.read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert "main" not in package
    assert "build" not in package
    assert "electron-builder" not in LEGACY_PACKAGE.read_text(encoding="utf-8")
    assert scripts["backend:build:win"] == "node build-backend-win.cjs"
    assert "../../frontend electron:build:win" in scripts["electron:build:win"]
    assert "../../frontend electron:dev" in scripts["electron:dev"]
    assert "process.exit(1)" in scripts["electron:build:mac"]
    assert "process.exit(1)" in scripts["electron:build:linux"]

    frontend_scripts = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))["scripts"]
    assert "electron-builder" in frontend_scripts["electron:build:win"]
    assert "process.exit(1)" in frontend_scripts["electron:build:mac"]
    assert "process.exit(1)" in frontend_scripts["electron:build:linux"]
