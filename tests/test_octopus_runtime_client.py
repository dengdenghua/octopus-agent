from __future__ import annotations

import hashlib
from typing import Any

import httpx
import pytest

from octopus_runtime.client import RegistryClient


class FakeResponse:
    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def test_fetch_verifies_checksum_even_when_body_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **_kwargs: Any) -> FakeResponse:
        assert url.endswith("/skill/empty/download")
        return FakeResponse(
            payload={
                "data": {
                    "id": "skill/empty",
                    "type": "skill",
                    "kind": "data",
                    "content": {"checksum": "sha256:" + ("0" * 64)},
                    "body": "",
                }
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError, match="checksum mismatch"):
        RegistryClient("https://registry.test").fetch("skill/empty")


def test_fetch_rejects_unsafe_asset_id_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError, match="unsafe registry asset id"):
        RegistryClient("https://registry.test").fetch("skill/../escape")

    assert called is False


def test_fetch_rejects_malformed_content_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(
            payload={
                "data": {
                    "id": "skill/bad",
                    "type": "skill",
                    "kind": "data",
                    "content": {"checksum": "md5:not-accepted"},
                    "body": "hello",
                }
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError, match="invalid sha256 checksum"):
        RegistryClient("https://registry.test").fetch("skill/bad")


def test_fetch_accepts_uppercase_sha256_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "hello"
    expected = hashlib.sha256(body.encode("utf-8")).hexdigest().upper()

    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(
            payload={
                "data": {
                    "id": "skill/ok",
                    "type": "skill",
                    "kind": "data",
                    "content": {"checksum": "sha256:" + expected},
                    "body": body,
                }
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    payload = RegistryClient("https://registry.test").fetch("skill/ok")

    assert payload.id == "skill/ok"
    assert payload.body == body


def test_fetch_accepts_safe_asset_id_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_get(url: str, **_kwargs: Any) -> FakeResponse:
        captured.append(url)
        return FakeResponse(
            payload={
                "data": {
                    "id": "twin-role/operator_1.2",
                    "type": "twin-role",
                    "kind": "data",
                    "body": "hello",
                }
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    payload = RegistryClient("https://registry.test").fetch("twin-role/operator_1.2")

    assert payload.id == "twin-role/operator_1.2"
    assert captured == [
        "https://registry.test/api/v1/registry/assets/twin-role/operator_1.2/download"
    ]


def test_fetch_bundle_rejects_malformed_header_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(content=b"bundle", headers={"X-Checksum-Sha256": "bad"})

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError, match="invalid sha256 checksum"):
        RegistryClient("https://registry.test").fetch_bundle("skill/bad")


def test_fetch_bundle_rejects_unsafe_asset_id_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError, match="unsafe registry asset id"):
        RegistryClient("https://registry.test").fetch_bundle("skill/name?bad=1")

    assert called is False


def test_fetch_bundle_accepts_sha256_header(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"bundle"

    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(
            content=content,
            headers={"X-Checksum-Sha256": hashlib.sha256(content).hexdigest()},
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    assert RegistryClient("https://registry.test").fetch_bundle("skill/ok") == content
