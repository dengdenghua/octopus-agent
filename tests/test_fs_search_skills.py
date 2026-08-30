"""Implementation note."""

from __future__ import annotations

from pathlib import Path

from runtime.execution.suckers import SkillRegistry
from runtime.execution.suckers.fs_search_skills import (
    _glob_files,
    _grep_text,
    _read_file_range,
    _tree,
    register_fs_search_skills,
)

# ─── Registration ────────────────────────────────────────────


class TestRegistration:
    def test_register_installs_all_four(self):
        r = SkillRegistry()
        count = register_fs_search_skills(r)
        assert count == 4
        for name in ("glob_files", "grep_text", "tree", "read_file_range"):
            assert r.has(name), f"missing: {name}"

    def test_trusted_sources_are_skill_public(self):
        r = SkillRegistry()
        register_fs_search_skills(r)
        for name in ("glob_files", "grep_text", "tree", "read_file_range"):
            assert r.get(name).trusted_source.startswith("skill://public/")

    def test_unified_base_catalog_exposes_fs_search(self):
        from runtime.execution.all_skills import (
            BASE_SKILL_IDS,
            register_base,
            skill_group,
            skill_kind,
        )

        r = SkillRegistry()
        register_base(r)

        for name in ("glob_files", "grep_text", "tree", "read_file_range"):
            assert name in BASE_SKILL_IDS
            assert r.has(name), f"missing from base registry: {name}"
            assert skill_group(name) == "fs_search"
            assert skill_kind(name) == "system"


# ─── glob_files ──────────────────────────────────────────────


