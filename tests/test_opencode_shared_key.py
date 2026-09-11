from types import SimpleNamespace

from runtime.platform.connectors.auth_orchestrator import AuthOrchestrator
from runtime.platform.connectors.credential_store import CredentialStore


def test_go_reuses_key_and_tracks_rotation_without_copy(tmp_path):
    store = CredentialStore(root=tmp_path)
    store.set_secret("opencode-zen", "api_key", "first-key")
    auth = AuthOrchestrator(credentials=store)
    conn = SimpleNamespace(id="opencode-go", auth_mode="token")
    assert auth.connect(conn)["connected"]
    assert store.get_secret("opencode-go", "api_key") == "first-key"
    assert "api_key" in store.list_secrets("opencode-go")
    assert "api_key" not in store._read_all()["connectors"]["opencode-go"]
    store.set_secret("opencode-zen", "api_key", "rotated-key")
    assert store.get_secret("opencode-go", "api_key") == "rotated-key"
    store.clear_connector("opencode-go")
    assert store.get_secret("opencode-zen", "api_key") == "rotated-key"
    assert not store.has_credentials("opencode-go")


def test_go_first_stores_shared_key_for_zen(tmp_path):
    store = CredentialStore(root=tmp_path)
    auth = AuthOrchestrator(credentials=store)
    conn = SimpleNamespace(id="opencode-go", auth_mode="token")
    auth.connect(conn, tokens={"api_key": "shared-key"})
    assert store.get_secret("opencode-zen", "api_key") == "shared-key"
    assert store.get_secret("opencode-go", "api_key") == "shared-key"
