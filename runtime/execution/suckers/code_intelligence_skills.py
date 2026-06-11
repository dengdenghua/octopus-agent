from __future__ import annotations

# ╔════════════════════════════════════════════════════════════════════════╗
# ║ code_intelligence_skills.py · navigation map (1083 lines, 8 skills).   ║
# ║                                                                        ║
# ║   §1 code_analyze (AST + structure)                  ~L14              ║
# ║       _analyze_python                                 ~L50              ║
# ║       _analyze_generic                                ~L156             ║
# ║   §2 embedder + persisted index                      ~L223             ║
# ║   §3 ast_search (pattern + scope)                    ~L271             ║
# ║       _expand_brace_glob, _node_text, etc.           ~L413             ║
# ║       _walk_ast_for_query                            ~L521             ║
# ║   §4 code_search (semantic + text fallback)          ~L582             ║
# ║       _build_index, _split_into_chunks               ~L645             ║
# ║       _fallback_text_search                          ~L697             ║
# ║   §5 code_edit_diff (unified diff application)       ~L734             ║
# ║       _apply_unified_diff                            ~L773             ║
# ║   §6 code_find_symbol (grep-based locator)           ~L812             ║
# ║   §7 code_dependency_graph (import graph)            ~L890             ║
# ║   §8 register_code_intelligence_skills               ~L963             ║
# ╚════════════════════════════════════════════════════════════════════════╝

import ast
import re
from pathlib import Path
from typing import Any

from .registry import Skill, SkillRegistry
from .testing import SkillExpect, SkillTestCase

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

def _code_analyze(
    path: str = "",
    *,
    content: str = "",
    language: str = "",
    **_kw: Any,
) -> dict[str, Any]:
    if not content and path:
        p = Path(path)
        if not p.exists():
            return {"error": f"file not found: {path}"}
        if p.stat().st_size > 500_000:
            return {"error": "file too large (>500KB)"}
        content = p.read_text(encoding="utf-8", errors="replace")

    if not content:
        return {"error": "no content to analyze"}

    if not language:
        language = _guess_language(path)

    if language == "python":
        return _analyze_python(content, path)
    return _analyze_generic(content, path, language)


def _guess_language(path: str) -> str:
    ext = Path(path).suffix.lower() if path else ""
    return {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
        ".rs": "rust", ".java": "java", ".rb": "ruby",
        ".cpp": "cpp", ".c": "c", ".h": "c",
    }.get(ext, "unknown")


