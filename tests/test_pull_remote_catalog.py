from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path
from types import ModuleType

import pytest


def _load_script() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "extensions"
        / "workbuddy-experts"
        / "scripts"
        / "pull-remote-catalog.py"
    )
    spec = importlib.util.spec_from_file_location("pull_remote_catalog", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(*members: tarfile.TarInfo) -> tarfile.TarFile:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for member in members:
            payload = b"safe payload" if member.isreg() else None
            if payload is not None:
                member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload) if payload is not None else None)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode="r:")


@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_safe_extract_rejects_archive_links(tmp_path: Path, member_type: bytes) -> None:
    script = _load_script()
    link = tarfile.TarInfo("bundle/link")
    link.type = member_type
    link.linkname = "../../outside"

    with _archive(link) as archive, pytest.raises(ValueError, match="unsupported tar member"):
        script._safe_extract(archive, tmp_path / "dest")

    assert not (tmp_path / "outside").exists()


def test_safe_extract_rejects_traversal_and_existing_symlink(tmp_path: Path) -> None:
    script = _load_script()
    traversal = tarfile.TarInfo("../outside.txt")
    with _archive(traversal) as archive, pytest.raises(ValueError, match="unsafe tar path"):
        script._safe_extract(archive, tmp_path / "dest")

    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "link").symlink_to(outside, target_is_directory=True)
    nested = tarfile.TarInfo("link/payload.txt")
    with _archive(nested) as archive, pytest.raises(ValueError, match="crosses symlink"):
        script._safe_extract(archive, dest)
    assert not (outside / "payload.txt").exists()


def test_safe_extract_writes_regular_files(tmp_path: Path) -> None:
    script = _load_script()
    directory = tarfile.TarInfo("bundle")
    directory.type = tarfile.DIRTYPE
    file_info = tarfile.TarInfo("bundle/agent.md")

    dest = tmp_path / "dest"
    with _archive(directory, file_info) as archive:
        script._safe_extract(archive, dest)

    assert (dest / "bundle" / "agent.md").read_bytes() == b"safe payload"
