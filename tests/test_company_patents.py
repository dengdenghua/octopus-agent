"""Tests for patent / FTO endpoints in the company router.

Covers:
- Patent search topic CRUD
- Patent record CRUD + dedup (publication_number / application_number)
- Patent record bulk import (the path used by the patent-import-xlsx skill)
- Patent risk creation with forced attorney-review for high+ risks
- 404 / 400 error paths
"""
from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.company.api import create_company_router  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_company_router(state_path=tmp_path / "company_projects.json"),
    )
    return TestClient(app)


def _create_project(client: TestClient) -> str:
    r = client.post(
        "/api/company/projects",
        json={
            "name": "SleepFlow Phase1",
            "industry": "hardware-startup",
            "stage": "prototype",
        },
    )
    assert r.status_code == 200
    return str(r.json()["id"])


# ── Topic CRUD ─────────────────────────────────────────────────────────


def test_create_and_list_patent_topic(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)

    r = client.post(
        f"/api/company/projects/{project_id}/patents/topics",
        json={
            "title": "床垫温度调控",
            "module": "sensor",
            "keywords_zh": ["床垫", "温度调控"],
            "keywords_en": ["mattress", "temperature regulation"],
        },
    )
    assert r.status_code == 200, r.text
    topic = r.json()
    assert topic["title"] == "床垫温度调控"
    assert topic["module"] == "sensor"
    assert topic["status"] == "not_started"

    r = client.get(f"/api/company/projects/{project_id}/patents/topics")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_create_patent_topic_unknown_project_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.post(
        "/api/company/projects/nope/patents/topics",
        json={"title": "X", "module": "sensor"},
    )
    assert r.status_code == 404


# ── Patent CRUD ────────────────────────────────────────────────────────


def test_create_and_list_patent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)

    r = client.post(
        f"/api/company/projects/{project_id}/patents",
        json={
            "title": "温度调控床垫系统",
            "applicant": "Eight Sleep Inc",
            "publication_number": "CN113711690B",
            "country": "CN",
            "legal_status": "active",
            "source": "manual",
            "relevance": "high",
        },
    )
    assert r.status_code == 200, r.text
    patent = r.json()
    assert patent["publication_number"] == "CN113711690B"
    assert patent["relevance"] == "high"

    r = client.get(f"/api/company/projects/{project_id}/patents")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["patents"][0]["title"] == "温度调控床垫系统"


def test_patent_dedup_on_publication_number(tmp_path: Path) -> None:
    """Creating a record with an already-used publication_number merges
    instead of creating a duplicate."""
    client = _client(tmp_path)
    project_id = _create_project(client)

    r1 = client.post(
        f"/api/company/projects/{project_id}/patents",
        json={
            "title": "原始标题",
            "publication_number": "CN113711690B",
            "country": "CN",
            "applicant": "",
        },
    )
    assert r1.status_code == 200
    record_id = r1.json()["id"]

    # Re-post with the same publication_number but more fields populated
    r2 = client.post(
        f"/api/company/projects/{project_id}/patents",
        json={
            "title": "更新后的标题",
            "publication_number": "CN113711690B",
            "country": "CN",
            "applicant": "Eight Sleep Inc",
            "abstract": "新增摘要",
        },
    )
    assert r2.status_code == 200

    # Should return the SAME record id with merged fields
    r_list = client.get(f"/api/company/projects/{project_id}/patents")
    assert r_list.json()["count"] == 1
    merged = r_list.json()["patents"][0]
    assert merged["id"] == record_id  # same record
    assert merged["title"] == "更新后的标题"  # title overwritten
    assert merged["applicant"] == "Eight Sleep Inc"  # filled in from empty
    assert merged["abstract"] == "新增摘要"


def test_patent_family_not_collapsed_by_dedup(tmp_path: Path) -> None:
    """Different publication numbers (US, CN, EP filings of the same patent
    family) MUST stay as separate records — they have different legal scope."""
    client = _client(tmp_path)
    project_id = _create_project(client)

    family = [
        {"title": "检测睡眠障碍", "publication_number": "US10105092B2", "country": "US",
         "applicant": "Eight Sleep Inc"},
        {"title": "检测睡眠障碍", "publication_number": "US11266348B2", "country": "US",
         "applicant": "Eight Sleep Inc"},
        {"title": "检测睡眠障碍", "publication_number": "EP3406196A1", "country": "EP",
         "applicant": "Eight Sleep Inc"},
    ]
    for item in family:
        r = client.post(
            f"/api/company/projects/{project_id}/patents",
            json=item,
        )
        assert r.status_code == 200, r.text

    r = client.get(f"/api/company/projects/{project_id}/patents")
    assert r.json()["count"] == 3, "patent family members must stay separate"


# ── Bulk import ────────────────────────────────────────────────────────


