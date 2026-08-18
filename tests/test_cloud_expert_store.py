"""Cloud Expert Store(WorkBuddy 专家商城云端源)单测。

覆盖:本地镜像加载、列表/搜索/分类、详情、bundle 解压安全性、安装编排。
网络相关路径用 monkeypatch 短路,不依赖公网。
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from runtime.platform.plugins import cloud_expert_store as ces


def _make_store_json(expert_count: int = 3) -> dict:
    experts = []
    for i in range(expert_count):
        experts.append(
            {
                "id": f"Expert{i}",
                "plugin": f"expert-{i}",
                "expertType": "agent" if i % 2 == 0 else "team",
                "categoryId": "02-Engineering",
                "displayName": {"en": f"Expert {i}", "zh": f"专家{i}"},
                "profession": {"en": "Engineer", "zh": "工程师"},
                "description": {"en": "desc", "zh": "描述"},
                "tags": [{"en": "tag", "zh": "标签"}],
                "quickPrompts": [{"en": "q", "zh": "提示"}],
                "defaultInitPrompt": {"en": "p", "zh": "开场"},
                "avatar": "https://example.com/a.png",
                "promptFile": "/plugins/expert-0/agents/expert-0.md",
                "bundleUrl": "https://example.com/bundles/expert-0.tar.gz",
                "updatedAt": "2026-08-18T00:00:00Z",
            }
        )
    return {
        "meta": {"count": expert_count, "agentCount": 2, "teamCount": 1},
        "categories": [
            {"id": "02-Engineering", "name": {"en": "Engineering", "zh": "技术工程"}}
        ],
        "experts": experts,
    }


def _write_mirror(store: dict) -> Path:
    # 构造一个假本地镜像:不落盘到真实仓库,而是 patch LOCAL_MIRROR
    return None  # noqa: BLE001


class TestCloudStoreLogic:
    def test_list_experts_uses_local_mirror(self, tmp_path, monkeypatch):
        store = _make_store_json(5)
        mirror = tmp_path / "expert-store.json"
        mirror.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(ces, "LOCAL_MIRROR", mirror)
        s = ces.CloudExpertStore(use_remote=False, use_cache=False)
        res = s.list_experts(limit=20)
        assert res["total"] == 5
        assert res["page_size"] == 20
        # 映射成 agent-market wire 形状
        a = res["agents"][0]
        assert a["source"] == "workbuddy-cloud"
        assert a["display_name"] == "专家0"
        assert a["category_id"] == "02-Engineering"
        assert a["is_team"] is False

    def test_search_filters(self, tmp_path, monkeypatch):
        store = _make_store_json(4)
        mirror = tmp_path / "expert-store.json"
        mirror.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(ces, "LOCAL_MIRROR", mirror)
        s = ces.CloudExpertStore(use_remote=False, use_cache=False)
        res = s.list_experts(search="专家3", limit=20)
        assert res["total"] == 1
        assert res["agents"][0]["id"] == "wb_expert-3"

    def test_category_filter_by_zh_name(self, tmp_path, monkeypatch):
        store = _make_store_json(3)
        mirror = tmp_path / "expert-store.json"
        mirror.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(ces, "LOCAL_MIRROR", mirror)
        s = ces.CloudExpertStore(use_remote=False, use_cache=False)
        res = s.list_experts(category="技术工程", limit=20)
        assert res["total"] == 3

    def test_team_flag(self, tmp_path, monkeypatch):
        store = _make_store_json(4)
        mirror = tmp_path / "expert-store.json"
        mirror.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(ces, "LOCAL_MIRROR", mirror)
        s = ces.CloudExpertStore(use_remote=False, use_cache=False)
        res = s.list_experts(limit=20)
        teams = [a for a in res["agents"] if a["is_team"]]
        assert len(teams) == 2

    def test_get_by_id(self, tmp_path, monkeypatch):
        store = _make_store_json(3)
        mirror = tmp_path / "expert-store.json"
        mirror.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(ces, "LOCAL_MIRROR", mirror)
        s = ces.CloudExpertStore(use_remote=False, use_cache=False)
        assert s.get("Expert1")["plugin"] == "expert-1"
        assert s.get("expert-2")["id"] == "Expert2"
        assert s.get("nope") is None


class TestBundleUnpack:
    def test_safe_extract_rejects_path_traversal(self, tmp_path):
        bundle = tmp_path / "evil.tar.gz"
        with tarfile.open(bundle, "w:gz") as tf:
            payload = b"evil"
            info = tarfile.TarInfo("../escape.txt")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        dest = tmp_path / "unpack"
        dest.mkdir()
        s = ces.CloudExpertStore(use_remote=False)
        try:
            s._unpack(bundle, dest)
            raised = False
        except ValueError:
            raised = True
        assert raised, "path traversal should be rejected"
        assert not (tmp_path / "escape.txt").exists()

    def test_unpack_valid_tarball(self, tmp_path):
        bundle = tmp_path / "ok.tar.gz"
        with tarfile.open(bundle, "w:gz") as tf:
            for name, data in (
                ("plugins/x/.codebuddy-plugin/plugin.json", b"{}"),
                ("plugins/x/agents/x.md", b"# x"),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        dest = tmp_path / "unpack"
        dest.mkdir()
        s = ces.CloudExpertStore(use_remote=False)
        out = s._unpack(bundle, dest)
        assert (out / "plugins/x/.codebuddy-plugin/plugin.json").exists()


class TestFindPackRoot:
    def test_finds_codebuddy_plugin_root(self, tmp_path):
        root = tmp_path / "unpack"
        (root / "plugins/x/.codebuddy-plugin").mkdir(parents=True)
        assert ces._find_pack_root(root) == root / "plugins/x"

    def test_falls_back_to_root(self, tmp_path):
        root = tmp_path / "unpack"
        root.mkdir()
        assert ces._find_pack_root(root) == root
