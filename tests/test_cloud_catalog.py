"""CloudCatalog(云商城插件/技能目录 + 内容包安装)单测。

覆盖:目录解析、内容包解包安全、install_skill 落地/幂等、install_plugin 落地 +
捆绑技能复制。内容包用内存 tar.gz 构造,不依赖公网。
"""
from __future__ import annotations

import io
import json
import tarfile

from runtime.platform.plugins.cloud_catalog import CloudCatalog


def _make_skill_pack() -> bytes:
    """构造 octopus-skills.tar.gz:skills/api-doc-gen/{SKILL.md, scripts/gen.py}。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in [
            ("skills/api-doc-gen/SKILL.md", b"# API Doc Gen\n"),
            ("skills/api-doc-gen/meta.json", b'{"name":"api-doc-gen"}\n'),
            ("skills/api-doc-gen/scripts/gen.py", b"print('hi')\n"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_plugin_pack() -> bytes:
    """构造 octopus-plugins.tar.gz:plugins/codex/figma + plugins/connector/wecom。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        entries = [
            ("plugins/codex/figma/.codex-plugin/plugin.json", b'{"name":"figma"}\n'),
            ("plugins/codex/figma/skills/figma-use/SKILL.md", b"# Figma Use\n"),
            ("plugins/connector/wecom/cli.json", b'{"command":"wecom"}\n'),
            ("plugins/connector/wecom/skills/wecomcli-calendar/SKILL.md", b"# WeCom Calendar\n"),
        ]
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class TestExtractMember:
    def test_extracts_under_prefix(self, tmp_path):
        pack = tmp_path / "pack.tar.gz"
        pack.write_bytes(_make_skill_pack())
        cat = CloudCatalog("skills", use_remote=False, use_cache=False)
        out = cat._extract_member(pack, "skills", tmp_path / "x", "api-doc-gen")
        assert out.name == "api-doc-gen"
        assert (out / "SKILL.md").exists()
        assert (out / "scripts" / "gen.py").exists()

    def test_missing_member_returns_none(self, tmp_path):
        pack = tmp_path / "pack.tar.gz"
        pack.write_bytes(_make_skill_pack())
        cat = CloudCatalog("skills", use_remote=False, use_cache=False)
        assert cat._extract_member(pack, "skills", tmp_path / "x", "nope") is None

    def test_rejects_path_traversal(self, tmp_path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            evil = "skills/evil/../../../outside.txt"
            info = tarfile.TarInfo(evil)
            data = b"boom"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        pack = tmp_path / "evil.tar.gz"
        pack.write_bytes(buf.getvalue())
        cat = CloudCatalog("skills", use_remote=False, use_cache=False)
        try:
            cat._extract_member(pack, "skills", tmp_path / "x", "evil")
        except ValueError:
            return
        raise AssertionError("path traversal not rejected")


class TestInstallSkill:
    def test_installs_to_target_and_is_idempotent(self, tmp_path, monkeypatch):
        pack = tmp_path / "pack.tar.gz"
        pack.write_bytes(_make_skill_pack())
        skills_root = tmp_path / "skills"
        cat = CloudCatalog("skills", use_remote=False, use_cache=False)
        monkeypatch.setattr(cat, "_archive_path", lambda: pack)
        res = cat.install_skill("api-doc-gen", skills_dir=skills_root)
        assert res["installed"] is True
        assert (skills_root / "api-doc-gen" / "SKILL.md").exists()
        # 幂等:二次安装返回 already_exists
        res2 = cat.install_skill("api-doc-gen", skills_dir=skills_root)
        assert res2["already_exists"] is True


class TestInstalledPlugins:
    def test_merges_cloud_dir_codex_cache_and_connector_state(self, tmp_path, monkeypatch):
        cat = CloudCatalog("plugins", use_remote=False, use_cache=False)
        # 云安装落点
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.PLUGIN_INSTALL_ROOT",
            tmp_path / "plugins",
        )
        (tmp_path / "plugins" / "connector" / "wecom").mkdir(parents=True)
        (tmp_path / "plugins" / "codex" / "figma").mkdir(parents=True)
        # codex 格式插件(octopus 布局 <plugin>/.codex-plugin/plugin.json)
        cache = tmp_path / "codex-cache" / "sites"
        (cache / ".codex-plugin").mkdir(parents=True)
        (cache / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"sites"}', encoding="utf-8"
        )
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.CODEX_CACHE_ROOT",
            tmp_path / "codex-cache",
        )
        # 连接器状态
        st = tmp_path / "connectors" / "state.json"
        st.parent.mkdir(parents=True)
        st.write_text(
            json.dumps({"github": {"id": "github", "installed": True},
                        "wecom": {"id": "wecom", "installed": False}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.CONNECTOR_STATE_FILE",
            st,
        )
        got = cat.installed_plugins()
        assert "wecom" in got          # 云安装落点
        assert "figma" in got          # 云安装落点(codex)
        assert "sites" in got          # codex 缓存
        assert "github" in got         # 连接器状态 installed=true
        assert "tencent-docs" not in got  # 未安装的连接器不标
        assert got == sorted(got)

class TestInstallPlugin:
    def test_connector_lands_and_copies_skills(self, tmp_path, monkeypatch):
        pack = tmp_path / "pack.tar.gz"
        pack.write_bytes(_make_plugin_pack())
        cat = CloudCatalog("plugins", use_remote=False, use_cache=False)
        monkeypatch.setattr(cat, "_archive_path", lambda: pack)
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.PLUGIN_INSTALL_ROOT",
            tmp_path / "plugins",
        )
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.CONNECTOR_STATE_FILE",
            tmp_path / "connectors" / "state.json",
        )
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.SKILLS_ROOT",
            tmp_path / "skills",
        )
        res = cat.install_plugin("wecom", plugin_kind="connector")
        assert res["installed"] is True
        plugin_dir = tmp_path / "plugins" / "connector" / "wecom"
        assert (plugin_dir / "cli.json").exists()
        # 捆绑技能复制到 ~/.octopus/skills/<id>__<skill>
        copied = res["copied_skills"]
        assert copied == ["wecom__wecomcli-calendar"]
        assert (tmp_path / "skills" / "wecom__wecomcli-calendar" / "SKILL.md").exists()

    def test_codex_plugin_lands(self, tmp_path, monkeypatch):
        pack = tmp_path / "pack.tar.gz"
        pack.write_bytes(_make_plugin_pack())
        cat = CloudCatalog("plugins", use_remote=False, use_cache=False)
        monkeypatch.setattr(cat, "_archive_path", lambda: pack)
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.PLUGIN_INSTALL_ROOT",
            tmp_path / "plugins",
        )
        monkeypatch.setattr(
            "runtime.platform.plugins.cloud_catalog.CloudCatalog.SKILLS_ROOT",
            tmp_path / "skills",
        )
        res = cat.install_plugin("figma", plugin_kind="codex")
        assert (tmp_path / "plugins" / "codex" / "figma" / ".codex-plugin" / "plugin.json").exists()
        assert res["kind"] == "codex"

