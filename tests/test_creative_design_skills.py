from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "runtime/execution/all_skills"

EXPECTED = {
    "creative-3d-animation",
    "creative-anime-pv",
    "creative-brand-film",
    "creative-broll-planner",
    "creative-character-performance",
    "creative-director-stage",
    "creative-dynamic-poster",
    "creative-education-video",
    "creative-fpv-video",
    "creative-koc-video",
    "creative-localization-dubbing",
    "creative-music-video",
    "creative-paper-collage",
    "creative-product-ad",
    "creative-title-sequence",
    "creative-ui-motion",
    "creative-video-deconstruct",
    "creative-video-editor",
    "creative-visual-direction",
}


def _frontmatter(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    _, raw, _ = source.split("---", 2)
    return yaml.safe_load(raw)


def test_design_skill_pack_is_complete_original_and_catalogued() -> None:
    found = {path.parent.name for path in SKILLS.glob("creative-*/SKILL.md")}
    assert found == EXPECTED

    catalog = (ROOT / "frontend/src/app/workspace/design/design-catalog.ts").read_text(
        encoding="utf-8"
    )
    for skill_id in sorted(EXPECTED):
        metadata = _frontmatter(SKILLS / skill_id / "SKILL.md")
        assert metadata["name"] == skill_id
        assert metadata["license"] == "Apache-2.0"
        assert metadata["metadata"]["origin"] == "octopus-original"
        assert f'id: "{skill_id}"' in catalog