def test_bulk_import_creates_and_dedupes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)

    body = {
        "source_label": "test_corpus.xlsx",
        "records": [
            {"title": "A", "publication_number": "P1"},
            {"title": "B", "publication_number": "P2"},
            {"title": "C", "publication_number": "P3"},
            # Duplicate of P1 with extra data
            {"title": "A updated", "publication_number": "P1",
             "key_claims_summary": "Independent claim..."},
        ],
    }
    r = client.post(
        f"/api/company/projects/{project_id}/patents/bulk-import",
        json=body,
    )
    assert r.status_code == 200, r.text
    counts = r.json()
    assert counts["created"] == 3, f"expected 3 created, got {counts}"
    assert counts["updated"] == 1, f"expected 1 updated, got {counts}"
    assert counts["total"] == 4

    # Re-import the same body — all 4 should be merge-updates, no new records
    r2 = client.post(
        f"/api/company/projects/{project_id}/patents/bulk-import",
        json=body,
    )
    counts2 = r2.json()
    # On re-import, P1's extra data is already there → skipped (no actual change),
    # but P2/P3/P1-original all "update" because updated_at changes the row.
    # The exact split between updated and skipped depends on payload normalization;
    # the contract is just that NO new records get created.
    listing = client.get(f"/api/company/projects/{project_id}/patents")
    assert listing.json()["count"] == 3, "no new records on re-import"


def test_bulk_import_unknown_project_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.post(
        "/api/company/projects/nope/patents/bulk-import",
        json={"records": []},
    )
    assert r.status_code == 404


# ── Patent risk ────────────────────────────────────────────────────────


def test_create_patent_risk_forces_attorney_review_for_high(
    tmp_path: Path,
) -> None:
    """High and critical risks MUST have requires_patent_attorney_review=True
    even if the request body explicitly sets it to False. This is a non-
    negotiable safety contract from the patent-risk-register skill."""
    client = _client(tmp_path)
    project_id = _create_project(client)

    # Try to bypass the attorney-review flag for a high risk
    r = client.post(
        f"/api/company/projects/{project_id}/patents/risks",
        json={
            "title": "Potential overlap with CN113711690B",
            "related_product_feature": "温度调控",
            "risk_level": "high",
            "reason": "Independent claim 1 reads on multi-zone temperature control",
            "suggested_design_around": "Use single-zone heating instead",
            "requires_patent_attorney_review": False,  # try to opt out
        },
    )
    assert r.status_code == 200, r.text
    risk = r.json()
    assert risk["risk_level"] == "high"
    assert risk["requires_patent_attorney_review"] is True, (
        "high+ risks MUST force attorney review"
    )


def test_create_patent_risk_critical_also_forced(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)
    r = client.post(
        f"/api/company/projects/{project_id}/patents/risks",
        json={
            "title": "Critical overlap",
            "related_product_feature": "床笠 PPG",
            "risk_level": "critical",
            "reason": "Reads on 80% of feature elements",
            "requires_patent_attorney_review": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["requires_patent_attorney_review"] is True


def test_create_patent_risk_low_keeps_user_choice(tmp_path: Path) -> None:
    """Low/medium risks honor the user's attorney-review choice."""
    client = _client(tmp_path)
    project_id = _create_project(client)
    r = client.post(
        f"/api/company/projects/{project_id}/patents/risks",
        json={
            "title": "Minor overlap",
            "related_product_feature": "App UI",
            "risk_level": "low",
            "reason": "Some keyword overlap; expired in target market",
            "requires_patent_attorney_review": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["requires_patent_attorney_review"] is False


def test_list_patent_risks_sorted_by_severity(tmp_path: Path) -> None:
    """List endpoint orders risks critical > high > medium > low."""
    client = _client(tmp_path)
    project_id = _create_project(client)

    for level in ["medium", "critical", "low", "high"]:
        client.post(
            f"/api/company/projects/{project_id}/patents/risks",
            json={
                "title": f"{level} risk",
                "related_product_feature": "feat",
                "risk_level": level,
                "reason": "...",
            },
        )

    r = client.get(f"/api/company/projects/{project_id}/patents/risks")
    levels = [risk["risk_level"] for risk in r.json()["risks"]]
    assert levels == ["critical", "high", "medium", "low"]


def test_update_patent_risk_relevels_attorney_review(tmp_path: Path) -> None:
    """Updating a risk's level to high re-forces the attorney-review flag."""
    client = _client(tmp_path)
    project_id = _create_project(client)
    r = client.post(
        f"/api/company/projects/{project_id}/patents/risks",
        json={
            "title": "x",
            "related_product_feature": "f",
            "risk_level": "low",
            "reason": "minor",
            "requires_patent_attorney_review": False,
        },
    )
    risk_id = r.json()["id"]
    assert r.json()["requires_patent_attorney_review"] is False

    r2 = client.patch(
        f"/api/company/patents/risks/{risk_id}",
        json={"risk_level": "high"},
    )
    assert r2.status_code == 200
    assert r2.json()["risk_level"] == "high"
    assert r2.json()["requires_patent_attorney_review"] is True


# ── Market template discovery ──────────────────────────────────────────


def test_patent_fto_screener_template_in_market() -> None:
    """The hardware-startup/patent-fto-screener template must appear in
    the agent market via _load_hardware_startup_templates."""
    from runtime.sensing.gateway.agent_world_router import (
        _load_hardware_startup_templates,
    )

    templates = _load_hardware_startup_templates()
    assert len(templates) >= 1
    ids = {t["id"] for t in templates}
    assert "hardware_patent_fto_screener" in ids

    template = next(t for t in templates if t["id"] == "hardware_patent_fto_screener")
    assert template["category"] == "specialist"
    assert "hardware-startup" in template["tags"]
    # The 5 skill markdown packs must be discovered
    assert set(template["private_skills"]) == {
        "patent-import-xlsx", "patent-search", "claim-extract",
        "fto-compare", "patent-risk-register",
    }