def _analyze_python(content: str, path: str) -> dict[str, Any]:
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return {"error": f"syntax error: {e}", "language": "python"}

    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[str] = []
    top_vars: list[str] = []
    calls: list[str] = []
    call_edges: list[dict] = []
    symbols: list[dict] = []

    current_scope: str = "<module>"

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = [a.arg for a in node.args.args]
            decorators = [
                ast.dump(d) if not isinstance(d, ast.Name) else d.id
                for d in node.decorator_list
            ]
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", None),
                "args": args,
                "decorators": decorators[:3],
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "docstring": ast.get_docstring(node) or "",
            })
            symbols.append({
                "name": node.name, "kind": "function",
                "line": node.lineno, "scope": current_scope,
            })
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = ""
                    if isinstance(child.func, ast.Name):
                        callee = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        callee = child.func.attr
                    if callee:
                        call_edges.append({
                            "caller": node.name,
                            "callee": callee,
                            "line": getattr(child, "lineno", 0),
                        })
        elif isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in node.body
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            bases = [ast.dump(b) for b in node.bases]
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", None),
                "methods": methods,
                "bases": bases[:5],
                "docstring": ast.get_docstring(node) or "",
            })
            symbols.append({
                "name": node.name, "kind": "class",
                "line": node.lineno, "scope": current_scope,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    top_vars.append(target.id)
                    symbols.append({
                        "name": target.id, "kind": "variable",
                        "line": node.lineno, "scope": "<module>",
                    })

    unique_edges = {(e["caller"], e["callee"]): e for e in call_edges}

    return {
        "path": path,
        "language": "python",
        "lines": content.count("\n") + 1,
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports[:50],
        "top_level_vars": top_vars[:30],
        "call_graph": list(set(calls))[:50],
        "call_edges": list(unique_edges.values())[:100],
        "symbols": symbols[:100],
    }


def _analyze_generic(content: str, path: str, language: str) -> dict[str, Any]:
    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[str] = []

    fn_patterns = {
        "javascript": r"(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        "typescript": r"(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        "go": r"func\s+(?:\([^)]*\)\s+)?(\w+)",
        "rust": r"(?:pub\s+)?fn\s+(\w+)",
        "java": r"(?:public|private|protected)?\s+\w+\s+(\w+)\s*\(",
        "ruby": r"def\s+(\w+)",
    }
    cls_patterns = {
        "javascript": r"class\s+(\w+)",
        "typescript": r"(?:export\s+)?class\s+(\w+)",
        "go": r"type\s+(\w+)\s+struct",
        "rust": r"(?:pub\s+)?struct\s+(\w+)",
        "java": r"class\s+(\w+)",
        "ruby": r"class\s+(\w+)",
    }
    import_patterns = {
        "javascript": r"import\s+.*?from\s+['\"]([^'\"]+)",
        "typescript": r"import\s+.*?from\s+['\"]([^'\"]+)",
        "go": r'"([^"]+)"',
        "rust": r"use\s+([\w:]+)",
        "java": r"import\s+([\w.]+)",
        "ruby": r"require\s+['\"]([^'\"]+)",
    }

    fn_re = fn_patterns.get(language)
    if fn_re:
        for i, line in enumerate(content.splitlines(), 1):
            m = re.search(fn_re, line)
            if m:
                functions.append({"name": m.group(1), "line": i})

    cls_re = cls_patterns.get(language)
    if cls_re:
        for i, line in enumerate(content.splitlines(), 1):
            m = re.search(cls_re, line)
            if m:
                classes.append({"name": m.group(1), "line": i})

    imp_re = import_patterns.get(language)
    if imp_re:
        imports = re.findall(imp_re, content)[:50]

    return {
        "path": path,
        "language": language,
        "lines": content.count("\n") + 1,
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports,
    }


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

_EMBEDDER = None
_INDEX: list[tuple[str, str, Any]] = []
_INDEX_DIR: str = ""
_INDEX_DB_PATH = Path("data/code_index.db")


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    try:
        from sentence_transformers import SentenceTransformer
        _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
        return _EMBEDDER
    except ImportError:
        return None


def _load_persisted_index() -> list[tuple[str, str, Any]]:
    if not _INDEX_DB_PATH.exists():
        return []
    try:
        import sqlite3

        import numpy as np
        conn = sqlite3.connect(str(_INDEX_DB_PATH))
        rows = conn.execute("SELECT path, chunk, embedding FROM code_chunks").fetchall()
        conn.close()
        return [
            (r[0], r[1], np.frombuffer(r[2], dtype=np.float32))
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def _save_persisted_index(index: list[tuple[str, str, Any]]) -> None:
    try:
        import sqlite3
        _INDEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_INDEX_DB_PATH))
        conn.execute("CREATE TABLE IF NOT EXISTS code_chunks (path TEXT, chunk TEXT, embedding BLOB)")
        conn.execute("DELETE FROM code_chunks")
        for path, chunk, emb in index:
            conn.execute(
                "INSERT INTO code_chunks VALUES (?, ?, ?)",
                (path, chunk, emb.tobytes()),
            )
        conn.commit()
        conn.close()
    except (OSError, ImportError, TypeError, ValueError):  # noqa: BLE001
        pass


def _ast_search(
    *,
    query_type: str,
    target_name: str,
    root: str,
    glob: str,
    sandbox_dir: str | None,
    max_matches: int,
) -> dict[str, Any]:
    allowed = {"function_calls", "function_definitions", "class_definitions", "imports"}
    if not query_type or query_type not in allowed:
        return {
            "error": f"invalid query_type: must be one of {sorted(allowed)}",
            "error_type": "invalid_argument",
        }
    if not target_name:
        return {
            "error": "missing target_name",
            "error_type": "invalid_argument",
        }

    try:
        from .code_edit_skills import _detect_language, _get_parser
    except ImportError:
        return {
            "error": "ast_unavailable",
            "error_type": "dependency_missing",
            "hint": "Install tree-sitter language packages.",
        }
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        return {
            "error": "ast_unavailable",
            "error_type": "dependency_missing",
            "hint": "Install tree-sitter language packages.",
        }

    root_path = Path(root).resolve() if root else Path(".").resolve()
    if not root_path.is_dir():
        return {
            "error": f"root not found: {root}",
            "error_type": "invalid_argument",
        }

    sandbox_root: Path | None = None
    if sandbox_dir:
        try:
            sandbox_root = Path(sandbox_dir).resolve()
        except (OSError, ValueError):
            sandbox_root = None

    candidates: list[Path] = []
    patterns = _expand_brace_glob(glob)
    for pat in patterns:
        for p in root_path.glob(pat):
            if not p.is_file():
                continue
            if any(part.startswith(".") or part in ("node_modules", "__pycache__")
                   for part in p.parts):
                continue
            if sandbox_root is not None:
                try:
                    p.resolve().relative_to(sandbox_root)
                except ValueError:
                    continue
            candidates.append(p)

    seen: set[str] = set()
    files: list[Path] = []
    for p in candidates:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        files.append(p)

    matches: list[dict[str, Any]] = []
    parser_attempted: set[str] = set()
    parser_ok: set[str] = set()
    any_parser_loaded = False

    for f in files:
        if len(matches) >= max_matches:
            break
        language = _detect_language(str(f))
        if not language:
            continue
        if language not in parser_attempted:
            parser_attempted.add(language)
            try:
                p_obj = _get_parser(language)
            except Exception:  # noqa: BLE001
                p_obj = None
            if p_obj is not None:
                parser_ok.add(language)
                any_parser_loaded = True
        if language not in parser_ok:
            continue
        try:
            parser = _get_parser(language)
            if parser is None:
                continue
            source_bytes = f.read_bytes()
            tree = parser.parse(source_bytes)
        except (OSError, UnicodeDecodeError):
            continue
        except Exception:  # noqa: BLE001
            continue

        try:
            rel_path = str(f.relative_to(root_path))
        except ValueError:
            rel_path = str(f)

        for m in _walk_ast_for_query(
            tree.root_node, source_bytes, language, query_type, target_name,
        ):
            m["path"] = rel_path.replace("\\", "/")
            matches.append(m)
            if len(matches) >= max_matches:
                break

    # If no parser ever loaded successfully AND tree-sitter import worked,
    # we likely have files but no language packages installed for them.
    # Still return a useful (empty) result rather than erroring.
    result: dict[str, Any] = {
        "matches": matches,
        "count": len(matches),
        "backend": "ast",
        "query_type": query_type,
        "target_name": target_name,
    }
    if any_parser_loaded:
        result["languages"] = sorted(parser_ok)
    elif files:
        result["note"] = "no parser available for any file in scope"
    else:
        result["note"] = "no files matched glob"
    return result


def _expand_brace_glob(pattern: str) -> list[str]:
    """Expand simple `{a,b,c}` brace alternatives in a glob into multiple patterns."""
    if "{" not in pattern or "}" not in pattern:
        return [pattern]
    start = pattern.index("{")
    end = pattern.index("}", start)
    prefix = pattern[:start]
    suffix = pattern[end + 1:]
    options = pattern[start + 1:end].split(",")
    out: list[str] = []
    for opt in options:
        sub = f"{prefix}{opt.strip()}{suffix}"
        out.extend(_expand_brace_glob(sub))
    return out


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line_snippet(source: bytes, line_idx0: int, max_len: int = 200) -> str:
    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if 0 <= line_idx0 < len(lines):
        return lines[line_idx0].strip()[:max_len]
    return ""


def _call_target_name(call_node: Any, source: bytes, language: str) -> str:
    func_child = call_node.child_by_field_name("function")
    if func_child is None and call_node.child_count > 0:
        func_child = call_node.children[0]
    if func_child is None:
        return ""

    if func_child.type == "identifier":
        return _node_text(func_child, source)
    if func_child.type in ("attribute", "member_expression"):
        attr = (
            func_child.child_by_field_name("attribute")
            or func_child.child_by_field_name("property")
        )
        if attr is not None:
            return _node_text(attr, source)
        last_ident = ""
        cursor = [func_child]
        while cursor:
            n = cursor.pop()
            if n.type in ("identifier", "property_identifier"):
                last_ident = _node_text(n, source)
            cursor.extend(n.children)
        return last_ident
    return ""


def _def_name(def_node: Any, source: bytes) -> str:
    name_node = def_node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node, source)
    for child in def_node.children:
        if child.type in ("identifier", "property_identifier"):
            return _node_text(child, source)
    return ""


def _import_mentions_target(import_node: Any, source: bytes, target_name: str) -> bool:
    text = _node_text(import_node, source)
    if target_name not in text:
        return False
    stack = list(import_node.children)
    while stack:
        n = stack.pop()
        if n.type in ("identifier", "dotted_name"):
            t = _node_text(n, source)
            if t == target_name or t.split(".")[-1] == target_name:
                return True
        if n.type == "aliased_import":
            for c in n.children:
                if c.type in ("identifier", "dotted_name"):
                    t = _node_text(c, source)
                    if t == target_name or t.split(".")[-1] == target_name:
                        return True
        stack.extend(n.children)
    return False


_CALL_TYPES = {
    "python": {"call"},
    "javascript": {"call_expression"},
    "typescript": {"call_expression"},
}
_FUNC_DEF_TYPES = {
    "python": {"function_definition"},
    "javascript": {"function_declaration", "method_definition", "function_expression"},
    "typescript": {"function_declaration", "method_definition", "function_expression"},
}
_CLASS_DEF_TYPES = {
    "python": {"class_definition"},
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration"},
}
_IMPORT_TYPES = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
}


