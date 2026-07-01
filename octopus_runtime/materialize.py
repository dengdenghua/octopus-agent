"""octopus-runtime · materializer(capability-plane.md §B「落地」半边)。

把下载的资产落到产品**现有磁盘布局**:prompt-skill → ``<skills_dir>/<slug>/SKILL.md``,
之后产品自己的 loader(``register_market_skills``)按现有逻辑接管(prompt handler、enabled 闸)。

**安全分水岭**:只落地 ``kind=data``(prompt_pack 等声明式资产);``kind=code``(带执行器的技能/插件)
只能作广告——执行代码永远留在产品本地、不过线(三种 skill kind 决策)。
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .client import DEFAULT_BASE, AssetPayload, RegistryClient

# 冷启动(空目录、97 个技能全要同步)串行拉取实测 ~150s——每个技能是独立 HTTP 往返(部分还要
# 再拉一次 bundle),线程池并发把它压到并发 N 批。httpx 同步调用天然线程安全,无需上 asyncio。
_DEFAULT_WORKERS = 16

# 可安全落地的类型:type=skill 资产 = SKILL.md prompt-pack —— body 被产品当 **prompt 注入**、
# 从不作为代码执行,故落地安全(registry 把 skill 粗标 kind=code 是为将来签名/沙箱策略,
# 不代表 body 是可执行码)。真正可执行的(plugin 等集成)默认不落地,需 allow_code 显式放开。
SAFE_TYPES = {"skill"}
_SAFE_SKILL_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _is_prompt_pack(p: AssetPayload) -> bool:
    return p.type in SAFE_TYPES


def _skill_md(p: AssetPayload) -> str:
    """registry 的 skill body 无 frontmatter → 用信封 name/description 重建,落成 agent 现有格式。"""
    name = (p.name or p.slug).strip()
    desc = " ".join((p.description or "").split())  # 压成单行,贴 SKILL.md frontmatter
    return f"---\nname: {name}\ndescription: {desc}\nsource: registry\n---\n\n{p.body.strip()}\n"


def _safe_skill_slug(p: AssetPayload) -> str:
    prefix, sep, slug = p.id.partition("/")
    if prefix != "skill" or sep != "/" or "/" in slug:
        raise ValueError(f"unsafe skill id from registry payload: {p.id!r}")
    if not _SAFE_SKILL_SLUG_RE.fullmatch(slug):
        raise ValueError(f"unsafe skill slug from registry payload: {slug!r}")
    return slug


def _verify_bundle_checksum(p: AssetPayload, data: bytes) -> None:
    expected = p.bundle.checksum if p.bundle else None
    if not expected:
        return
    expected = expected.removeprefix("sha256:")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f"bundle checksum mismatch for {p.id}: expected {expected} got {actual}")


def _verify_body_checksum(p: AssetPayload) -> None:
    expected = p.content.checksum if p.content else None
    if not expected:
        return
    expected = expected.removeprefix("sha256:")
    actual = hashlib.sha256(p.body.encode("utf-8")).hexdigest()
    if actual != expected:
        raise ValueError(f"checksum mismatch for {p.id}: expected {expected} got {actual}")


def _ensure_safe_skill_dir(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"skill dir must not be a symlink: {path}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"skill dir must be a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _atomic_write_text(path: Path, content: str) -> None:
    _ensure_safe_skill_dir(path.parent)
    tmp: Path | None = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as f:
        tmp = Path(f.name)
        f.write(content)
        f.flush()
    try:
        tmp.replace(path)
    except Exception:
        if tmp is not None and tmp.exists():
            tmp.unlink()
        raise


def _validate_skill_bundle(tar: tarfile.TarFile, skills_dir: Path, slug: str) -> None:
    """Validate that a full-bundle only writes ``<slug>/...`` and contains SKILL.md."""
    dest = skills_dir.resolve()
    skill_root = (dest / slug).resolve()
    skill_md = skill_root / "SKILL.md"
    has_skill_md = False
    for m in tar.getmembers():
        target = (dest / m.name).resolve()
        if target != skill_root and skill_root not in target.parents:
            raise ValueError(f"bundle member outside skill dir {slug!r}: {m.name}")
        if m.issym() or m.islnk():
            raise ValueError(f"link not allowed in bundle: {m.name}")
        if not (m.isdir() or m.isfile()):
            raise ValueError(f"unsupported file type in bundle: {m.name}")
        if target == skill_root and not m.isdir():
            raise ValueError(f"skill root must be a directory in bundle: {m.name}")
        if target == skill_md and m.isfile():
            has_skill_md = True
    if not has_skill_md:
        raise ValueError(f"bundle missing required file: {slug}/SKILL.md")


def _extract_skill_bundle(tar: tarfile.TarFile, skills_dir: Path, slug: str) -> Path:
    """Safely extract a full-bundle into ``skills_dir/slug`` with staged replacement."""
    _validate_skill_bundle(tar, skills_dir, slug)
    skills_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{slug}.", dir=skills_dir) as tmp_name:
        tmp_root = Path(tmp_name)
        try:
            tar.extractall(tmp_root, filter="data")  # noqa: S202 - members validated above.
        except TypeError:  # pragma: no cover - compatibility with older Python 3.11 patch levels
            tar.extractall(tmp_root)  # noqa: S202 - members validated above.
        staged = tmp_root / slug
        md = staged / "SKILL.md"
        if not md.is_file():
            raise ValueError(f"bundle missing required file after extraction: {slug}/SKILL.md")
        dest = skills_dir / slug
        backup = tmp_root / f"{slug}.previous"
        if dest.exists():
            if dest.is_dir() and not dest.is_symlink():
                dest.rename(backup)
            else:
                dest.rename(backup)
        try:
            staged.rename(dest)
        except Exception:
            if backup.exists() and not dest.exists():
                backup.rename(dest)
            raise
        if backup.exists():
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()
    return skills_dir / slug / "SKILL.md"


def materialize_skill(p: AssetPayload, skills_dir: Path, *, client: RegistryClient | None = None) -> Path:
    """落地一个技能到 ``<skills_dir>/<slug>/``。**有 full-bundle 则取整目录 tar.gz 解压**(带
    scripts/refs/requirements);否则只写 ``SKILL.md``(body-only)。返回 SKILL.md 路径。"""
    skills_dir = Path(skills_dir)
    slug = _safe_skill_slug(p)
    if p.bundle and p.bundle.ref:
        c = client or RegistryClient(DEFAULT_BASE)
        data = c.fetch_bundle(p.id)
        _verify_bundle_checksum(p, data)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            return _extract_skill_bundle(tar, skills_dir, slug)
    dest = skills_dir / slug
    md = dest / "SKILL.md"
    _verify_body_checksum(p)
    _atomic_write_text(md, _skill_md(p))
    return md


def _sync_one(
    slug: str, skills_dir: Path, client: RegistryClient, allow_code: bool
) -> tuple[str, str | None, str | None]:
    """拉取 + 落地单个技能。返回 (slug, ok_path_or_None, skip_or_error_reason_or_None)。"""
    asset_id = slug if "/" in slug else f"skill/{slug}"
    try:
        p = client.fetch(asset_id)
        if not _is_prompt_pack(p) and not allow_code:
            return slug, None, f"type={p.type or '?'}/kind={p.kind or '?'}:可执行资产默认不落地(--allow-code 放开)"
        md = materialize_skill(p, skills_dir, client=client)
        return slug, str(md), None
    except Exception as exc:  # noqa: BLE001 — 单个坏不影响整批
        return slug, None, f"__error__:{exc}"


def sync_skills(
    slugs: list[str],
    skills_dir: Path | str,
    *,
    base_url: str = DEFAULT_BASE,
    allow_code: bool = False,
    max_workers: int = _DEFAULT_WORKERS,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """拉取 + 校验 + 落地一批技能(**并发**,httpx 同步调用线程安全)。
    返回 (ok, skipped, errors),各元素 (slug, info)。"""
    client = RegistryClient(base_url)
    skills_dir = Path(skills_dir)
    ok: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    if not slugs:
        return ok, skipped, errors
    with ThreadPoolExecutor(max_workers=min(max_workers, len(slugs))) as pool:
        futures = [pool.submit(_sync_one, slug, skills_dir, client, allow_code) for slug in slugs]
        for fut in as_completed(futures):
            slug, path, reason = fut.result()
            if path:
                ok.append((slug, path))
            elif reason and reason.startswith("__error__:"):
                errors.append((slug, reason.removeprefix("__error__:")))
            elif reason:
                skipped.append((slug, reason))
    return ok, skipped, errors
