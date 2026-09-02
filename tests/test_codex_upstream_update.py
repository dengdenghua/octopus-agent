from __future__ import annotations

import pytest

from runtime.execution.codex_backend.upstream_update import (
    CodexUpstreamUpdateService,
)


def _metadata(version: str = "0.150.0") -> dict[str, object]:
    return {
        "version": version,
        "dist": {
            "integrity": "sha512-approved",
            "tarball": f"https://registry.npmjs.org/codex/-/codex-{version}.tgz",
        },
    }


def test_detects_and_persists_new_codex_release(tmp_path):
    service = CodexUpstreamUpdateService(
        tmp_path / "status.json",
        current_version="0.149.0",
        fetcher=lambda _url, _timeout: _metadata(),
    )

    status = service.check()

    assert status.update_available is True
    assert status.latest_version == "0.150.0"
    assert status.approval_status == "pending"
    assert status.integrity == "sha512-approved"
    assert service.read() == status


def test_approval_only_marks_candidate_for_next_octopus_release(tmp_path):
    service = CodexUpstreamUpdateService(
        tmp_path / "status.json",
        current_version="0.149.0",
        fetcher=lambda _url, _timeout: _metadata(),
    )
    service.check()

    approved = service.approve("0.150.0")

    assert approved.approval_status == "approved_for_next_release"
    assert approved.approved_version == "0.150.0"
    assert approved.approved_at
    assert service.read().tarball_url.endswith("codex-0.150.0.tgz")


def test_rejects_stale_or_unknown_approval(tmp_path):
    service = CodexUpstreamUpdateService(
        tmp_path / "status.json",
        current_version="0.149.0",
        fetcher=lambda _url, _timeout: _metadata(),
    )
    service.check()

    try:
        service.approve("0.151.0")
    except ValueError as exc:
        assert "not current" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("stale candidate approval must fail")


def test_network_failure_preserves_last_good_candidate(tmp_path):
    calls = 0

    def fetch(_url: str, _timeout: float):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _metadata()
        raise TimeoutError("upstream timed out")

    service = CodexUpstreamUpdateService(
        tmp_path / "status.json",
        current_version="0.149.0",
        fetcher=fetch,
    )
    service.check()

    failed = service.check()

    assert failed.latest_version == "0.150.0"
    assert failed.update_available is True
    assert failed.error == "upstream timed out"


def test_rejects_unverified_or_insecure_metadata(tmp_path):
    service = CodexUpstreamUpdateService(
        tmp_path / "status.json",
        current_version="0.149.0",
        fetcher=lambda _url, _timeout: {
            "version": "0.150.0",
            "dist": {"tarball": "http://example.test/codex.tgz"},
        },
    )

    status = service.check()

    assert status.update_available is False
    assert status.error == "Codex package integrity is missing"


def test_optional_radar_is_inert_when_bundled_runtime_is_unavailable(tmp_path, monkeypatch):
    def unavailable() -> str:
        raise RuntimeError("bundled Codex version is unavailable")

    monkeypatch.setattr(
        "runtime.execution.codex_backend.upstream_update.resolve_bundled_codex_version",
        unavailable,
    )
    service = CodexUpstreamUpdateService(
        tmp_path / "status.json",
        allow_unavailable=True,
        fetcher=lambda _url, _timeout: pytest.fail("unavailable radar must not fetch"),
    )

    status = service.check()

    assert status.available is False
    assert status.current_version is None
    assert status.update_available is False
    assert status.error == "bundled Codex version is unavailable"
    assert not (tmp_path / "status.json").exists()
    service.start()
    assert service._task is None
    with pytest.raises(ValueError, match="runtime is unavailable"):
        service.approve("0.150.0")


@pytest.mark.parametrize(
    "registry_url",
    [
        "http://registry.example.test/latest",
        "file:///etc/passwd",
        "https://user:secret@registry.example.test/latest",
        "https:///missing-host",
    ],
)
def test_rejects_unsafe_registry_urls_before_fetch(tmp_path, registry_url):
    with pytest.raises(
        ValueError,
        match="unauthenticated HTTPS URL",
    ):
        CodexUpstreamUpdateService(
            tmp_path / "status.json",
            current_version="0.149.0",
            registry_url=registry_url,
        )
