"""Read-only remote discovery and explicit, pinned Agent Skill installation.

Search metadata is not authority. Installation downloads only the selected skill,
never runs its scripts, and retains the host's deployment/authentication gates.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

import yaml

from runtime.platform.io import atomic_write_json
from runtime.platform.io.transactional import path_transaction
from runtime.platform.plugins._secure_fetch import fetch_public_https_bytes
from runtime.platform.process.paths import app_paths

OFFICIAL = {"openai": "openai/skills", "anthropic": "anthropics/skills", "vercel": "vercel-labs/agent-skills"}
TTL = 3600
MAX_ARCHIVE = 25 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 5000


def _cache() -> Path:
    return app_paths().data_dir / "cache" / "external-skills"


def _repo(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError("invalid GitHub skill repository")
    return value


def _id(repo: str, name: str) -> str:
    return "external-" + hashlib.sha256(f"{repo.lower()}:{name}".encode()).hexdigest()[:24]


def _json(url: str) -> dict:
    value = json.loads(fetch_public_https_bytes(url, timeout=12, max_bytes=2 * 1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError("invalid remote catalog")
    return value


def _frontmatter(body: bytes) -> tuple[dict, str]:
    text = body.decode("utf-8-sig")
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise ValueError("SKILL.md is missing YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise ValueError("SKILL.md is missing a name")
    if not isinstance(metadata.get("description"), str):
        raise ValueError("SKILL.md is missing a description")
    return metadata, text[match.end():]


def _archive(repo: str, commit: str) -> bytes:
    _repo(repo)
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("skill version must be a pinned commit")
    return fetch_public_https_bytes(f"https://codeload.github.com/{repo}/tar.gz/{commit}", timeout=30, max_bytes=MAX_ARCHIVE)


def _files(body: bytes, *, links: set[str] | None = None) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    expanded = 0
    with tarfile.open(fileobj=io.BytesIO(body), mode="r|gz") as archive:
        for count, member in enumerate(archive):
            if count >= MAX_FILES:
                raise ValueError("skill repository has too many files")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name:
                raise ValueError("unsafe skill archive path")
            if member.isdir():
                continue
            if not member.isfile():
                if member.issym() or member.islnk():
                    if links is not None:
                        links.add(str(PurePosixPath(*path.parts[1:])))
                    continue  # Never materialize links, even within the archive.
                raise ValueError("unsupported skill archive member")
            expanded += member.size
            if member.size > MAX_FILE or expanded > MAX_EXPANDED:
                raise ValueError("skill repository exceeds extraction limits")
            relative = str(PurePosixPath(*path.parts[1:]))
            if relative in files:
                raise ValueError("duplicate skill archive member")
            stream = archive.extractfile(member)
            if stream is not None:
                files[relative] = stream.read(MAX_FILE + 1)
    return files


def _rows(repo: str, commit: str, files: dict[str, bytes], source: str) -> list[dict]:
    rows = []
    for path, body in files.items():
        parts = PurePosixPath(path).parts
        if parts[-1] != "SKILL.md" or any(p.startswith(".") and p not in {".curated", ".experimental"} for p in parts):
            continue
        try:
            meta, _ = _frontmatter(body)
        except (ValueError, UnicodeError, yaml.YAMLError):
            continue
        name = meta["name"].strip()[:160]
        if not name:
            continue
        rows.append({"name": _id(repo, name), "display_name": name, "original_name": name,
                     "description": meta["description"][:6000], "source": source,
                     "author": repo.split("/")[0], "repository": repo, "commit": commit,
                     "version": commit[:12], "skill_path": str(PurePosixPath(path).parent),
                     "source_url": f"https://github.com/{repo}/tree/{commit}/{PurePosixPath(path).parent}",
                     "license": str(meta.get("license") or "见仓库及技能 LICENSE")[:1000],
                     "compatibility": str(meta.get("compatibility") or "依赖以技能说明为准")[:1000],
                     "tags": [], "external": True})
    # Duplicate names within one repository need a path-qualified identity.
    counts = {}
    for row in rows:
        counts[row["name"]] = counts.get(row["name"], 0) + 1
    return [row for row in rows if counts[row["name"]] == 1]


def _remember(rows: list[dict]) -> None:
    path = _cache() / "index.json"
    with path_transaction(path):
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {}
        for row in rows:
            old = index.get(row["name"], {})
            # Search metadata must not overwrite an already pinned official row.
            index[row["name"]] = old if old.get("commit") and not row.get("commit") else row
        atomic_write_json(path, dict(list(index.items())[-10000:]))


def _official(source: str) -> tuple[list[dict], dict]:
    repo = OFFICIAL[source]
    path = _cache() / f"{source}.json"
    with path_transaction(path):
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if time.time() - cached.get("checked_at", 0) < TTL:
            return cached["items"], {"source": source, "state": "ready", "count": len(cached["items"])}
        try:
            commit = _json(f"https://api.github.com/repos/{repo}/commits/HEAD")["sha"]
            rows = _rows(repo, commit, _files(_archive(repo, commit)), source)
            if not rows:
                raise ValueError("empty skill repository")
            _remember(rows)
            atomic_write_json(path, {"checked_at": time.time(), "items": rows})
            return rows, {"source": source, "state": "ready", "count": len(rows)}
        except Exception:
            rows = cached.get("items", [])
            return rows, {"source": source, "state": "stale" if rows else "unavailable", "count": len(rows)}


def _search(query: str) -> tuple[list[dict], dict]:
    if len(query.strip()) < 2:
        return [], {"source": "skills.sh", "state": "search_required", "count": 0}
    path = _cache() / "search" / (hashlib.sha256(query.encode()).hexdigest() + ".json")
    with path_transaction(path):
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if time.time() - cached.get("checked_at", 0) < 300:
            return cached["items"], {"source": "skills.sh", "state": "ready", "count": len(cached["items"])}
        try:
            data = _json("https://skills.sh/api/search?" + urlencode({"q": query[:200], "limit": 30}))
            if not isinstance(data.get("skills"), list):
                raise ValueError("invalid search response")
            rows = []
            for item in data["skills"][:30]:
                try:
                    repo = _repo(str(item.get("source", "")))
                    name = str(item["name"]).strip()[:160]
                    if not name:
                        continue
                except (ValueError, KeyError, AttributeError):
                    continue
                rows.append({"name": _id(repo, name), "display_name": name, "original_name": name,
                             "description": f"Skills.sh 搜索结果 · {repo}；安装时读取完整技能与依赖说明。",
                             "author": repo.split("/")[0], "repository": repo, "source": "skills.sh",
                             "source_url": f"https://github.com/{repo}", "external": True,
                             "search_match": query, "version": "安装时固定提交版本", "tags": []})
            _remember(rows)
            atomic_write_json(path, {"checked_at": time.time(), "items": rows})
            # Search snapshots are an expendable cache, not installed skills.
            for old in sorted(path.parent.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[100:]:
                old.unlink(missing_ok=True)
            return rows, {"source": "skills.sh", "state": "ready", "count": len(rows)}
        except Exception:
            rows = cached.get("items", [])
            return rows, {"source": "skills.sh", "state": "stale" if rows else "unavailable", "count": len(rows)}


def _minimax_design() -> tuple[list[dict], dict]:
    """Discover versioned public packages; media tools remain host dependencies."""
    source = "minimax-design"
    path = _cache() / f"{source}.json"
    with path_transaction(path):
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if cached.get("schema") == 2 and time.time() - cached.get("checked_at", 0) < TTL:
            return cached["items"], {"source": source, "state": "ready", "count": len(cached["items"])}
        try:
            rows = {}
            for page in range(1, 11):
                data = _json("https://design.minimaxi.com/api/v1/skills/market?" + urlencode(
                    {"page": page, "page_size": 20, "source": "official-featured"}))
                items, total = data.get("skills"), data.get("total")
                if not isinstance(items, list) or type(total) is not int or not 0 <= total <= 200:
                    raise ValueError("invalid MiniMax Design catalog")
                previous = len(rows)
                for item in items:
                    name = item.get("name", "") if isinstance(item, dict) else ""
                    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", name):
                        raise ValueError("invalid MiniMax Design skill name")
                    def label(*keys, fallback=""):
                        return next((item[key].strip()[:6000] for key in keys
                                     if isinstance(item.get(key), str) and item[key].strip()), fallback)
                    tags = item.get("tags_cn", [])
                    rows[name] = {
                        "name": _id("minimax-design/catalog", name), "original_name": name,
                        "display_name": label("display_name_zh", fallback=name),
                        "description": label("summary_zh", "desc_cn", "summary", "description"),
                        "version": label("version"), "author": label("author_cn", "author_en", fallback="MiniMax Design"),
                        "source": source, "external": True,
                        "catalog_only": not bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", label("version"))),
                        "source_url": "https://design.minimaxi.com/",
                        "tags": [tag for tag in tags if isinstance(tag, str)][:20] if isinstance(tags, list) else [],
                        "compatibility": "可安装原版技能指令与配套资源。图像、视频、音频生成需另行配置兼容工具与模型；安装不会自动开通 MiniMax 服务。",
                    }
                if len(rows) >= total:
                    break
                if len(rows) == previous:
                    raise ValueError("incomplete MiniMax Design catalog")
            else:
                raise ValueError("MiniMax Design pagination limit exceeded")
            result = list(rows.values())
            _remember(result)
            atomic_write_json(path, {"schema": 2, "checked_at": time.time(), "items": result})
            return result, {"source": source, "state": "ready", "count": len(result)}
        except Exception:
            rows = cached.get("items", [])
            return rows, {"source": source, "state": "stale" if rows else "unavailable", "count": len(rows)}


def list_external_skills(search: str = "") -> dict:
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_official, source) for source in OFFICIAL]
        futures.append(executor.submit(_search, search))
        futures.append(executor.submit(_minimax_design))
        results = [future.result() for future in futures]
    merged = {}
    for rows, _ in results:
        for row in rows:
            if row["name"] in merged:
                if row.get("search_match"):
                    merged[row["name"]]["search_match"] = search
                continue
            merged[row["name"]] = dict(row)
    return {"items": list(merged.values()), "total": len(merged), "meta": {"sources": [state for _, state in results]}}


def _zip_files(body: bytes) -> dict[str, bytes]:
    """Read portable regular files only, without extracting untrusted ZIP paths."""
    files: dict[str, bytes] = {}
    seen: dict[str, bool] = {}
    expanded = 0
    if len(body) > MAX_ARCHIVE:
        raise ValueError("skill archive exceeds download limit")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        if len(members) > MAX_FILES:
            raise ValueError("skill archive has too many files")
        for member in members:
            raw = member.filename.rstrip("/")
            parts = raw.split("/")
            if not raw or "\\" in raw or any(
                p in {"", ".", ".."} or p.endswith((" ", "."))
                or re.search(r'[<>:"|?*\x00-\x1f]', p)
                or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\..*)?", p, re.I)
                for p in parts
            ) or member.orig_filename != member.filename:
                raise ValueError("unsafe skill archive path")
            mode = stat.S_IFMT(member.external_attr >> 16)
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR} or member.flag_bits & 1:
                raise ValueError("unsupported skill archive member")
            directory = member.is_dir()
            if mode == stat.S_IFDIR and not directory:
                raise ValueError("invalid skill archive directory")
            key = raw.casefold()
            if key in seen:
                raise ValueError("duplicate skill archive member")
            seen[key] = directory
            expanded += member.file_size
            if member.file_size > MAX_FILE or expanded > MAX_EXPANDED:
                raise ValueError("skill archive exceeds extraction limits")
            if not directory:
                with archive.open(member) as stream:
                    content = stream.read(MAX_FILE + 1)
                if len(content) != member.file_size or len(content) > MAX_FILE:
                    raise ValueError("invalid skill archive size")
                files[raw] = content
        for path in seen:
            if any(seen.get(str(parent)) is False for parent in PurePosixPath(path).parents if str(parent) != "."):
                raise ValueError("conflicting skill archive paths")
    roots = [path for path in files if path == "SKILL.md" or path.endswith("/SKILL.md")]
    if len(roots) != 1:
        raise ValueError("skill archive must contain one SKILL.md")
    prefix = roots[0][:-len("SKILL.md")]
    if any(not path.startswith(prefix) for path in files):
        raise ValueError("skill archive contains unrelated files")
    result = {path[len(prefix):]: content for path, content in files.items()}
    if any(path.casefold() in {".source.json", "skill.original.md"} for path in result):
        raise ValueError("skill archive contains reserved metadata")
    return result


def _install_design(row: dict, *, skills_dir: Path | None = None) -> dict:
    name, original, version = row["name"], row["original_name"], row.get("version", "")
    if (_id("minimax-design/catalog", original) != name
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", original)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version)):
        raise ValueError("invalid MiniMax Design skill identity or version")
    root = Path(skills_dir or app_paths().data_dir / "skills").resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    with path_transaction(target):
        if target.is_symlink() or target.resolve().parent != root:
            raise ValueError("unsafe skill destination")
        if target.exists():
            if not (target / "SKILL.md").is_file():
                raise ValueError("skill destination is incomplete")
            return {"installed": True, "already_exists": True, "name": name}
        url = "https://design.minimaxi.com/api/v1/skills/market/download?" + urlencode({"name": original, "version": version})
        body = fetch_public_https_bytes(url, timeout=30, max_bytes=MAX_ARCHIVE)
        files = _zip_files(body)
        metadata, instructions = _frontmatter(files["SKILL.md"])
        package = yaml.safe_load(files.get("meta.yaml", b""))
        if metadata["name"] != original or not isinstance(package, dict) or str(package.get("version")) != version:
            raise ValueError("MiniMax Design package name or version mismatch")
        resolved = {**row, "download_url": url, "archive_sha256": hashlib.sha256(body).hexdigest()}
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as temp:
            stage = Path(temp) / name
            stage.mkdir()
            for path, content in files.items():
                dest = stage / path
                if not dest.resolve().is_relative_to(stage.resolve()):
                    raise ValueError("unsafe skill member")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            (stage / "SKILL.original.md").write_bytes(files["SKILL.md"])
            metadata["name"] = name
            metadata["version"] = version
            (stage / "SKILL.md").write_text("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + instructions, encoding="utf-8")
            atomic_write_json(stage / ".source.json", resolved)
            stage.rename(target)
        return {"installed": True, "name": name, "source": row["source"], "version": version, "path": str(target)}


def install_external_skill(name: str, *, skills_dir: Path | None = None) -> dict:
    if not re.fullmatch(r"external-[a-f0-9]{24}", name):
        raise ValueError("invalid external skill identifier")
    try:
        row = json.loads((_cache() / "index.json").read_text(encoding="utf-8"))[name]
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError("请先刷新技能源或重新搜索该技能") from exc
    if row.get("catalog_only"):
        raise ValueError("该技能仅支持目录浏览，请前往 MiniMax Design 使用")
    if row.get("source") == "minimax-design":
        return _install_design(row, skills_dir=skills_dir)
    repo = _repo(row["repository"])
    if _id(repo, row["original_name"]) != name:
        raise ValueError("skill identity mismatch")
    target_root = Path(skills_dir or app_paths().data_dir / "skills").resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / name
    with path_transaction(target):
        if target.is_symlink() or target.resolve().parent != target_root:
            raise ValueError("unsafe skill destination")
        if target.exists():
            if not (target / "SKILL.md").is_file():
                raise ValueError("skill destination is incomplete")
            return {"installed": True, "already_exists": True, "name": name}
        commit = row.get("commit") or _json(f"https://api.github.com/repos/{repo}/commits/HEAD")["sha"]
        links: set[str] = set()
        files = _files(_archive(repo, commit), links=links)
        matches = [item for item in _rows(repo, commit, files, row["source"]) if item["name"] == name]
        if len(matches) != 1:
            raise ValueError("未找到唯一匹配的 SKILL.md，请前往原仓库核对")
        resolved = matches[0]
        prefix = resolved["skill_path"].rstrip("/") + "/"
        if prefix == "./":
            prefix = ""
        if any(path.startswith(prefix) for path in links):
            raise ValueError("该技能包含链接文件，当前安装器不支持；请查看原仓库依赖")
        with tempfile.TemporaryDirectory(prefix=".install-", dir=target_root) as temp:
            stage = Path(temp) / name
            stage.mkdir()
            for path, content in files.items():
                if not path.startswith(prefix):
                    continue
                relative = path[len(prefix):]
                if any(p.startswith(".") for p in PurePosixPath(relative).parts):
                    continue
                dest = stage / relative
                if not dest.resolve().is_relative_to(stage.resolve()):
                    raise ValueError("unsafe skill member")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            # Namespace runtime identity; preserve the complete original instructions.
            metadata, instructions = _frontmatter((stage / "SKILL.md").read_bytes())
            metadata["name"] = name
            (stage / "SKILL.md").write_text("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + instructions, encoding="utf-8")
            for license_name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "NOTICE", "NOTICE.txt"):
                if license_name in files:
                    (stage / ("REPOSITORY-" + license_name)).write_bytes(files[license_name])
            atomic_write_json(stage / ".source.json", resolved)
            stage.rename(target)
        return {"installed": True, "name": name, "source": row["source"], "commit": commit, "path": str(target)}