class TestSyncCodexCache:
    def test_migrates_legacy_cache_to_octopus_layout(self, tmp_path):
        from runtime.platform.plugins import codex_discovery

        legacy = tmp_path / "legacy-cache"
        # 旧布局:<family>/<plugin>/<version>/.codex-plugin/plugin.json(同插件多版本)
        v10 = legacy / "openai" / "figma" / "1.0.0"
        (v10 / ".codex-plugin").mkdir(parents=True)
        (v10 / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"figma","version":"1.0.0"}', encoding="utf-8"
        )
        v11 = legacy / "openai" / "figma" / "1.1.0"
        (v11 / ".codex-plugin").mkdir(parents=True)
        (v11 / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"figma","version":"1.1.0"}', encoding="utf-8"
        )
        dest = tmp_path / "octopus-codex"
        n = codex_discovery.sync_codex_cache_to_octopus(source=legacy, dest=dest)
        assert n == 1
        # 只保留最新版本,且为 octopus 布局 <plugin>/
        assert (dest / "figma" / ".codex-plugin" / "plugin.json").exists()
        meta = json.loads((dest / "figma" / ".codex-plugin" / "plugin.json").read_text("utf-8"))
        assert meta["version"] == "1.1.0"
        # 幂等:重复同步不再复制
        n2 = codex_discovery.sync_codex_cache_to_octopus(source=legacy, dest=dest)
        assert n2 == 0