def _walk_ast_for_query(
    root_node: Any,
    source: bytes,
    language: str,
    query_type: str,
    target_name: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = [root_node]
    while stack:
        node = stack.pop()
        try:
            node_type = node.type
        except AttributeError:
            continue

        if query_type == "function_calls" and node_type in _CALL_TYPES.get(language, set()):
            name = _call_target_name(node, source, language)
            if name == target_name:
                line0 = node.start_point[0]
                out.append({
                    "line": line0 + 1,
                    "column": node.start_point[1],
                    "kind": "call",
                    "snippet": _line_snippet(source, line0),
                })
        elif query_type == "function_definitions" and node_type in _FUNC_DEF_TYPES.get(language, set()):
            name = _def_name(node, source)
            if name == target_name:
                line0 = node.start_point[0]
                out.append({
                    "line": line0 + 1,
                    "column": node.start_point[1],
                    "kind": "function_definition",
                    "snippet": _line_snippet(source, line0),
                })
        elif query_type == "class_definitions" and node_type in _CLASS_DEF_TYPES.get(language, set()):
            name = _def_name(node, source)
            if name == target_name:
                line0 = node.start_point[0]
                out.append({
                    "line": line0 + 1,
                    "column": node.start_point[1],
                    "kind": "class_definition",
                    "snippet": _line_snippet(source, line0),
                })
        elif query_type == "imports" and node_type in _IMPORT_TYPES.get(language, set()):
            if _import_mentions_target(node, source, target_name):
                line0 = node.start_point[0]
                out.append({
                    "line": line0 + 1,
                    "column": node.start_point[1],
                    "kind": "import",
                    "snippet": _line_snippet(source, line0),
                })

        stack.extend(node.children)

    return out


def _code_search(
    pattern: str = "",
    *,
    query: str = "",
    mode: str = "regex",
    query_type: str = "",
    target_name: str = "",
    root: str = "",
    directory: str = ".",
    extensions: str = ".py,.ts,.tsx,.js,.go,.rs,.java",
    glob: str = "**/*.{py,ts,tsx,js,jsx}",
    sandbox_dir: str | None = None,
    max_matches: int = 200,
    top_k: int = 10,
    **_kw: Any,
) -> dict[str, Any]:
    # AST structural search mode
    if mode == "ast":
        return _ast_search(
            query_type=query_type,
            target_name=target_name,
            root=root or directory or ".",
            glob=glob,
            sandbox_dir=sandbox_dir,
            max_matches=max_matches,
        )

    # Legacy regex/embedding mode (the "query" / "pattern" param)
    effective_query = query or pattern
    if not effective_query:
        return {"error": "missing query"}

    embedder = _get_embedder()
    if embedder is None:
        return _fallback_text_search(effective_query, directory, extensions, top_k)

    global _INDEX, _INDEX_DIR
    exts = set(extensions.split(","))
    if not _INDEX or directory != _INDEX_DIR:
        _INDEX = _load_persisted_index()
        if not _INDEX or directory != _INDEX_DIR:
            _INDEX = _build_index(embedder, directory, exts)
            _save_persisted_index(_INDEX)
        _INDEX_DIR = directory

    if not _INDEX:
        return {"results": [], "count": 0, "backend": "embedding", "note": "no files indexed"}

    import numpy as np
    q_emb = embedder.encode([effective_query])[0]
    scores = []
    for path, chunk, emb in _INDEX:
        sim = float(np.dot(q_emb, emb) / (np.linalg.norm(q_emb) * np.linalg.norm(emb) + 1e-9))
        scores.append((sim, path, chunk))
    scores.sort(reverse=True)

    results = [
        {"path": p, "score": round(s, 4), "snippet": c[:300]}
        for s, p, c in scores[:top_k]
    ]
    return {"results": results, "count": len(results), "backend": "embedding"}


def _build_index(embedder: Any, directory: str, exts: set[str]) -> list[tuple[str, str, Any]]:
    chunks: list[tuple[str, str]] = []
    root = Path(directory)
    if not root.is_dir():
        return []

    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in exts:
            continue
        if any(part.startswith(".") or part == "node_modules" or part == "__pycache__"
               for part in p.parts):
            continue
        if p.stat().st_size > 200_000:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(root))
        for chunk in _split_into_chunks(content, rel):
            chunks.append((rel, chunk))
        if len(chunks) > 5000:
            break

    if not chunks:
        return []

    texts = [c for _, c in chunks]
    embeddings = embedder.encode(texts, show_progress_bar=False, batch_size=64)
    return [(p, c, e) for (p, c), e in zip(chunks, embeddings, strict=False)]


