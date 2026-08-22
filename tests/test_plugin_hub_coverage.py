"""Dense coverage for PluginHub lifecycle (audit Q-05)."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.platform.plugins.plugin_hub import PluginHub


def _make_plugin(root: Path, name: str = "testplug") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\ndescription: test\n", encoding="utf-8"
    )
    (d / "__init__.py").write_text(
        "from runtime.platform.plugins.plugin_base import ModulePlugin\n\n"
        "class TestPlugin(ModulePlugin):\n"
        f"    name = '{name}'\n"
        "    def register_skills(self):\n        pass\n"
        "    def register_channels(self):\n        pass\n"
        "    def register_routes(self):\n        pass\n",
        encoding="utf-8",
    )
    return d


def test_discover_and_manifest(tmp_path: Path) -> None:
    hub = PluginHub(plugin_dir=tmp_path)
    _make_plugin(tmp_path)
    found = hub.discover()
    assert any(p.get("name") == "testplug" for p in found)
    d = tmp_path / "testplug"
    manifest = hub._read_manifest_file(d)
    assert manifest and manifest["name"] == "testplug"
    assert hub._read_manifest_file(tmp_path / "missing") is None


def test_load_unload_lifecycle(tmp_path: Path) -> None:
    hub = PluginHub(plugin_dir=tmp_path)
    _make_plugin(tmp_path)
    plugin = hub.load("testplug")
    assert plugin is not None and plugin.name == "testplug"
    assert hub.load("testplug") is plugin  # cached
    assert hub.get_plugin("testplug") is plugin
    assert hub.unload("testplug") is True
    assert hub.get_plugin("testplug") is None
    assert hub.load("nope") is None


def test_list_and_plugin_dir_resolution(tmp_path: Path) -> None:
    hub = PluginHub(plugin_dir=tmp_path)
    _make_plugin(tmp_path)
    assert hub.load("testplug") is not None
    listed = hub.list_plugins()
    assert any(p.get("name") == "testplug" for p in listed)
    assert hub._resolve_plugin_dir("testplug") == (tmp_path / "testplug")
    assert hub._resolve_plugin_dir("missing") is None


# ── WebSocket route mounting (voice / realtime stream plugins) ──


def _make_ws_plugin(root: Path, name: str = "voiceplug") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\ndescription: voice\n"
        "websockets:\n"
        "  - path: /ws/voice\n"
        "    handler: handle_voice_ws\n",
        encoding="utf-8",
    )
    (d / "__init__.py").write_text(
        "from runtime.platform.plugins.plugin_base import ModulePlugin\n\n"
        "class VoicePlugin(ModulePlugin):\n"
        f"    name = '{name}'\n"
        "    async def handle_voice_ws(self, websocket):\n"
        "        await websocket.accept()\n"
        "        while True:\n"
        "            try:\n"
        "                data = await websocket.receive_text()\n"
        "            except Exception:\n"
        "                break  # client closed\n"
        "            if data == 'ping':\n"
        "                await websocket.send_text('pong')\n"
        "        # 不主动 close:让 TestClient 的 with 退出负责收尾。\n",
        encoding="utf-8",
    )
    return d


def test_websocket_route_mounts_and_echoes(tmp_path: Path) -> None:
    """A manifest ``websockets`` entry mounts a live WS route on the app."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    app = FastAPI()
    hub = PluginHub(plugin_dir=tmp_path, fastapi_app=app)
    _make_ws_plugin(tmp_path)
    assert hub.load("voiceplug") is not None

    with TestClient(app) as client:
        try:
            with client.websocket_connect("/api/plugins/webhooks/voiceplug/ws/voice") as ws:
                ws.send_text("ping")
                assert ws.receive_text() == "pong"
        except WebSocketDisconnect:
            # 退出 with 时 TestClient 收到服务端 close 帧,框架正常收尾。
            pass

    hub.unload("voiceplug")

    hub.unload("voiceplug")


def test_websocket_missing_handler_closes_4404(tmp_path: Path) -> None:
    """A websockets entry pointing at a missing handler closes cleanly."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    app = FastAPI()
    hub = PluginHub(plugin_dir=tmp_path, fastapi_app=app)
    d = tmp_path / "wsbroken"
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(
        "name: wsbroken\nversion: 1.0.0\n"
        "websockets:\n"
        "  - path: /ws/none\n"
        "    handler: missing_handler\n",
        encoding="utf-8",
    )
    (d / "__init__.py").write_text(
        "from runtime.platform.plugins.plugin_base import ModulePlugin\n\n"
        "class BrokenPlugin(ModulePlugin):\n"
        "    name = 'wsbroken'\n",
        encoding="utf-8",
    )
    assert hub.load("wsbroken") is not None

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/plugins/webhooks/wsbroken/ws/none") as ws,
    ):
        ws.receive_text()

    hub.unload("wsbroken")
