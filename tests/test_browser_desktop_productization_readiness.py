from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.browser_desktop_productization_readiness import (
    compute_browser_desktop_productization_readiness,
    run_browser_desktop_productization_probe,
)


def test_browser_desktop_productization_readiness_is_complete() -> None:
    report = compute_browser_desktop_productization_readiness()

    assert report["schema"] == "octopus.browser_desktop_productization_readiness.v1"
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["missing_count"] == 0
    assert report["probe"]["ok"] is True
    assert report["probe"]["manifest_ready"] is True
    assert report["probe"]["relay_loop_ready"] is True
    assert report["probe"]["computer_policy_endpoint_ready"] is True
    assert report["probe"]["policy_probe"]["ok"] is True
    assert {row["id"] for row in report["checks"]} >= {
        "chrome_relay_extension_surface",
        "chrome_relay_backend_control_plane",
        "signed_in_browser_fallback",
        "desktop_app_permission_policy",
        "desktop_preview_execute_product_loop",
        "desktop_grounding_modes",
        "browser_desktop_product_tests",
    }
    assert report["next_actions"] == [
        "Browser/desktop productization checks are ready.",
    ]


def test_browser_desktop_productization_readiness_detects_missing_root(
    tmp_path: Path,
) -> None:
    report = compute_browser_desktop_productization_readiness(root=tmp_path)

    assert report["ready"] is False
    assert report["score"] < 1.0
    assert report["missing_count"] > 0
    assert report["next_actions"]


def test_browser_desktop_productization_probe_validates_policy_and_relay() -> None:
    probe = run_browser_desktop_productization_probe()

    assert probe["schema"] == "octopus.browser_desktop_productization_probe.v1"
    assert probe["ok"] is True
    assert probe["policy_probe"]["allowed_decision"]["decision"] == "allowed"
    assert probe["policy_probe"]["denied_decision"]["decision"] == "denied"
    assert probe["policy_probe"]["prompt_decision"]["decision"] == "prompt"