def _split_into_chunks(content: str, path: str) -> list[str]:
    lines = content.splitlines()
    if len(lines) <= 60:
        return [f"# {path}\n{content}"] if content.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if len(current) >= 50 and (
            re.match(r"^(def |class |function |export |pub fn |func )", line.strip())
            or not line.strip()
        ):
            chunks.append(f"# {path}\n" + "\n".join(current))
            current = []
    if current:
        chunks.append(f"# {path}\n" + "\n".join(current))
    return chunks


def _fallback_text_search(
    query: str, directory: str, extensions: str, top_k: int,
) -> dict[str, Any]:
    results: list[dict] = []
    exts = set(extensions.split(","))
    root = Path(directory)
    if not root.is_dir():
        return {"results": [], "count": 0, "backend": "text_fallback"}

    q_lower = query.lower()
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in exts:
            continue
        if any(part.startswith(".") or part == "node_modules" for part in p.parts):
            continue
        if p.stat().st_size > 200_000:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if q_lower in content.lower():
            for i, line in enumerate(content.splitlines(), 1):
                if q_lower in line.lower():
                    results.append({
                        "path": str(p.relative_to(root)),
                        "line": i,
                        "snippet": line.strip()[:200],
                    })
                    if len(results) >= top_k:
                        return {"results": results, "count": len(results), "backend": "text_fallback"}
    return {"results": results[:top_k], "count": len(results), "backend": "text_fallback"}


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

