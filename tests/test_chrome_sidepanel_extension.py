from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extensions" / "octopus-browser-relay"


def test_chrome_extension_manifest_declares_side_panel() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert manifest["side_panel"]["default_path"] == "sidepanel.html"
    assert {"sidePanel", "storage", "tabs", "scripting"} <= set(manifest["permissions"])
    csp = manifest["content_security_policy"]["extension_pages"]
    assert "connect-src" in csp
    assert "ws://127.0.0.1:8000" in csp
    assert "ws://localhost:8000" in csp
    assert manifest["action"]["default_title"] == "Open Octopus Agent Sidecar"


def test_sidepanel_is_extension_native_not_page_overlay() -> None:
    html = (EXTENSION / "sidepanel.html").read_text(encoding="utf-8")

    assert 'href="sidepanel.css"' in html
    assert 'src="sidepanel.js"' in html
    assert "<script>" not in html
    assert "Octopus Chrome Sidecar" in html
    assert "页面轻面板" in html
    assert 'id="controlTitle"' in html
    assert 'id="stopButton"' in html


def test_sidepanel_sends_chrome_turns_over_realtime() -> None:
    js = (EXTENSION / "sidepanel.js").read_text(encoding="utf-8")

    assert "/api/realtime" in js
    assert 'rpc("turn/start"' in js
    assert "@Chrome" in js
    assert 'runtime_surfaces: ["chrome"]' in js
    assert "chrome_operation_mode: true" in js
    assert 'method === "item/agentMessage/delta"' in js
    assert "payload.id !== undefined" in js
    assert "showApprovalRequest" in js
    assert 'action: "accept"' in js
    assert 'action: "decline"' in js
    assert 'type: "octopus.control"' in js
    assert "toggleControlStop" in js


def test_background_opens_sidepanel_and_keeps_bookmarklet_fallback() -> None:
    js = (EXTENSION / "background.js").read_text(encoding="utf-8")

    assert "chrome.sidePanel.setPanelBehavior" in js
    assert "openPanelOnActionClick" in js
    assert "openSidePanel" in js
    assert "openPageAgent" in js
    assert 'type === "octopus.status"' in js
    assert 'type === "octopus.openPageAgent"' in js


def test_background_enforces_tab_control_lease() -> None:
    js = (EXTENSION / "background.js").read_text(encoding="utf-8")

    assert "validateCommandLease" in js
    assert "browser_relay_control_interrupted" in js
    assert "setPageControlIndicator" in js
    assert '"octopus.controlIndicator"' in js
    assert "active_tab_changed" in js
    assert "tab_url_changed" in js
    assert 'type === "octopus.control"' in js
    assert 'type === "octopus.userActivity"' in js
    assert "/api/control-sessions" in js
    assert "ensureControlSessionForCommand" in js
    assert "appendControlAction" in js
    assert "appendControlEvidence" in js
    assert "/takeover" in js
    assert "chrome_human_interrupt" in js


def test_content_script_reports_trusted_user_activity() -> None:
    js = (EXTENSION / "content.js").read_text(encoding="utf-8")

    assert "reportUserActivity" in js
    assert "event?.isTrusted" in js
    assert 'type: "octopus.userActivity"' in js
    assert '"pointerdown"' in js
    assert '"input"' in js


def test_content_script_renders_nonblocking_edge_light_not_aurora_overlay() -> None:
    js = (EXTENSION / "content.js").read_text(encoding="utf-8")

    assert "octopus-browser-control-indicator" in js
    assert "pointer-events: none" in js
    assert "position: fixed" in js
    assert "inset: 0" in js
    assert "box-shadow:" in js
    assert "octopus-control-edge-pulse" in js
    assert "prefers-reduced-motion" in js
    assert "aurora" not in js.lower()
    assert "linear-gradient" not in js.lower()
