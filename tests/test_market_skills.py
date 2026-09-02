"""Implementation note."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import pytest

from runtime.execution.suckers import SkillRegistry
from runtime.execution.suckers.market_skills import (
    _PROMPT_REFRESH_MAX_DEADLINE_S,
    _parse_frontmatter,
    _prompt_refresh_deadline,
    _sanitize_skill_name,
    load_single_market_skill,
    register_market_skills,
    register_prompt_market_skills,
)

# Implementation note.


class TestParseFrontmatter:
    def test_simple_key_value(self):
        text = "---\nname: demo\ndescription: hi\n---\nbody"
        meta, body = _parse_frontmatter(text)
        assert meta == {"name": "demo", "description": "hi"}
        assert body == "body"

    def test_no_frontmatter_returns_empty_meta(self):
        text = "just a body\nwith lines"
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == text.strip()

    def test_block_scalar_folded(self):
        text = "---\ndescription: >\n  this is a\n  folded description\n---\nhi"
        meta, _ = _parse_frontmatter(text)
        assert meta["description"] == "this is a folded description"

    def test_list_expanded(self):
        text = "---\ntags:\n  - one\n  - two\n---\nbody"
        meta, _ = _parse_frontmatter(text)
        assert meta["tags"] == ["one", "two"]

    def test_inline_list(self):
        text = "---\ntags: [a, b, c]\n---\nx"
        meta, _ = _parse_frontmatter(text)
        assert meta["tags"] == ["a", "b", "c"]

    def test_bools_coerced(self):
        text = "---\nenabled: false\nalways_apply: true\n---\nx"
        meta, _ = _parse_frontmatter(text)
        assert meta["enabled"] is False
        assert meta["always_apply"] is True


# ─── sanitize ────────────────────────────────────────────────


class TestSanitize:
    def test_keeps_ascii_alnum(self):
        assert _sanitize_skill_name("shopify-builder", "x") == "shopify-builder"
        assert _sanitize_skill_name("copy_writing_27", "x") == "copy_writing_27"

    def test_replaces_special(self):
        assert _sanitize_skill_name("weird space!", "x") == "weird_space_"

    def test_empty_uses_fallback(self):
        assert _sanitize_skill_name("", "fallback") == "fallback"
        assert _sanitize_skill_name("   ", "fb") == "fb"


# Implementation note.


class TestRegistration:
    def test_registers_basic_skill(self, tmp_path: Path):
        skill = tmp_path / "copywriter"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: copywriter\ndescription: write copy.\n---\n# Guide\n\nDo the thing.\n",
            encoding="utf-8",
        )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        assert count == 1
        assert r.has("copywriter")
        s = r.get("copywriter")
        assert s.trusted_source == "skill://all_skills/copywriter"
        assert "market" in s.affinity

    def test_handler_returns_instructions_and_resources(self, tmp_path: Path):
        skill = tmp_path / "pdf"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: PDF stuff.\n---\n# PDF Guide\n\nStep 1. Open.\n",
            encoding="utf-8",
        )
        (skill / "reference.md").write_text("extra docs", encoding="utf-8")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "helper.py").write_text("print(1)", encoding="utf-8")

        r = SkillRegistry()
        register_market_skills(r, all_skills_dir=tmp_path)
        payload = r.get("pdf").handler()
        assert payload["skill"] == "pdf"
        assert "PDF Guide" in payload["instructions"]
        res_paths = {x["path"] for x in payload["resources"]}
        assert "reference.md" in res_paths
        script_paths = {x["path"] for x in payload["scripts"]}
        assert "scripts/helper.py" in script_paths
        assert Path(payload["cwd"]) == skill.resolve()

    def test_frontmatter_enabled_false_skipped(self, tmp_path: Path):
        off = tmp_path / "disabled_one"
        off.mkdir()
        (off / "SKILL.md").write_text(
            "---\nname: disabled_one\ndescription: x\nenabled: false\n---\nbody",
            encoding="utf-8",
        )
        on = tmp_path / "enabled_one"
        on.mkdir()
        (on / "SKILL.md").write_text(
            "---\nname: enabled_one\ndescription: y\n---\nbody",
            encoding="utf-8",
        )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        assert count == 1
        assert r.has("enabled_one")
        assert not r.has("disabled_one")

    def test_skills_config_can_re_enable(self, tmp_path: Path):
        # frontmatter enabled omitted; config says enabled=true → load
        skill = tmp_path / "my-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: z\n---\nbody",
            encoding="utf-8",
        )
        cfg = {"99_my-skill": {"installedVersion": "0.0.1", "enabled": True}}
        (tmp_path / "skills_config.json").write_text(
            json.dumps(cfg),
            encoding="utf-8",
        )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        assert count == 1
        assert r.has("my-skill")

    def test_missing_name_falls_back_to_dirname(self, tmp_path: Path):
        # Implementation note.
        skill = tmp_path / "from-dir"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\ndescription: no name\n---\nbody",
            encoding="utf-8",
        )
        r = SkillRegistry()
        register_market_skills(r, all_skills_dir=tmp_path)
        assert r.has("from-dir")

    def test_duplicate_names_skipped(self, tmp_path: Path):
        # Implementation note.
        for sub in ("a", "b"):
            d = tmp_path / sub
            d.mkdir()
            (d / "SKILL.md").write_text(
                "---\nname: same\ndescription: x\n---\nbody",
                encoding="utf-8",
            )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        assert count == 1
        assert r.has("same")

    def test_body_truncated_at_limit(self, tmp_path: Path):
        skill = tmp_path / "huge"
        skill.mkdir()
        huge = "x" * (40 * 1024)  # 40 KB · over 32 KB cap
        (skill / "SKILL.md").write_text(
            f"---\nname: huge\ndescription: big.\n---\n{huge}",
            encoding="utf-8",
        )
        r = SkillRegistry()
        register_market_skills(r, all_skills_dir=tmp_path)
        payload = r.get("huge").handler()
        # Truncation marker appended · body within cap + marker length
        assert "[... truncated ...]" in payload["instructions"]
        assert len(payload["instructions"]) < 40 * 1024

    def test_missing_directory_returns_zero(self, tmp_path: Path):
        r = SkillRegistry()
        count = register_market_skills(
            r,
            all_skills_dir=tmp_path / "does_not_exist",
        )
        assert count == 0

    def test_production_chokepoint_rejects_direct_mutable_catalog_registration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        skill = tmp_path / "remote"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: remote\ndescription: mutable\n---\nMUTABLE REMOTE PROMPT",
            encoding="utf-8",
        )
        monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "shared")
        registry = SkillRegistry()

        assert register_market_skills(registry, all_skills_dir=tmp_path) == 0
        assert not load_single_market_skill(registry, "remote", all_skills_dir=tmp_path)
        assert not registry.has("remote")


class TestPromptCatalogDistribution:
    @staticmethod
    def _write_skill(root: Path, name: str, body: str = "body") -> None:
        skill = root / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: packaged fallback.\n---\n{body}\n",
            encoding="utf-8",
        )

    def test_empty_external_metadata_dir_uses_bundled_fallback(self, tmp_path: Path):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        external.mkdir(parents=True)
        (external / "skills_config.json").write_text("{}\n", encoding="utf-8")
        bundled = tmp_path / "bundled"
        self._write_skill(bundled, "offline-core")
        registry = SkillRegistry()

        count = register_prompt_market_skills(
            registry,
            resource_dir=resources,
            bundled_dir=bundled,
        )

        assert count == 1
        assert registry.has("offline-core")

    def test_bounded_refresh_errors_are_observable_after_bundled_registration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        external.mkdir(parents=True)
        (resources / "skills.lock.json").write_text(
            '{"skills": ["registry-only"]}\n',
            encoding="utf-8",
        )
        bundled = tmp_path / "bundled"
        self._write_skill(bundled, "offline-core")

        monkeypatch.setattr(
            "octopus_runtime.bootstrap_skills",
            lambda *_args, **_kwargs: ([], [], [("registry-only", "registry offline")]),
        )
        registry = SkillRegistry()

        with caplog.at_level(logging.WARNING):
            count = register_prompt_market_skills(
                registry,
                resource_dir=resources,
                bundled_dir=bundled,
            )

        assert count == 1
        assert registry.has("offline-core")
        assert "bounded refresh incomplete" in caplog.text
        assert "registry offline" in caplog.text

    def test_partial_external_catalog_is_supplemented_by_bundled_fallback(
        self,
        tmp_path: Path,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        bundled = tmp_path / "bundled"
        self._write_skill(external, "external-newer", "external body")
        self._write_skill(bundled, "external-newer", "bundled body")
        self._write_skill(bundled, "offline-core")
        registry = SkillRegistry()

        count = register_prompt_market_skills(
            registry,
            resource_dir=resources,
            bundled_dir=bundled,
        )

        assert count == 2
        assert registry.has("external-newer")
        assert registry.has("offline-core")
        assert registry.get("external-newer").handler()["instructions"] == "external body"

    def test_production_uses_only_build_bound_catalog_and_never_refreshes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        bundled = tmp_path / "bundled"
        self._write_skill(external, "shared-name", "mutable external body")
        self._write_skill(external, "external-only", "remote-only body")
        self._write_skill(bundled, "shared-name", "build-bound body")
        (resources / "skills.lock.json").write_text(
            '{"skills": ["external-only"]}\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "production")
        monkeypatch.setattr(
            "runtime.platform.process.paths.bundled_market_skills_dir",
            lambda: bundled,
        )

        def unexpected_bootstrap(*_args, **_kwargs):
            raise AssertionError("production startup must not contact the skill registry")

        monkeypatch.setattr("octopus_runtime.bootstrap_skills", unexpected_bootstrap)
        registry = SkillRegistry()

        with caplog.at_level(logging.WARNING):
            count = register_prompt_market_skills(
                registry,
                resource_dir=resources,
                bundled_dir=bundled,
            )

        assert count == 1
        assert registry.get("shared-name").handler()["instructions"] == "build-bound body"
        assert not registry.has("external-only")
        assert "ignoring mutable external prompt-skill catalog" in caplog.text

    def test_production_fails_closed_without_build_bound_catalog(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        self._write_skill(external, "external-only")
        monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "server")

        def unexpected_bootstrap(*_args, **_kwargs):
            raise AssertionError("production startup must not contact the skill registry")

        monkeypatch.setattr("octopus_runtime.bootstrap_skills", unexpected_bootstrap)

        with pytest.raises(RuntimeError, match="Remote and mutable external catalogs are disabled"):
            register_prompt_market_skills(
                SkillRegistry(),
                resource_dir=resources,
                bundled_dir=tmp_path / "missing-bundle",
            )

    def test_bounded_refresh_exception_is_observable_after_bundled_registration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        resources = tmp_path / "resources"
        (resources / "skills" / "public").mkdir(parents=True)
        (resources / "skills.lock.json").write_text(
            '{"skills": ["registry-only"]}\n',
            encoding="utf-8",
        )
        bundled = tmp_path / "bundled"
        self._write_skill(bundled, "offline-core")

        def fail_bootstrap(*_args, **_kwargs):
            raise OSError("registry socket unavailable")

        monkeypatch.setattr("octopus_runtime.bootstrap_skills", fail_bootstrap)
        registry = SkillRegistry()

        with caplog.at_level(logging.WARNING):
            count = register_prompt_market_skills(
                registry,
                resource_dir=resources,
                bundled_dir=bundled,
            )

        assert count == 1
        assert "bounded refresh failed" in caplog.text
        assert "registry socket unavailable" in caplog.text

    def test_packaged_catalog_passes_small_deadline_without_waiting_for_default_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        external.mkdir(parents=True)
        lockfile = resources / "skills.lock.json"
        lockfile.write_text('{"skills": ["registry-only"]}\n', encoding="utf-8")
        bundled = tmp_path / "bundled"
        self._write_skill(bundled, "offline-core")
        calls: list[dict[str, object]] = []

        def fake_bootstrap(*_args, **kwargs):
            calls.append(kwargs)
            return [], [], [("registry-only", "fake blackhole deadline")]

        monkeypatch.setattr("octopus_runtime.bootstrap_skills", fake_bootstrap)
        registry = SkillRegistry()

        count = register_prompt_market_skills(
            registry,
            resource_dir=resources,
            bundled_dir=bundled,
            refresh_deadline_s=0.05,
        )

        assert count == 1
        assert registry.has("offline-core")
        assert calls == [
            {
                "request_timeout_s": 0.05,
                "max_workers": 8,
                "total_timeout_s": 0.05,
            }
        ]

    def test_packaged_startup_returns_within_deadline_when_refresh_worker_blocks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        external.mkdir(parents=True)
        (resources / "skills.lock.json").write_text(
            '{"skills": ["registry-only"]}\n',
            encoding="utf-8",
        )
        bundled = tmp_path / "bundled"
        self._write_skill(bundled, "offline-core")
        started = threading.Event()
        release = threading.Event()

        def fake_sync_one(slug, *_args, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return slug, None, "__error__:released"

        monkeypatch.setattr("octopus_runtime.materialize._sync_one", fake_sync_one)
        registry = SkillRegistry()
        began = time.monotonic()
        try:
            count = register_prompt_market_skills(
                registry,
                resource_dir=resources,
                bundled_dir=bundled,
                refresh_deadline_s=0.05,
            )
            elapsed = time.monotonic() - began
        finally:
            release.set()

        assert started.is_set()
        assert elapsed < 0.5
        assert count == 1
        assert registry.has("offline-core")
        assert not registry.has("registry-only")

    def test_successful_refresh_is_only_visible_after_next_registry_construction(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        (resources / "skills.lock.json").parent.mkdir(parents=True)
        (resources / "skills.lock.json").write_text(
            '{"skills": ["registry-only"]}\n',
            encoding="utf-8",
        )
        bundled = tmp_path / "bundled"
        self._write_skill(bundled, "offline-core")

        def fake_bootstrap(*_args, **_kwargs):
            self._write_skill(external, "registry-only", "downloaded body")
            return ["registry-only"], [], []

        monkeypatch.setattr("octopus_runtime.bootstrap_skills", fake_bootstrap)
        first_registry = SkillRegistry()

        with caplog.at_level(logging.INFO):
            first_count = register_prompt_market_skills(
                first_registry,
                resource_dir=resources,
                bundled_dir=bundled,
            )

        assert first_count == 1
        assert first_registry.has("offline-core")
        assert not first_registry.has("registry-only")
        assert "apply after the next restart" in caplog.text

        second_registry = SkillRegistry()
        second_count = register_prompt_market_skills(
            second_registry,
            resource_dir=resources,
            bundled_dir=bundled,
            refresh_deadline_s=0,
        )
        assert second_count == 2
        assert second_registry.get("registry-only").handler()["instructions"] == "downloaded body"

    def test_without_bundled_catalog_preserves_synchronous_bootstrap(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        resources = tmp_path / "resources"
        external = resources / "skills" / "public"
        lockfile = resources / "skills.lock.json"
        lockfile.parent.mkdir(parents=True)
        lockfile.write_text('{"skills": ["registry-only"]}\n', encoding="utf-8")
        calls: list[dict[str, object]] = []

        def fake_bootstrap(*_args, **kwargs):
            calls.append(kwargs)
            self._write_skill(external, "registry-only")
            return ["registry-only"], [], []

        monkeypatch.setattr("octopus_runtime.bootstrap_skills", fake_bootstrap)
        registry = SkillRegistry()

        count = register_prompt_market_skills(
            registry,
            resource_dir=resources,
            bundled_dir=tmp_path / "missing-bundle",
        )

        assert count == 1
        assert registry.has("registry-only")
        assert calls == [{}]

    def test_refresh_deadline_is_operator_configurable_but_hard_capped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_PROMPT_SKILL_REFRESH_DEADLINE_S", "1.25")
        assert _prompt_refresh_deadline(None) == 1.25

        monkeypatch.setenv("OCTOPUS_PROMPT_SKILL_REFRESH_DEADLINE_S", "999")
        assert _prompt_refresh_deadline(None) == _PROMPT_REFRESH_MAX_DEADLINE_S

        assert _prompt_refresh_deadline(0) == 0

    def test_missing_external_and_bundled_catalogs_fail_fast(self, tmp_path: Path):
        resources = tmp_path / "resources"
        (resources / "skills" / "public").mkdir(parents=True)
        registry = SkillRegistry()

        with pytest.raises(RuntimeError, match="installation is incomplete"):
            register_prompt_market_skills(
                registry,
                resource_dir=resources,
                bundled_dir=tmp_path / "missing-bundle",
            )


class TestMainSkillRegistration:
    def test_uses_runtime_policy_capabilities_despite_legacy_package(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import runtime.platform.capabilities  # noqa: F401
        from runtime.execution import all_skills

        class _Capabilities:
            @staticmethod
            def disabled_skill_groups() -> set[str]:
                return {"web"}

        called: list[str] = []
        monkeypatch.setattr(
            "runtime.platform.runtime_policy.capabilities.load",
            lambda: _Capabilities(),
        )
        monkeypatch.setattr(
            all_skills,
            "_GROUP_REGISTRARS",
            {
                "builtin": lambda _registry: called.append("builtin"),
                "web": lambda _registry: called.append("web"),
                "market": lambda _registry: called.append("market"),
            },
        )
        monkeypatch.setattr(
            all_skills,
            "_register_prompt_market",
            lambda _registry: called.append("prompt"),
        )

        all_skills.register_all(SkillRegistry())

        assert called == ["builtin", "prompt", "market"]

    def test_production_agent_docs_ignore_mutable_external_override(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.execution.suckers.agent_doc_skills import register_agent_doc_skills

        external = tmp_path / "skills" / "public"
        TestPromptCatalogDistribution._write_skill(
            external,
            "frontend-design",
            "MUTABLE REMOTE OVERRIDE",
        )
        monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "commercial")
        monkeypatch.setattr(
            "runtime.platform.process.paths.resources_root",
            lambda: tmp_path,
        )
        registry = SkillRegistry()

        register_agent_doc_skills(registry)

        assert registry.has("frontend-design")
        assert (
            "MUTABLE REMOTE OVERRIDE"
            not in registry.get("frontend-design").handler()["instructions"]
        )


# Implementation note.
#
# Implementation note.
# Implementation note.


class TestLoadSingleMarketSkill:
    """Implementation note."""

    def test_loads_skill_with_enabled_false(self, tmp_path: Path):
        skill = tmp_path / "closed"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: closed\ndescription: off by default.\nenabled: false\n---\nbody",
            encoding="utf-8",
        )
        r = SkillRegistry()
        # Implementation note.
        register_market_skills(r, all_skills_dir=tmp_path)
        assert not r.has("closed")
        # Implementation note.
        ok = load_single_market_skill(r, "closed", all_skills_dir=tmp_path)
        assert ok
        assert r.has("closed")

    def test_returns_true_when_already_registered(self, tmp_path: Path):
        skill = tmp_path / "on"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: on\ndescription: x\n---\nbody",
            encoding="utf-8",
        )
        r = SkillRegistry()
        register_market_skills(r, all_skills_dir=tmp_path)
        # Implementation note.
        assert load_single_market_skill(r, "on", all_skills_dir=tmp_path)

    def test_returns_false_for_missing_dir(self, tmp_path: Path):
        r = SkillRegistry()
        assert not load_single_market_skill(
            r,
            "does_not_exist",
            all_skills_dir=tmp_path,
        )

    def test_returns_false_when_all_skills_dir_missing(self, tmp_path: Path):
        r = SkillRegistry()
        assert not load_single_market_skill(
            r,
            "x",
            all_skills_dir=tmp_path / "nope",
        )

    def test_respects_frontmatter_when_opted_in(self, tmp_path: Path):
        skill = tmp_path / "off"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: off\ndescription: x\nenabled: false\n---\nbody",
            encoding="utf-8",
        )
        r = SkillRegistry()
        ok = load_single_market_skill(
            r,
            "off",
            all_skills_dir=tmp_path,
            ignore_frontmatter_enabled=False,
        )
        assert not ok
        assert not r.has("off")


class TestRealAllSkillsDirSmoke:
    def test_registers_some_real_skills(self):
        r = SkillRegistry()
        count = register_market_skills(r)
        # Implementation note.
        assert count >= 3, f"expected >= 3 market skills, got {count}"
        # Implementation note.
        all_names = set(r.all_names())
        # Derive the expectation from the catalog itself so this smoke check
        # doesn't go stale when the all_skills/ set is reorganized. (The old
        # hardcoded {xlsx, create-website, image-prompt-guide} live in
        # skills/public/, which register_market_skills does NOT read — it reads
        # runtime/execution/all_skills/. Most skills register under their
        # directory name, so the registered names must overlap the actual
        # all_skills/ subdirectories.)
        import runtime.execution.all_skills as _all_skills_pkg

        all_skills_dir = Path(_all_skills_pkg.__file__).resolve().parent
        dir_names = {p.parent.name for p in all_skills_dir.glob("*/SKILL.md")}
        hit = all_names & dir_names
        assert hit, (
            f"no registered skill matches an all_skills/ dir; "
            f"registry={sorted(all_names)[:10]} dirs={sorted(dir_names)[:10]}"
        )


class TestAliases:
    """``aliases:`` frontmatter field lets one physical SKILL.md serve
    multiple trigger names. Pins the contract that motivated the
    deduplication of EN/CN twin skills (see project_known_defects.md
    P3 cluster)."""

    def test_inline_alias_list_registers_canonical_plus_aliases(
        self,
        tmp_path: Path,
    ):
        skill = tmp_path / "valuation"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: valuation\n"
            "description: Run a DCF.\n"
            "aliases: [dcf-model, cashflow-valuation]\n"
            "---\n"
            "# DCF\n",
            encoding="utf-8",
        )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        assert count == 3
        assert r.has("valuation")
        assert r.has("dcf-model")
        assert r.has("cashflow-valuation")
        # Aliases share handler bodies — every name returns the same
        # instructions so prompts keying on either name look identical.
        assert (
            r.get("valuation").handler()["instructions"]
            == (r.get("dcf-model").handler()["instructions"])
        )
        # Aliases are flagged as such via trusted_source so dedupers
        # / metrics can tell aliases from canonicals.
        assert r.get("valuation").trusted_source.endswith("/valuation")
        assert "#alias" in r.get("dcf-model").trusted_source

    def test_block_style_alias_list(self, tmp_path: Path):
        skill = tmp_path / "primary"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: primary\n"
            "description: x\n"
            "aliases:\n"
            "  - secondary\n"
            "  - tertiary\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        assert count == 3
        assert r.has("primary")
        assert r.has("secondary")
        assert r.has("tertiary")

    def test_alias_collision_with_existing_skill_is_skipped(
        self,
        tmp_path: Path,
    ):
        # Pre-register a skill with the alias name; the alias should
        # back off rather than raising.
        first = tmp_path / "first"
        first.mkdir()
        (first / "SKILL.md").write_text(
            "---\nname: first\ndescription: f.\n---\nbody\n",
            encoding="utf-8",
        )
        second = tmp_path / "second"
        second.mkdir()
        (second / "SKILL.md").write_text(
            "---\nname: second\ndescription: s.\naliases: [first]\n---\nbody\n",
            encoding="utf-8",
        )
        r = SkillRegistry()
        count = register_market_skills(r, all_skills_dir=tmp_path)
        # ``first`` registers normally, ``second`` registers, alias
        # ``first`` collides and is skipped → 2 not 3.
        assert count == 2
        assert r.has("first")
        assert r.has("second")
        # Original ``first`` handler wins; alias didn't overwrite.
        assert "f" in r.get("first").description.lower()