def _code_edit_diff(
    path: str = "",
    *,
    diff: str = "",
    search: str = "",
    replace: str = "",
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}
    p = Path(path)
    if not p.exists():
        return {"error": f"file not found: {path}"}

    content = p.read_text(encoding="utf-8", errors="replace")

    if search:
        if search not in content:
            return {"error": f"search text not found in {path}", "path": path}
        new_content = content.replace(search, replace, 1)
        p.write_text(new_content, encoding="utf-8")
        return {
            "ok": True,
            "path": path,
            "mode": "search_replace",
            "changes": 1,
        }

    if diff:
        try:
            new_content = _apply_unified_diff(content, diff)
            p.write_text(new_content, encoding="utf-8")
            return {"ok": True, "path": path, "mode": "unified_diff"}
        except ValueError as e:
            return {"error": str(e), "path": path}

    return {"error": "provide either 'diff' or 'search'+'replace'"}


def _apply_unified_diff(original: str, diff_text: str) -> str:
    lines = original.splitlines(keepends=True)
    result = list(lines)
    offset = 0

    for hunk_match in re.finditer(
        r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@.*?\n((?:[+ \-].*?\n)*)",
        diff_text,
    ):
        old_start = int(hunk_match.group(1)) - 1 + offset
        hunk_lines = hunk_match.group(3).splitlines(keepends=True)

        removes = []
        adds = []
        for hl in hunk_lines:
            if hl.startswith("-"):
                removes.append(hl[1:])
            elif hl.startswith("+"):
                adds.append(hl[1:])

        for j, rem in enumerate(removes):
            idx = old_start + j
            if idx < len(result) and result[idx].rstrip("\n") == rem.rstrip("\n"):
                result[idx] = None  # type: ignore[assignment]

        insert_at = old_start
        for add in adds:
            result.insert(insert_at, add)
            insert_at += 1
            offset += 1

        offset -= len(removes)

    return "".join(line for line in result if line is not None)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

