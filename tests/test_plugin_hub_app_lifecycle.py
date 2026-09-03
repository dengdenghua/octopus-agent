from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.ui import _app_routers_extra
from runtime.platform.ui._app_routers_extra import (
    _plugin_hub_roots,
    _register_plugin_hub_lifecycle,
)


class _LifecycleHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start_all(self) -> list[str]:
        self.calls.append("start")
        return ["paper_trading"]

    def stop_all(self) -> list[str]:
        self.calls.append("stop")
        return ["paper_trading"]


def test_plugin_hub_background_lifecycle_follows_fastapi_app() -> None:
    app = FastAPI()
    hub = _LifecycleHub()
    _register_plugin_hub_lifecycle(app, hub)

    assert hub.calls == []
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert hub.calls == ["start"]
    assert hub.calls == ["start", "stop"]


def test_plugin_hub_uses_active_app_data_root_for_external_packages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _app_routers_extra,
        "app_paths",
        lambda: SimpleNamespace(data_dir=tmp_path / "active-data"),
    )

    plugin_dir, bundled_plugin_dir = _plugin_hub_roots()

    assert plugin_dir == tmp_path / "active-data" / "plugins"
    assert bundled_plugin_dir.name == "bundled"
    assert bundled_plugin_dir.parent.name == "plugins"
