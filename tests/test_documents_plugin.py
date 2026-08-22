"""Tests for the bundled ``documents`` plugin (独立自研 docx 处理)。

覆盖:
  1. 插件可发现、可加载(bundled)
  2. 注册 4 个技能进 SkillRegistry
  3. create_docx -> extract_text / to_markdown / docx_info 的真实本地文件流
  4. create_docx 写操作安全门:文件已存在且未传 overwrite 时拒绝
  5. 缺失文件返回干净错误
"""

from __future__ import annotations

from unittest.mock import MagicMock

from runtime.platform.plugins.bundled import documents as documents_module
from runtime.platform.plugins.bundled.documents import DocumentsPlugin
from runtime.platform.plugins.plugin_base import ModuleContext
from runtime.platform.plugins.plugin_hub import PluginHub

PLUGIN_ID = "documents"


def test_bundled_documents_is_discoverable_and_loadable() -> None:
    hub = PluginHub()
    matches = [item for item in hub.discover() if item["id"] == PLUGIN_ID]

    assert len(matches) == 1
    assert matches[0]["bundled"] is True
    assert hub.load(PLUGIN_ID) is not None


def test_documents_registers_four_skills() -> None:
    plugin = DocumentsPlugin()
    registered: list[str] = []
    plugin.ctx = ModuleContext(
        plugin_name=PLUGIN_ID,
        plugin_dir="",
        manifest=None,
        skill_registry=MagicMock(register=lambda s, verify_tests=False: registered.append(s.name)),
    )
    plugin.register_skills()

    assert set(registered) == {
        "documents.create_docx",
        "documents.extract_text",
        "documents.to_markdown",
        "documents.docx_info",
    }


def _sample_sections() -> list[dict]:
    return [
        {"type": "heading", "text": "季度总结", "level": 1},
        {"type": "paragraph", "text": "本季度整体进展顺利。"},
        {"type": "list", "items": ["完成 A", "完成 B"], "ordered": False},
        {
            "type": "table",
            "headers": ["指标", "数值"],
            "rows": [["收入", "100"], ["利润", "20"]],
        },
    ]


def test_create_then_extract_roundtrip(tmp_path) -> None:
    plugin = DocumentsPlugin()
    out = tmp_path / "report.docx"
    created = plugin._create_docx(path=str(out), title="季度报告", sections=_sample_sections())
    assert created["ok"], created
    assert out.exists()
    assert created["num_headings"] == 1
    assert created["num_tables"] == 1

    extracted = plugin._extract_text(path=str(out))
    assert extracted["ok"], extracted
    assert extracted["num_paragraphs"] >= 3
    assert extracted["num_tables"] == 1
    # 标题层级保留
    levels = [p["level"] for p in extracted["paragraphs"] if p["level"]]
    assert levels == [1]
    texts = [p["text"] for p in extracted["paragraphs"]]
    assert "季度总结" in texts and "完成 A" in texts


def test_create_docx_requires_overwrite_for_existing_file(tmp_path) -> None:
    plugin = DocumentsPlugin()
    out = tmp_path / "exists.docx"
    first = plugin._create_docx(path=str(out), sections=[{"type": "paragraph", "text": "v1"}])
    assert first["ok"]

    # 不传 overwrite -> 拒绝
    rejected = plugin._create_docx(path=str(out), sections=[{"type": "paragraph", "text": "v2"}])
    assert rejected["ok"] is False
    assert "overwrite" in rejected["error"]

    # 传 overwrite=true -> 覆盖成功
    overwritten = plugin._create_docx(
        path=str(out), sections=[{"type": "paragraph", "text": "v2"}], overwrite=True
    )
    assert overwritten["ok"]
    extracted = plugin._extract_text(path=str(out))
    assert any(p["text"] == "v2" for p in extracted["paragraphs"])


def test_to_markdown_preserves_structure(tmp_path) -> None:
    plugin = DocumentsPlugin()
    out = tmp_path / "doc.md.docx"
    assert plugin._create_docx(path=str(out), sections=_sample_sections())["ok"]

    converted = plugin._to_markdown(path=str(out))
    assert converted["ok"], converted
    md = converted["markdown"]
    assert "# 季度总结" in md
    assert "- 完成 A" in md
    assert "| 指标" in md and "|---|---|" in md


def test_docx_info_counts(tmp_path) -> None:
    plugin = DocumentsPlugin()
    out = tmp_path / "info.docx"
    assert plugin._create_docx(path=str(out), sections=_sample_sections())["ok"]

    info = plugin._docx_info(path=str(out))
    assert info["ok"], info
    assert info["num_tables"] == 1
    assert info["num_headings"] == 1
    assert info["size_bytes"] > 0
    assert info["tables"][0]["rows"] == 3  # 表头 + 2 行


def test_missing_file_returns_clean_error(tmp_path) -> None:
    plugin = DocumentsPlugin()
    missing = tmp_path / "nope.docx"
    assert plugin._extract_text(path=str(missing))["ok"] is False
    assert plugin._to_markdown(path=str(missing))["ok"] is False
    assert plugin._docx_info(path=str(missing))["ok"] is False


def test_non_docx_path_rejected(tmp_path) -> None:
    plugin = DocumentsPlugin()
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    out = plugin._extract_text(path=str(txt))
    assert out["ok"] is False
    assert ".docx" in out["error"]


def test_python_docx_is_an_optional_runtime_capability(monkeypatch) -> None:
    """The core wheel remains usable when the optional document library is absent."""

    monkeypatch.setattr(documents_module, "_DOCX_OK", False)

    out = DocumentsPlugin()._create_docx(path="report.docx", sections=[])

    assert out["ok"] is False
    assert "python-docx" in out["error"]