def _code_find_symbol(
    symbol: str = "",
    *,
    directory: str = ".",
    extensions: str = ".py",
    **_kw: Any,
) -> dict[str, Any]:
    if not symbol:
        return {"error": "missing symbol name"}

    root = Path(directory)
    if not root.is_dir():
        return {"error": f"directory not found: {directory}"}

    exts = set(extensions.split(","))
    results: list[dict] = []

    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in exts:
            continue
        if any(part.startswith(".") or part in ("node_modules", "__pycache__")
               for part in p.parts):
            continue
        if p.stat().st_size > 500_000:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if p.suffix == ".py":
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == symbol:
                        results.append({
                            "path": str(p.relative_to(root)),
                            "line": node.lineno,
                            "kind": "function",
                            "signature": f"def {node.name}({', '.join(a.arg for a in node.args.args)})",
                        })
                elif isinstance(node, ast.ClassDef):
                    if node.name == symbol:
                        results.append({
                            "path": str(p.relative_to(root)),
                            "line": node.lineno,
                            "kind": "class",
                        })
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == symbol:
                            results.append({
                                "path": str(p.relative_to(root)),
                                "line": node.lineno,
                                "kind": "variable",
                            })
        else:
            for i, line in enumerate(content.splitlines(), 1):
                if re.search(rf"\b{re.escape(symbol)}\b", line):
                    results.append({
                        "path": str(p.relative_to(root)),
                        "line": i,
                        "kind": "reference",
                        "snippet": line.strip()[:150],
                    })

        if len(results) >= 50:
            break

    return {"symbol": symbol, "definitions": results, "count": len(results)}


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

def _code_dependency_graph(
    directory: str = ".",
    *,
    package: str = "",
    **_kw: Any,
) -> dict[str, Any]:
    root = Path(directory)
    if not root.is_dir():
        return {"error": f"directory not found: {directory}"}

    nodes: list[dict] = []
    edges: list[dict] = []
    file_modules: dict[str, str] = {}

    for p in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in ("node_modules", "__pycache__")
               for part in p.parts):
            continue
        if p.stat().st_size > 500_000:
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        mod = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        file_modules[mod] = rel
        nodes.append({"id": rel, "module": mod, "lines": 0})

    for node_info in nodes:
        p = root / node_info["id"]
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        node_info["lines"] = content.count("\n") + 1
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            target_mod = ""
            if isinstance(n, ast.Import):
                for alias in n.names:
                    target_mod = alias.name
            elif isinstance(n, ast.ImportFrom):
                target_mod = n.module or ""
            if not target_mod:
                continue
            if package and not target_mod.startswith(package):
                continue
            for known_mod, known_file in file_modules.items():
                if (target_mod == known_mod
                    or target_mod.startswith(known_mod + ".")
                    or target_mod.endswith("." + known_mod)
                    or target_mod.endswith("." + known_mod.split(".")[-1])):
                    edges.append({
                        "source": node_info["id"],
                        "target": known_file,
                        "import": target_mod,
                    })
                    break

    unique_edges = {(e["source"], e["target"]): e for e in edges}
    return {
        "nodes": nodes[:200],
        "edges": list(unique_edges.values())[:500],
        "node_count": len(nodes),
        "edge_count": len(unique_edges),
    }


