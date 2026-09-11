"""Prepare a pinned official OpenCode CLI runtime using only the Python stdlib."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "frontend/electron/opencode-runtime-lock.json"
OUTPUT = ROOT / "extras/desktop/build/opencode"
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 400 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 180


def download_archive(target: str, destination: Path) -> None:
    """Network worker; its parent enforces a hard total deadline."""
    profile = json.loads(LOCK.read_text(encoding="utf-8"))["platforms"][target]
    count = 0
    with (
        urllib.request.urlopen(profile["url"], timeout=30) as response,
        destination.open("wb") as writer,
    ):
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length > MAX_ARCHIVE_BYTES:
            raise ValueError("OpenCode download exceeds size limit")
        while block := response.read(64 * 1024):
            count += len(block)
            if count > MAX_ARCHIVE_BYTES:
                raise ValueError("OpenCode download exceeds size limit")
            writer.write(block)


def run_download_worker(target: str, destination: Path) -> None:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--download-only",
        target,
        "--output",
        str(destination),
    ]
    options: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if os.name == "nt":
        options["creationflags"] |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    try:
        returncode = process.wait(timeout=MAX_DOWNLOAD_SECONDS)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


def verify_archive(archive: Path, expected_sha256: str) -> None:
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected_sha256:
        raise ValueError("OpenCode archive integrity mismatch")


def _copy_archive_member(archive: Path, destination: Path, profile: dict[str, Any]) -> None:
    member_name = profile["archiveMember"]
    if profile["archiveFormat"] == "zip":
        with zipfile.ZipFile(archive) as bundle:
            matches = [info for info in bundle.infolist() if info.filename == member_name]
            if len(matches) != 1 or matches[0].is_dir():
                raise ValueError(f"missing or duplicate OpenCode member: {member_name}")
            info = matches[0]
            unix_mode = info.external_attr >> 16
            if unix_mode and (unix_mode & 0o170000) not in {0, 0o100000}:
                raise ValueError(f"non-regular OpenCode member: {member_name}")
            if not 0 < info.file_size <= MAX_EXECUTABLE_BYTES:
                raise ValueError(f"invalid OpenCode member size: {member_name}")
            source = bundle.open(info)
            with source, destination.open("wb") as writer:
                shutil.copyfileobj(source, writer)
        return
    if profile["archiveFormat"] == "tar.gz":
        with tarfile.open(archive, "r:gz") as bundle:
            matches = [member for member in bundle.getmembers() if member.name == member_name]
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError(
                    f"missing, duplicate or non-regular OpenCode member: {member_name}"
                )
            if not 0 < matches[0].size <= MAX_EXECUTABLE_BYTES:
                raise ValueError(f"invalid OpenCode member size: {member_name}")
            source = bundle.extractfile(matches[0])
            if source is None:
                raise ValueError(f"cannot read OpenCode member: {member_name}")
            with source, destination.open("wb") as writer:
                shutil.copyfileobj(source, writer)
        return
    raise ValueError("unsupported OpenCode archive format")


def extract_runtime(archive: Path, destination: Path, profile: dict[str, Any]) -> dict[str, str]:
    """Copy one exact regular member; never extract an archive-controlled path."""
    executable = destination / profile["executable"]
    _copy_archive_member(archive, executable, profile)
    magic = bytes.fromhex(profile["executableMagic"])
    with executable.open("rb") as stream:
        if stream.read(len(magic)) != magic:
            raise ValueError("OpenCode executable format mismatch")
    executable.chmod(0o755)
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {profile["executable"]: digest}


def verify_prepared_bundle(target: str, output: Path) -> Path:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    profile = lock["platforms"][target]
    if output.is_symlink() or not output.is_dir():
        raise ValueError("OpenCode output is not a regular directory")
    manifest_path = output / "opencode-bundle.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("invalid OpenCode bundle manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "schema": "echo.opencode_bundle.v1",
        "version": lock["version"],
        "platform": target,
        "asset": profile["asset"],
        "archiveSha256": profile["sha256"],
        "executable": profile["executable"],
        "executableMagic": profile["executableMagic"],
        "fileHashPhase": profile["fileHashPhase"],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("OpenCode bundle provenance mismatch")
    if set(manifest.get("files", {})) != {profile["executable"], "LICENSE"}:
        raise ValueError("OpenCode bundle file inventory mismatch")
    expected_entries = {
        profile["executable"],
        "LICENSE",
        "opencode-bundle.json",
    }
    if {entry.name for entry in output.iterdir()} != expected_entries:
        raise ValueError("OpenCode bundle directory inventory mismatch")
    for name, expected_hash in manifest["files"].items():
        file = output / name
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"OpenCode bundle file is not regular: {name}")
        with file.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected_hash:
                raise ValueError(f"OpenCode bundle hash mismatch: {name}")
    executable = output / profile["executable"]
    magic = bytes.fromhex(profile["executableMagic"])
    with executable.open("rb") as stream:
        if stream.read(len(magic)) != magic:
            raise ValueError("OpenCode executable format mismatch")
    return executable


def prepare(target: str, output: Path = OUTPUT, archive: Path | None = None) -> Path:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    profile = lock["platforms"].get(target)
    if profile is None:
        raise ValueError(f"unsupported OpenCode platform: {target}")
    output = output.absolute()
    if output.is_symlink():
        raise ValueError("OpenCode output directory must not be a symlink")
    if archive is None:
        try:
            return verify_prepared_bundle(target, output)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".opencode-stage-", dir=output.parent) as scratch:
        stage = Path(scratch)
        if archive is None:
            archive = stage / profile["asset"]
            run_download_worker(target, archive)
        verify_archive(archive, profile["sha256"])
        files = extract_runtime(archive, stage, profile)
        license_source = ROOT / f"extras/desktop/licenses/opencode-{lock['version']}/LICENSE"
        license_bytes = license_source.read_bytes()
        if hashlib.sha256(license_bytes).hexdigest() != lock["license"]["sha256"]:
            raise ValueError("OpenCode license integrity mismatch")
        (stage / "LICENSE").write_bytes(license_bytes)
        files["LICENSE"] = lock["license"]["sha256"]
        manifest = {
            "schema": "echo.opencode_bundle.v1",
            "version": lock["version"],
            "platform": target,
            "asset": profile["asset"],
            "archiveSha256": profile["sha256"],
            "executable": profile["executable"],
            "executableMagic": profile["executableMagic"],
            "fileHashPhase": profile["fileHashPhase"],
            "files": files,
        }
        manifest_name = "opencode-bundle.json"
        (stage / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Publish the manifest last. An interrupted build cannot validate as complete.
        expected_entries = {*files, manifest_name}
        for entry in output.iterdir():
            if entry.name in expected_entries:
                continue
            if entry.is_dir() and not entry.is_symlink():
                raise ValueError(f"unexpected directory in OpenCode output: {entry.name}")
            entry.unlink()
        for name in [*files, manifest_name]:
            destination = output / name
            if destination.is_symlink():
                raise ValueError(f"OpenCode output must not be a symlink: {name}")
            os.replace(stage / name, destination)
    return output / profile["executable"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default=sys.platform)
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    parser.add_argument("--arch", default=arch, choices=["x64", "arm64"])
    parser.add_argument(
        "--archive", type=Path, help="use a cached archive with the same integrity check"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--download-only", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.download_only:
        download_archive(args.download_only, args.output)
        return
    print(prepare(f"{args.platform}-{args.arch}", args.output, args.archive))


if __name__ == "__main__":
    main()
