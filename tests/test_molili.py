"""Implementation note."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.adapters.integrations.molili import (  # noqa: E402
    MoliliAuthConfig,
    MoliliConfig,
    MoliliLink,
    MoliliLinkStore,
    load_molili_config_from_dict,
)
from runtime.adapters.integrations.molili.client import (  # noqa: E402
    detect_dead_token,
    mask_phone,
    pluck,
)
from runtime.platform.ui import create_app  # noqa: E402
from runtime.safety.auth.identity import (  # noqa: E402
    Identity,
    IdentityStore,
    encode_jwt_hs256,
)

# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class _FakeResp:
    def __init__(self, body: Any, status: int = 200):
        self._body = body
        self.status_code = status
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self.content = self._text.encode()
        else:
            self._text = str(body or "")
            self.content = self._text.encode()

    @property
    def text(self) -> str:
        return self._text

    def json(self) -> Any:
        if isinstance(self._body, (dict, list)):
            return self._body
        raise ValueError("not json")


class _FakeHttp:
    """Implementation note."""

    def __init__(self) -> None:
        self.post_routes: dict[str, _FakeResp | list[_FakeResp]] = {}
        self.get_routes: dict[str, _FakeResp | list[_FakeResp]] = {}
        self.post_calls: list[tuple[str, dict]] = []
        self.get_calls: list[tuple[str, dict]] = []

    def _pick(
        self, routes: dict[str, Any], url: str,
    ) -> _FakeResp:
        for u, v in routes.items():
            if url.startswith(u):
                if isinstance(v, list):
                    return v.pop(0) if len(v) > 1 else v[0]
                return v
        return _FakeResp({"error": "no route"}, 404)

    def post(
        self, url: str, *, json=None, headers=None, content=None, timeout=None,
        **kw: Any,
    ) -> _FakeResp:
        self.post_calls.append((url, json or {}))
        return self._pick(self.post_routes, url)

    def get(
        self, url: str, *, headers=None, params=None, timeout=None, **kw: Any,
    ) -> _FakeResp:
        self.get_calls.append((url, params or {}))
        return self._pick(self.get_routes, url)


# ═══════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════


class TestConfig:
    def test_defaults_disabled(self):
        c = MoliliConfig()
        assert c.enabled is False
        assert c.base_url.startswith("https://molili")

    def test_load_from_dict(self):
        c = load_molili_config_from_dict({
            "enabled": True,
            "base_url": "https://x/y",
            "auth": {"sms_send_url": "https://s", "sms_verify_url": "https://v"},
        })
        assert c.enabled is True
        assert c.auth.sms_send_url == "https://s"

    def test_legacy_phone_field_migration(self):
        c = MoliliAuthConfig(phone_field="telephone")
        # Implementation note.
        assert c.verify_phone_field == "telephone"

    def test_explicit_verify_phone_field_wins(self):
        c = MoliliAuthConfig(phone_field="old", verify_phone_field="new")
        assert c.verify_phone_field == "new"

    def test_none_returns_default(self):
        c = load_molili_config_from_dict(None)
        assert c.enabled is False


# ═══════════════════════════════════════════════════════════
# Link store
# ═══════════════════════════════════════════════════════════


class TestLinkStore:
    def test_get_missing(self, tmp_path: Path):
        s = MoliliLinkStore(path=tmp_path / "l.json")
        assert s.get("actor-x") is None

    def test_put_then_get(self, tmp_path: Path):
        s = MoliliLinkStore(path=tmp_path / "l.json")
        link = MoliliLink(
            octopus_user_id="alice",
            molili_user_id="m-123",
            molili_token="t-456",
            linked_at=time.time(),
        )
        s.put(link)
        got = s.get("alice")
        assert got is not None
        assert got.molili_user_id == "m-123"
        # Implementation note.
        s2 = MoliliLinkStore(path=tmp_path / "l.json")
        assert s2.get("alice") is not None

    def test_delete(self, tmp_path: Path):
        s = MoliliLinkStore(path=tmp_path / "l.json")
        s.put(MoliliLink(octopus_user_id="a", molili_user_id="m", molili_token="t"))
        assert s.delete("a") is True
        assert s.get("a") is None
        assert s.delete("a") is False

    def test_update_credits_clears_invalid_flag(self, tmp_path: Path):
        s = MoliliLinkStore(path=tmp_path / "l.json")
        link = MoliliLink(
            octopus_user_id="a",
            molili_user_id="m",
            molili_token="t",
            token_invalid=True,
            token_invalid_reason="BE_REPLACED",
        )
        s.put(link)
        updated = s.update_credits("a", {"surplusCredits": 100}, now=time.time())
        assert updated is not None
        assert updated.token_invalid is False
        assert updated.token_invalid_reason is None
        assert updated.credits_snapshot == {"surplusCredits": 100}

    def test_mark_token_invalid(self, tmp_path: Path):
        s = MoliliLinkStore(path=tmp_path / "l.json")
        s.put(MoliliLink(octopus_user_id="a", molili_user_id="m", molili_token="t"))
        got = s.mark_token_invalid("a", "TOKEN_EXPIRED: xxx")
        assert got is not None
        assert got.token_invalid is True
        assert "TOKEN_EXPIRED" in (got.token_invalid_reason or "")

    def test_update_credits_missing_link(self, tmp_path: Path):
        s = MoliliLinkStore(path=tmp_path / "l.json")
        assert s.update_credits("ghost", {}, now=0.0) is None

    def test_malformed_json_graceful(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid", encoding="utf-8")
        s = MoliliLinkStore(path=p)
        # Implementation note.
        assert s.get("a") is None


# ═══════════════════════════════════════════════════════════
# client helpers
# ═══════════════════════════════════════════════════════════


class TestClientHelpers:
    def test_pluck_happy(self):
        assert pluck({"a": {"b": {"c": 1}}}, "a.b.c") == 1

    def test_pluck_missing(self):
        assert pluck({"a": 1}, "a.b") is None
        assert pluck(None, "x") is None
        assert pluck({}, None) is None

    def test_mask_phone(self):
        assert mask_phone("13800001234") == "***1234"
        assert mask_phone("12") == "***"

    def test_detect_dead_token_be_replaced(self):
        assert detect_dead_token({"success": False, "errCode": "BE_REPLACED"}) is not None

    def test_detect_dead_token_success(self):
        assert detect_dead_token({"success": True}) is None

    def test_detect_dead_token_non_dict(self):
        assert detect_dead_token(None) is None
        assert detect_dead_token("text") is None


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


JWT_SECRET = "test-jwt-secret-at-least-32-chars-long-abc-xyz"


@pytest.fixture
def cfg() -> MoliliConfig:
    return MoliliConfig(
        enabled=True,
        base_url="https://m.example/chatApi/v1",
        info_url="https://m.example/userApi/v1/userInfo",
        auth=MoliliAuthConfig(
            sms_send_url="https://m.example/userApi/v1/sendSms",
            sms_verify_url="https://m.example/userApi/v1/loginByMobile",
        ),
        jwt_secret=JWT_SECRET,
    )


@pytest.fixture
def store(tmp_path: Path) -> MoliliLinkStore:
    return MoliliLinkStore(path=tmp_path / "l.json")


@pytest.fixture
def identity_store() -> IdentityStore:
    return IdentityStore()


@pytest.fixture
def http() -> _FakeHttp:
    return _FakeHttp()


def _app_with(cfg: MoliliConfig, store: MoliliLinkStore, identity_store, http):
    """Implementation note."""
    from fastapi import FastAPI

    from runtime.adapters.integrations.molili.router_account import create_account_router
    from runtime.adapters.integrations.molili.router_auth import create_auth_router
    from runtime.adapters.integrations.molili.router_proxy import create_proxy_router

    app = FastAPI()
    app.include_router(create_auth_router(
        config=cfg, link_store=store, identity_store=identity_store, http_client=http,
    ))
    app.include_router(create_account_router(
        config=cfg, link_store=store, identity_store=identity_store, http_client=http,
    ))
    app.include_router(create_proxy_router(
        config=cfg, link_store=store, identity_store=identity_store, http_client=http,
    ))
    return app


def _bearer_for(actor: str) -> dict[str, str]:
    now = int(time.time())
    jwt = encode_jwt_hs256(
        {"sub": actor, "iat": now, "exp": now + 3600, "iss": "octopus-agent"},
        secret=JWT_SECRET,
    )
    return {"Authorization": f"Bearer {jwt}"}


class TestSmsFlow:
    def test_send_ok(self, cfg, store, identity_store, http):
        http.post_routes["https://m.example/userApi/v1/sendSms"] = _FakeResp(
            {"success": True, "data": {}},
        )
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post("/api/auth/molili/sms/send", json={"phone": "13800001234"})
        assert r.status_code == 200
        assert r.json()["sent"] is True
        # Implementation note.
        call_body = http.post_calls[0][1]
        assert call_body.get("mobile") == "13800001234"

    def test_verify_creates_link_and_identity(
        self, cfg, store, identity_store, http,
    ):
        http.post_routes["https://m.example/userApi/v1/loginByMobile"] = _FakeResp({
            "success": True,
            "data": {
                "userId": "molili-77",
                "token": "tkn-abc",
                "userInfo": {"mobile": "138****1234", "surplusCredits": 500},
            },
        })
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/auth/molili/sms/verify",
            json={"phone": "13800001234", "code": "123456"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["actor_id"].startswith("molili:")
        assert data["access_token"]  # Implementation note.
        # Implementation note.
        assert identity_store.get(data["actor_id"]) is not None
        # Implementation note.
        link = store.get(data["actor_id"])
        assert link is not None
        assert link.molili_user_id == "molili-77"
        assert link.molili_token == "tkn-abc"
        assert link.credits_snapshot["surplusCredits"] == 500

    def test_verify_missing_userid_fails_502(
        self, cfg, store, identity_store, http,
    ):
        http.post_routes["https://m.example/userApi/v1/loginByMobile"] = _FakeResp(
            {"success": True, "data": {"token": "t"}},  # Implementation note.
        )
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/auth/molili/sms/verify",
            json={"phone": "138", "code": "1"},
        )
        assert r.status_code == 502

    def test_disabled_returns_503(self, cfg, store, identity_store, http):
        cfg2 = cfg.model_copy(update={"enabled": False})
        client = TestClient(_app_with(cfg2, store, identity_store, http))
        r = client.post(
            "/api/auth/molili/sms/send", json={"phone": "138"},
        )
        assert r.status_code == 503


class TestAccountLink:
    def test_link_manual(self, cfg, store, identity_store, http):
        actor = "molili:13800001234"
        identity_store.add(Identity(actor_id=actor))
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/link",
            json={"molili_user_id": "m-1", "molili_token": "t-1"},
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["molili_user_id"] == "m-1"

    def test_show_requires_link(self, cfg, store, identity_store, http):
        actor = "molili:ghost"
        identity_store.add(Identity(actor_id=actor))
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get("/api/account/molili", headers=_bearer_for(actor))
        assert r.status_code == 404

    def test_show_ok_after_link(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get("/api/account/molili", headers=_bearer_for(actor))
        assert r.status_code == 200
        assert r.json()["molili_user_id"] == "m"

    def test_unlink(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.delete("/api/account/molili/link", headers=_bearer_for(actor))
        assert r.status_code == 200
        assert r.json()["unlinked"] is True
        assert store.get(actor) is None

    def test_unauth_returns_401(self, cfg, store, identity_store, http):
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get("/api/account/molili")
        assert r.status_code == 401


class TestRefreshCredits:
    def test_refresh_pulls_info_and_balance(
        self, cfg, store, identity_store, http,
    ):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))

        http.get_routes["https://m.example/goodsApi/v1/goodsDetailList"] = _FakeResp(
            {"success": True, "data": []},
        )
        http.get_routes["https://m.example/userApi/v1/userInfo"] = _FakeResp({
            "success": True, "data": {"userId": "m", "mobile": "138", "surplusCredits": 100},
        })
        http.get_routes["https://m.example/creditsApi/v1/surplusCreditsQuery"] = _FakeResp({
            "success": True, "data": 888,
        })
        http.post_routes["https://m.example/creditsApi/v1/page"] = _FakeResp({
            "success": True,
            "data": {
                "records": [
                    {"type": "invite", "credits": 10, "surplusCredits": 5},
                    {"type": "pay", "credits": 1000, "surplusCredits": 883},
                ],
            },
        })

        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/refresh", headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["credits"]["surplusCredits"] == 888
        assert data["credits"]["creditsSummary"]["total_remaining"] == 888
        assert data["credits"]["creditsSummary"]["by_type"]["invite"]["remaining"] == 5

    def test_refresh_detects_dead_token(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))

        http.get_routes["https://m.example/goodsApi/v1/goodsDetailList"] = _FakeResp(
            {"success": False, "errCode": "BE_REPLACED", "errMessage": "别处登录了"},
        )
        http.get_routes["https://m.example/userApi/v1/userInfo"] = _FakeResp({
            "success": True, "data": {"userId": "m"},
        })
        http.post_routes["https://m.example/creditsApi/v1/page"] = _FakeResp({
            "success": True, "data": {"records": []},
        })

        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/refresh", headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["token_invalid"] is True
        assert "BE_REPLACED" in data["token_invalid_reason"]
        # Implementation note.
        link = store.get(actor)
        assert link is not None
        assert link.token_invalid is True

    def test_refresh_no_info_url_noop(self, cfg, store, identity_store, http):
        cfg2 = cfg.model_copy(update={"info_url": None})
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(
            octopus_user_id=actor, molili_user_id="m", molili_token="t",
            credits_snapshot={"cached": True},
        ))
        client = TestClient(_app_with(cfg2, store, identity_store, http))
        r = client.post(
            "/api/account/molili/refresh", headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        # Implementation note.
        assert r.json()["credits"] == {"cached": True}
        assert http.get_calls == []


class TestDailyClaim:
    def test_info(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.get_routes["https://m.example/dailyCreditsClaimApi/v1/info"] = _FakeResp({
            "success": True, "data": {"claimed": False, "fixed": 50},
        })
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get(
            "/api/account/molili/daily-claim/info", headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["data"]["claimed"] is False

    def test_claim_direct(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.post_routes["https://m.example/dailyCreditsClaimApi/v1/claim"] = _FakeResp({
            "success": True, "data": {"credits": 50},
        })
        # Implementation note.
        http.get_routes["https://m.example/userApi/v1/userInfo"] = _FakeResp({
            "success": True, "data": {"userId": "m"},
        })
        http.get_routes["https://m.example/goodsApi/v1/goodsDetailList"] = _FakeResp({
            "success": True, "data": [],
        })
        http.post_routes["https://m.example/creditsApi/v1/page"] = _FakeResp({
            "success": True, "data": {"records": []},
        })

        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/daily-claim/claim",
            json={"draw": False},
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["data"]["credits"] == 50
        # Implementation note.
        claim_call = next(
            b for u, b in http.post_calls if "dailyCreditsClaim" in u
        )
        assert claim_call["claimType"] == "direct"

    def test_claim_lottery(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.post_routes["https://m.example/dailyCreditsClaimApi/v1/claim"] = _FakeResp({
            "success": True, "data": {"credits": 88},
        })
        http.get_routes["https://m.example/userApi/v1/userInfo"] = _FakeResp({
            "success": True, "data": {},
        })
        http.get_routes["https://m.example/goodsApi/v1/goodsDetailList"] = _FakeResp({
            "success": True, "data": [],
        })
        http.post_routes["https://m.example/creditsApi/v1/page"] = _FakeResp({
            "success": True, "data": {"records": []},
        })

        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/daily-claim/claim",
            json={"draw": True},
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        claim_call = next(
            b for u, b in http.post_calls if "dailyCreditsClaim" in u
        )
        assert claim_call["claimType"] == "lottery"


class TestOrders:
    def test_payment_link(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.post_routes["https://m.example/orderApi/v1/paymentLink"] = _FakeResp({
            "success": True,
            "data": {"paymentLink": "weixin://wxpay/xxx", "orderNo": "OD-001"},
        })
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/orders/payment-link",
            json={"goods_id": 42},
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["data"]["orderNo"] == "OD-001"

    def test_find_order(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.get_routes["https://m.example/orderApi/v1/findByOrderNo"] = _FakeResp({
            "success": True, "data": {"orderStatus": 200, "orderNo": "OD-001"},
        })
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get(
            "/api/account/molili/orders/OD-001", headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["data"]["orderStatus"] == 200

    def test_confirm_paid_triggers_refresh(
        self, cfg, store, identity_store, http,
    ):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.get_routes["https://m.example/orderApi/v1/findByOrderNo"] = _FakeResp({
            "success": True, "data": {"orderStatus": 200},  # Implementation note.
        })
        # Implementation note.
        http.get_routes["https://m.example/userApi/v1/userInfo"] = _FakeResp({
            "success": True, "data": {},
        })
        http.get_routes["https://m.example/goodsApi/v1/goodsDetailList"] = _FakeResp({
            "success": True, "data": [],
        })
        http.post_routes["https://m.example/creditsApi/v1/page"] = _FakeResp({
            "success": True, "data": {"records": []},
        })

        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/orders/OD-001/confirm",
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["paid"] is True
        assert data["order_status"] == 200

    def test_confirm_not_paid(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        http.get_routes["https://m.example/orderApi/v1/findByOrderNo"] = _FakeResp({
            "success": True, "data": {"orderStatus": 0},  # Implementation note.
        })
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/account/molili/orders/OD-9/confirm",
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["paid"] is False


class TestProxy:
    def test_models_listed(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m", molili_token="t"))
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get(
            "/api/molili/openai/v1/models", headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()["data"]]
        assert "molili" in ids
        assert "kimi-k2.5" in ids

    def test_models_requires_link(self, cfg, store, identity_store, http):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.get(
            "/api/molili/openai/v1/models", headers=_bearer_for(actor),
        )
        assert r.status_code == 404

    def test_chat_completions_non_stream(
        self, cfg, store, identity_store, http,
    ):
        actor = "molili:1"
        identity_store.add(Identity(actor_id=actor))
        store.put(MoliliLink(octopus_user_id=actor, molili_user_id="m-xyz", molili_token="t"))
        http.post_routes["https://m.example/chatApi/v1/chat/completions"] = _FakeResp({
            "id": "chat-1",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        })
        client = TestClient(_app_with(cfg, store, identity_store, http))
        r = client.post(
            "/api/molili/openai/v1/chat/completions",
            json={"model": "molili", "messages": [{"role": "user", "content": "hi"}]},
            headers=_bearer_for(actor),
        )
        assert r.status_code == 200
        assert r.json()["id"] == "chat-1"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestCreateAppWiring:
    def test_molili_disabled_no_routes(self, tmp_path: Path):
        cfg = MoliliConfig(enabled=False)
        app = create_app(
            journal_path=tmp_path / "j.jsonl", molili_config=cfg,
        )
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert not any("molili" in p for p in paths)

    def test_molili_enabled_mounts_all(self, tmp_path: Path):
        cfg = MoliliConfig(
            enabled=True,
            auth=MoliliAuthConfig(
                sms_send_url="https://x/s", sms_verify_url="https://x/v",
            ),
        )
        store = MoliliLinkStore(path=tmp_path / "l.json")
        app = create_app(
            journal_path=tmp_path / "j.jsonl",
            molili_config=cfg,
            molili_link_store=store,
        )
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/auth/molili/sms/send" in paths
        assert "/api/auth/molili/sms/verify" in paths
        assert "/api/account/molili/link" in paths
        assert "/api/molili/openai/v1/models" in paths
        assert "/api/molili/openai/v1/chat/completions" in paths

    def test_create_app_molili_login_token_unlocks_account(
        self, tmp_path: Path,
    ):
        cfg = MoliliConfig(
            enabled=True,
            jwt_secret=JWT_SECRET,
            auth=MoliliAuthConfig(mock_mode=True, mock_code="123456"),
        )
        store = MoliliLinkStore(path=tmp_path / "l.json")
        app = create_app(
            journal_path=tmp_path / "j.jsonl",
            molili_config=cfg,
            molili_link_store=store,
        )
        client = TestClient(app)

        r = client.post(
            "/api/auth/molili/sms/verify",
            json={"phone": "13800001234", "code": "123456"},
        )
        assert r.status_code == 200
        token = r.json()["access_token"]

        account = client.get(
            "/api/account/molili",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert account.status_code == 200
        assert account.json()["molili_user_id"] == "mock-13800001234"


def test_actor_from_identifier_phone_vs_email() -> None:
    """Email login must not collapse all users to a single actor.

    The gateway uses email login; digits-only extraction would map every email
    to ``molili:`` (one shared identity). Distinct emails → distinct actors;
    pure phones still key on digits (back-compat).
    """
    from runtime.adapters.integrations.molili.router_auth import _actor_from_phone

    assert _actor_from_phone("13800138000") == "molili:13800138000"
    assert _actor_from_phone("+8613800138000") == "molili:+8613800138000"
    assert _actor_from_phone("a@x.com") == "molili:a@x.com"
    assert _actor_from_phone("a@x.com") != _actor_from_phone("b@x.com")