class TestGlobFiles:
    def test_matches_simple_pattern(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "readme.md").write_text("doc")
        r = _glob_files(pattern="*.py", root=str(tmp_path))
        names = {f["path"] for f in r["files"]}
        assert names == {"a.py", "b.py"}
        assert r["count"] == 2

    def test_recursive_double_star(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "deep").mkdir()
        (tmp_path / "src" / "deep" / "a.py").write_text("x")
        (tmp_path / "src" / "b.py").write_text("y")
        r = _glob_files(pattern="**/*.py", root=str(tmp_path))
        assert r["count"] == 2

    def test_missing_root_returns_error(self):
        r = _glob_files(pattern="*.py", root="/not/a/real/path/xyz")
        assert "error" in r

    def test_not_a_directory(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        r = _glob_files(pattern="*.py", root=str(f))
        assert "error" in r

    def test_excludes_hidden(self, tmp_path: Path):
        (tmp_path / "visible.py").write_text("x")
        (tmp_path / ".hidden.py").write_text("y")
        r = _glob_files(pattern="*.py", root=str(tmp_path))
        names = {f["path"] for f in r["files"]}
        assert "visible.py" in names
        assert ".hidden.py" not in names

    def test_max_results_caps_output(self, tmp_path: Path):
        for i in range(20):
            (tmp_path / f"f{i}.txt").write_text("x")
        r = _glob_files(pattern="*.txt", root=str(tmp_path), max_results=5)
        assert r["count"] == 5
        assert r["truncated"]

    def test_dirs_excluded_by_default(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "file.x").write_text("y")
        r = _glob_files(pattern="*", root=str(tmp_path))
        names = {f["path"] for f in r["files"]}
        assert "sub" not in names
        assert "file.x" in names


# ─── grep_text ───────────────────────────────────────────────


class TestGrepText:
    def test_finds_matches(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("hello\nworld\nhello again\n")
        r = _grep_text(pattern="hello", root=str(tmp_path), glob="*.txt")
        assert r["count"] == 2
        lines = {m["line"] for m in r["matches"]}
        assert lines == {1, 3}

    def test_ignore_case(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("Hello\nHELLO\nhello\n")
        r = _grep_text(
            pattern="hello",
            root=str(tmp_path),
            glob="*.txt",
            ignore_case=True,
        )
        assert r["count"] == 3

    def test_bad_regex_returns_error(self, tmp_path: Path):
        r = _grep_text(pattern="[unclosed", root=str(tmp_path))
        assert "error" in r
        assert "bad_regex" in r["error"]

    def test_missing_root_returns_error(self):
        r = _grep_text(pattern="x", root="/not/real/xyz")
        assert "error" in r

    def test_skips_non_utf8(self, tmp_path: Path):
        # Binary file · grep must skip silently, not crash
        (tmp_path / "b.bin").write_bytes(b"\x80\xff\x00notutf8")
        (tmp_path / "a.txt").write_text("hello\n")
        r = _grep_text(pattern="hello", root=str(tmp_path), glob="*")
        assert r["count"] == 1

    def test_max_matches_caps_output(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("x\n" * 50)
        r = _grep_text(
            pattern="x",
            root=str(tmp_path),
            glob="*.txt",
            max_matches=10,
        )
        assert r["count"] == 10
        assert r["truncated"]

    def test_truncates_long_line(self, tmp_path: Path):
        long = "x" * 2000
        (tmp_path / "a.txt").write_text(long + "\n")
        r = _grep_text(pattern="x", root=str(tmp_path), glob="*.txt", max_matches=1)
        assert len(r["matches"][0]["text"]) <= 500

    def test_default_search_does_not_stop_at_legacy_200_file_boundary(self, tmp_path: Path):
        for i in range(250):
            (tmp_path / f"source_{i:03}.txt").write_text("ordinary\n")
        (tmp_path / "source_249.txt").write_text("unique_large_project_target\n")

        r = _grep_text(
            pattern="unique_large_project_target",
            root=str(tmp_path),
            glob="*.txt",
        )

        assert r["count"] == 1
        assert r["matches"][0]["path"] == "source_249.txt"
        assert r["scanned_files"] == 250
        assert not r["truncated"]

    def test_generated_dependency_trees_do_not_consume_file_budget(self, tmp_path: Path):
        dependency_dir = tmp_path / "node_modules" / "package"
        dependency_dir.mkdir(parents=True)
        for i in range(20):
            (dependency_dir / f"dep_{i}.js").write_text("needle\n")
        (tmp_path / "app.ts").write_text("needle\n")

        r = _grep_text(
            pattern="needle",
            root=str(tmp_path),
            glob="**/*",
            max_files=1,
        )

        assert r["count"] == 1
        assert r["matches"][0]["path"] == "app.ts"
        assert r["scanned_files"] == 1

    def test_supports_brace_glob_for_mixed_typescript_sources(self, tmp_path: Path):
        (tmp_path / "component.tsx").write_text("export const target = true\n")
        (tmp_path / "helper.ts").write_text("export const target = false\n")
        (tmp_path / "ignored.js").write_text("const target = null\n")

        r = _grep_text(
            pattern="target",
            root=str(tmp_path),
            glob="**/*.{ts,tsx}",
        )

        assert {match["path"] for match in r["matches"]} == {"component.tsx", "helper.ts"}
        assert r["scanned_files"] == 2

    def test_accepts_provider_query_and_path_aliases(self, tmp_path: Path):
        source = tmp_path / "component.tsx"
        source.write_text("export function referenceTabForBlock() {}\n")

        r = _grep_text(query="referenceTabForBlock", path=str(source))

        assert r["count"] == 1
        assert r["matches"][0]["path"] == "component.tsx"

    def test_explicit_path_overrides_injected_workspace_root(self, tmp_path: Path):
        source = tmp_path / "component.tsx"
        source.write_text("export const exactTarget = true\n")
        (tmp_path / "unrelated.tsx").write_text("export const exactTarget = false\n")

        r = _grep_text(
            pattern="exactTarget",
            root=str(tmp_path),
            path=str(source),
        )

        assert r["root"] == str(source.resolve())
        assert r["scanned_files"] == 1
        assert r["count"] == 1
        assert r["matches"][0]["path"] == "component.tsx"


# ─── tree ────────────────────────────────────────────────────


class TestTree:
    def test_builds_nested_structure(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("y")
        r = _tree(root=str(tmp_path), max_depth=3)
        assert r["tree"]["is_dir"]
        names = [c["name"] for c in r["tree"]["children"]]
        assert "a.txt" in names
        assert "sub" in names
        sub = next(c for c in r["tree"]["children"] if c["name"] == "sub")
        sub_names = [c["name"] for c in sub["children"]]
        assert "b.txt" in sub_names

    def test_depth_limit(self, tmp_path: Path):
        # Build a chain 4 levels deep
        cur = tmp_path
        for i in range(4):
            cur = cur / f"d{i}"
            cur.mkdir()
        r = _tree(root=str(tmp_path), max_depth=2)
        # Walk down the children; at depth=2 we should see children_truncated
        node = r["tree"]
        depth = 0
        while node.get("children"):
            node = node["children"][0]
            depth += 1
            if not node.get("is_dir"):
                break
        assert depth <= 2 or "children_truncated" in node

    def test_hidden_excluded_by_default(self, tmp_path: Path):
        (tmp_path / "visible").mkdir()
        (tmp_path / ".hidden").mkdir()
        r = _tree(root=str(tmp_path), max_depth=2)
        names = [c["name"] for c in r["tree"]["children"]]
        assert "visible" in names
        assert ".hidden" not in names

    def test_missing_root_returns_error(self):
        r = _tree(root="/not/real/xyz")
        assert "error" in r


# ─── read_file_range ─────────────────────────────────────────


class TestReadFileRange:
    def test_reads_range(self, tmp_path: Path):
        lines = [f"line{i}" for i in range(1, 11)]
        p = tmp_path / "a.txt"
        p.write_text("\n".join(lines))
        r = _read_file_range(path=str(p), offset=3, limit=4)
        assert r["offset"] == 3
        assert r["returned_lines"] == 4
        assert r["content"] == "line3\nline4\nline5\nline6"

    def test_limit_beyond_file_caps(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_text("one\ntwo\nthree")
        r = _read_file_range(path=str(p), offset=1, limit=100)
        assert r["returned_lines"] == 3
        assert not r["truncated"]

    def test_truncated_flag(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_text("\n".join(str(i) for i in range(1, 11)))
        r = _read_file_range(path=str(p), offset=1, limit=5)
        assert r["truncated"]

    def test_missing_file_returns_error(self):
        r = _read_file_range(path="/no/such/file/zzz.txt")
        assert "error" in r

    def test_not_a_file(self, tmp_path: Path):
        r = _read_file_range(path=str(tmp_path))
        assert "error" in r

    def test_offset_clamped_to_1(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_text("a\nb\nc")
        r = _read_file_range(path=str(p), offset=0, limit=1)
        assert r["offset"] == 1
        assert r["content"] == "a"

    def test_crlf_lines_handled(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_bytes(b"1\r\n2\r\n3\r\n4\r\n")
        r = _read_file_range(path=str(p), offset=1, limit=3)
        assert r["total_lines"] == 4
        assert r["returned_lines"] == 3
        assert r["content"] == "1\n2\n3"
        assert r["truncated"]

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_text("")
        r = _read_file_range(path=str(p), offset=1, limit=5)
        assert r["total_lines"] == 0
        assert r["returned_lines"] == 0
        assert r["content"] == ""
        assert not r["truncated"]

    def test_offset_beyond_eof(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_text("x\ny")
        r = _read_file_range(path=str(p), offset=10, limit=5)
        assert r["returned_lines"] == 0
        assert r["end_line"] == 2
        assert r["total_lines"] == 2
        assert r["content"] == ""

    def test_no_trailing_newline(self, tmp_path: Path):
        p = tmp_path / "a.txt"
        p.write_text("line1\nline2")
        r = _read_file_range(path=str(p), offset=1, limit=10)
        assert r["total_lines"] == 2
        assert r["content"] == "line1\nline2"
        assert not r["truncated"]


# ─── Explicitly-named hidden dirs ────────────────────────────


class TestHiddenDirsAreVisibleWhenNamed:
    """A named dot-directory must not be filtered back out after matching.

    Regression: ``.github/workflows/*`` reported ``count: 0`` on a repo with
    seven workflow files, so callers concluded the directory did not exist.
    """

    @staticmethod
    def _repo(tmp_path: Path) -> Path:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "ci.yml").write_text("runs-on: ubuntu-latest\n")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("runs-on: noise\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.yml").write_text("runs-on: noise\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1\n")
        return tmp_path

    def test_named_hidden_dir_is_listed(self, tmp_path: Path):
        root = self._repo(tmp_path)
        r = _glob_files(pattern=".github/workflows/*", root=str(root))
        assert [f["path"] for f in r["files"]] == [".github/workflows/ci.yml"]

    def test_hidden_root_is_explicit_too(self, tmp_path: Path):
        root = self._repo(tmp_path)
        r = _glob_files(pattern="**/*.yml", root=str(root / ".github"))
        assert r["count"] == 1

    def test_grep_sees_named_hidden_dir(self, tmp_path: Path):
        root = self._repo(tmp_path)
        r = _grep_text(pattern="runs-on", root=str(root), glob=".github/**")
        assert r["count"] == 1

    def test_unnamed_hidden_and_noise_dirs_stay_excluded(self, tmp_path: Path):
        root = self._repo(tmp_path)
        paths = [f["path"] for f in _glob_files(pattern="**/*", root=str(root))["files"]]
        assert paths == ["src/main.py"]

    def test_wildcard_segment_does_not_unlock_hidden_trees(self, tmp_path: Path):
        root = self._repo(tmp_path)
        # '.*' is a guess, not an explicit name; it must not re-open .git/.
        r = _glob_files(pattern=".*/**", root=str(root))
        assert r["count"] == 0


class TestTrailingRecursiveGlobMatchesFiles:
    """``dir/**`` must enumerate files, as bash globstar and ripgrep do.

    Regression: ``Path.glob`` resolves a trailing ``**`` to directories only, so
    with the default ``include_dirs=False`` the query could never match.
    """

    @staticmethod
    def _tree(tmp_path: Path) -> Path:
        (tmp_path / "pkg" / "sub").mkdir(parents=True)
        (tmp_path / "pkg" / "a.py").write_text("a\n")
        (tmp_path / "pkg" / "sub" / "b.py").write_text("b\n")
        return tmp_path

    def test_trailing_globstar_returns_files(self, tmp_path: Path):
        root = self._tree(tmp_path)
        r = _glob_files(pattern="pkg/**", root=str(root))
        assert sorted(f["path"] for f in r["files"]) == ["pkg/a.py", "pkg/sub/b.py"]

    def test_bare_globstar_returns_files(self, tmp_path: Path):
        root = self._tree(tmp_path)
        assert _glob_files(pattern="**", root=str(root))["count"] == 2

    def test_include_dirs_keeps_directory_semantics(self, tmp_path: Path):
        root = self._tree(tmp_path)
        r = _glob_files(pattern="pkg/**", root=str(root), include_dirs=True)
        assert any(f["is_dir"] for f in r["files"])
