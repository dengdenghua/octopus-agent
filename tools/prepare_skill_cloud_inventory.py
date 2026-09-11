"""Prepare a complete, version-preserving LOCAL staging set; never publish it.

The manifest deliberately has no cloud URLs until authenticated release signing
and upload succeed. Existing signed catalogs are not overwritten.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.platform.assets.skill_inventory import SKIP_DIRS, scan_local_skills


def package_skill(root: Path, name: str, out: Path) -> dict:
    package_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-_")[:80] or "skill"
    package_id += "-" + hashlib.sha256(name.casefold().encode()).hexdigest()[:10]
    files: list[tuple[Path, str, str]] = []
    excluded: list[str] = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
        for filename in sorted(names):
            path = Path(directory) / filename
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or filename.lower() in {".env", "auth.json", "credentials.json"} or filename.lower().startswith(".env.") or path.suffix.lower() in {".pem", ".key", ".pfx"}:
                excluded.append(rel)
                continue
            files.append((path, rel, hashlib.sha256(path.read_bytes()).hexdigest()))
    digest = hashlib.sha256(json.dumps([(rel, sha) for _, rel, sha in files], ensure_ascii=False).encode()).hexdigest()
    archive = out / f"skill-{package_id}-{digest[:16]}.tar.gz"
    if not any(rel == "SKILL.md" for _, rel, _ in files):
        raise ValueError(f"Missing SKILL.md: {name}")
    def stable(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ""
        return info
    with archive.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w") as tar:
        for path, rel, _ in files:
            tar.add(path, arcname=f"skills/{package_id}/{rel}", recursive=False, filter=stable)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if len(members) != len(files):
            raise ValueError("Archive member mismatch")
        for member, (_, rel, sha) in zip(members, files, strict=True):
            handle = tar.extractfile(member)
            if not member.isfile() or handle is None or hashlib.sha256(handle.read()).hexdigest() != sha:
                raise ValueError(f"Archive verification failed: {name}/{rel}")
    return {"package_id": package_id, "archive": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size, "files": len(files), "excluded": excluded}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="https://github.com/dengdenghua/workbuddy-expert-market/releases/download/octopus-content")
    parser.add_argument("--metadata-catalog", type=Path, default=Path(__file__).resolve().parents[1] / "extensions/workbuddy-experts/storefront/data/skill-registry.json")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(args.metadata_catalog.read_text(encoding="utf-8")) if args.metadata_catalog.is_file() else {}
    known = {item["name"].casefold(): item for item in metadata.get("skills", [])}
    result = []
    for skill in scan_local_skills():
        packages = {}
        for variant in skill["variants"]:
            package = package_skill(Path(variant["path"]), skill["name"], args.out)
            packages.setdefault(package["sha256"], package)
        result.append({**{k: v for k, v in skill.items() if k != "variants"}, "packages": list(packages.values())})
    manifest = {"status": "prepared_not_published", "skills": result, "count": len(result), "packages": sum(len(item["packages"]) for item in result)}
    (args.out / "inventory.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    catalog = []
    with tarfile.open(args.out / "octopus-skills.tar.gz", "w:gz") as combined:
        for skill in result:
            primary = skill["packages"][0]
            previous = known.get(skill["name"].casefold(), {})
            with tarfile.open(args.out / primary["archive"]) as archive:
                for member in archive.getmembers():
                    combined.addfile(member, archive.extractfile(member))
            catalog.append({
                "name": primary["package_id"], "display_name": skill["name"],
                "aliases": [skill["name"]], "version": skill["version"],
                "description": skill["description"] or previous.get("description", ""),
                "tags": previous.get("tags", []), "author": previous.get("author", ""),
                "source": "echo-skill-inventory",
                "download_url": f"{args.base_url}/octopus-skills.tar.gz",
                "package_url": f"{args.base_url}/{primary['archive']}",
                "package_sha256": primary["sha256"], "package_bytes": primary["bytes"],
                "versions": skill["packages"],
            })
    (args.out / "skill-registry.candidate.json").write_text(json.dumps({
        "meta": {"count": len(catalog), "status": "prepared_not_published"}, "skills": catalog,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ["status", "count", "packages"]}))


if __name__ == "__main__":
    main()