# ═══════════════════════════════════════════════════════════
# Registrar
# ═══════════════════════════════════════════════════════════


def register_code_intelligence_skills(registry: SkillRegistry) -> int:
    registry.register(
        Skill(
            name="code_analyze",
            description=(
                "解析代码文件的 AST 结构。返回 functions/classes/imports/"
                "call_graph。支持 Python（精确 AST）和 JS/TS/Go/Rust/Java"
                "（正则 fallback）。Args: {path: string} 或 {content: string, language?: string}。"
                "用于理解代码结构、查找函数定义、分析依赖关系。"
            ),
            affinity=["code", "analysis"],
            cost_profile="low",
            trusted_source="skill://private/code_analyze",
            handler=_code_analyze,
            tests=[
                SkillTestCase(
                    name="empty_returns_error",
                    tier="golden",
                    args={},
                    expect=SkillExpect(output_contains=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="code_search",
            description=(
                "代码搜索。两种模式："
                "(1) 默认 mode='regex' — 语义/embedding 搜索，"
                "Args: {query: string, directory?: string, top_k?: int}。"
                "首次调用会索引目录，后续复用。无 sentence-transformers 时退化为文本搜索。"
                "(2) mode='ast' — tree-sitter 结构化搜索，"
                "Args: {mode:'ast', query_type:'function_calls'|'function_definitions'|"
                "'class_definitions'|'imports', target_name: string, root?: string, "
                "glob?: string}. 跳过注释/字符串中的伪命中。"
            ),
            affinity=["code", "search", "rag"],
            cost_profile="mid",
            trusted_source="skill://private/code_search",
            handler=_code_search,
            tests=[
                SkillTestCase(
                    name="empty_query_error",
                    tier="golden",
                    args={},
                    expect=SkillExpect(output_contains=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="code_edit_diff",
            description=(
                "Diff 级代码编辑。两种模式：(1) search/replace 精确文本替换 "
                "Args: {path, search, replace}；(2) unified diff 应用 "
                "Args: {path, diff}。比整文件覆写更安全精确。"
            ),
            affinity=["code", "fs_write"],
            cost_profile="low",
            trusted_source="skill://private/code_edit_diff",
            handler=_code_edit_diff,
            tests=[
                SkillTestCase(
                    name="missing_path_error",
                    tier="golden",
                    args={},
                    expect=SkillExpect(output_contains=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="code_find_symbol",
            description=(
                "跨文件查找符号定义位置。精确定位函数/类/变量在哪个文件哪一行定义。"
                "Args: {symbol: string, directory?: string}。"
                "用于'跳转到定义'、'查找所有引用'等代码导航场景。"
            ),
            affinity=["code", "analysis"],
            cost_profile="mid",
            trusted_source="skill://private/code_find_symbol",
            handler=_code_find_symbol,
            tests=[
                SkillTestCase(
                    name="empty_symbol_error",
                    tier="golden",
                    args={},
                    expect=SkillExpect(output_contains=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="code_dependency_graph",
            description=(
                "分析 Python 项目的文件间 import 依赖图。"
                "返回 nodes（文件）和 edges（import 关系），可用于理解项目结构。"
                "Args: {directory?: string, package?: string}。"
            ),
            affinity=["code", "analysis"],
            cost_profile="mid",
            trusted_source="skill://private/code_dependency_graph",
            handler=_code_dependency_graph,
            tests=[
                SkillTestCase(
                    name="missing_dir_error",
                    tier="golden",
                    args={"directory": "/nonexistent"},
                    expect=SkillExpect(output_contains=["error"]),
                ),
            ],
        )
    )
    return 5


__all__ = ["register_code_intelligence_skills"]
