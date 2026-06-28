from __future__ import annotations

from runtime.platform.runtime_policy.computer_automation import (
    app_permission_decision,
    load_computer_automation_policy,
    save_computer_automation_policy,
)


def test_computer_automation_policy_round_trips_allow_deny_prompt(tmp_path) -> None:
    path = tmp_path / "computer_policy.json"

    saved = save_computer_automation_policy(
        {
            "allowed_apps": ["Chrome", "Chrome"],
            "denied_apps": ["Keychain Access"],
            "preview_required": True,
            "lease_required": True,
        },
        path=path,
    )
    loaded = load_computer_automation_policy(path)

    assert saved["schema"] == "octopus.computer_automation_policy.v1"
    assert loaded["persisted"] is True
    assert loaded["allowed_apps"] == ["Chrome"]
    assert loaded["denied_apps"] == ["Keychain Access"]
    assert app_permission_decision(loaded, target_app="Chrome")["decision"] == "allowed"
    assert app_permission_decision(loaded, target_app="Keychain Access")["decision"] == "denied"
    assert app_permission_decision(loaded, target_app="Preview")["decision"] == "prompt"
