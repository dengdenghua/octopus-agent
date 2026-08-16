"""Dense coverage for discord channel verify/webhook/ts (audit Q-05)."""

from __future__ import annotations

import json

import pytest

from runtime.adapters.channels.discord import (
    DiscordChannel,
    DiscordSignatureError,
    _parse_discord_ts,
)

PUBLIC_KEY = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
BAD_PUBLIC_KEY = "zzzz"


def _channel(**kw) -> DiscordChannel:
    kw.setdefault("bot_token", "tok")
    kw.setdefault("public_key", PUBLIC_KEY)
    kw.setdefault("channel_id", "discord")
    return DiscordChannel(**kw)


def test_constructor_validation() -> None:
    with pytest.raises(ValueError):
        DiscordChannel(bot_token="", public_key=PUBLIC_KEY)
    with pytest.raises(ValueError):
        DiscordChannel(bot_token="t", public_key=BAD_PUBLIC_KEY)


def test_verify_signature_error_paths() -> None:
    ch = _channel()
    with pytest.raises(DiscordSignatureError):
        ch.verify_signature(body=b"x", signature_hex="", timestamp="")
    with pytest.raises(DiscordSignatureError):
        ch.verify_signature(body=b"x", signature_hex="nothex", timestamp="t")


def test_verify_signature_success() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    from cryptography.hazmat.primitives import serialization

    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ch = DiscordChannel(bot_token="t", public_key=raw.hex())
    body = b'{"type":1}'
    ts = "1700000000"
    sig = priv.sign(ts.encode() + body).hex()
    ch.verify_signature(body=body, signature_hex=sig, timestamp=ts)  # no raise


def test_handle_webhook_ping_and_command(monkeypatch) -> None:
    ch = _channel()
    # verify_signature has its own tests; here we exercise the payload logic.
    monkeypatch.setattr(ch, "verify_signature", lambda **kw: None)

    ping = ch.handle_webhook(body=b'{"type":1}', headers={})
    assert ping == {"type": 1}

    payload = {
        "type": 2,
        "id": "i1",
        "channel_id": "c1",
        "guild_id": "g1",
        "member": {"user": {"id": "u1"}},
        "data": {"name": "ask", "options": [{"value": "hello"}]},
        "message": {"id": "m1", "attachments": [{"url": "http://a/1", "filename": "f.png"}]},
    }
    body = json.dumps(payload).encode()
    msg = ch.handle_webhook(body=body, headers={})
    assert msg is not None
    assert msg.sender_id == "u1"
    assert msg.thread_id == "c1"
    assert "hello" in msg.content
    assert msg.attachments and msg.attachments[0].filename == "f.png"

    with pytest.raises(ValueError):
        ch.handle_webhook(body=b"not json", headers={})


def test_parse_discord_ts() -> None:
    assert _parse_discord_ts("2026-08-17T12:00:00Z") is not None
    assert _parse_discord_ts("bad") is None
    assert _parse_discord_ts(None) is None
