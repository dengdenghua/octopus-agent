"""Pinned runtime preparation rejects tampering before publishing a bundle."""

import hashlib
import importlib.util
import io
import json
import stat
import subprocess
import tarfile
import warnings
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "extras/desktop/prepare-opencode.py"
spec = importlib.util.spec_from_file_location("prepare_opencode", SCRIPT)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def make_zip(path, *, link=False, duplicate=False, member="opencode.exe"):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        info = zipfile.ZipInfo(member)
        if link:
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            data = b"../../outside"
        else:
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            data = b"MZ fixture executable"
        bundle.writestr(info, data)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                bundle.writestr(info, data)


def make_tar(path):
    with tarfile.open(path, "w:gz") as bundle:
        data = b"\x7fELF fixture executable"
        member = tarfile.TarInfo("opencode")
        member.mode = 0o755
        member.size = len(data)
        bundle.addfile(member, io.BytesIO(data))


@pytest.fixture
def fixture_bundle(tmp_path, monkeypatch):
    archive = tmp_path / "opencode-windows-x64.zip"
    make_zip(archive)
    root = tmp_path / "repo"
    license_path = root / "extras/desktop/licenses/opencode-test/LICENSE"
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(b"fixture license")
    profile = {
        "asset": archive.name,
        "url": "https://example.invalid/opencode.zip",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archiveFormat": "zip",
        "archiveMember": "opencode.exe",
        "executable": "opencode.exe",
        "executableMagic": "4d5a",
        "fileHashPhase": "pre-authenticode",
    }
    lock = root / "lock.json"
    lock.write_text(
        json.dumps(
            {
                "version": "test",
                "platforms": {"win32-x64": profile},
                "license": {"sha256": hashlib.sha256(license_path.read_bytes()).hexdigest()},
            }
        )
    )
    monkeypatch.setattr(prepare, "ROOT", root)
    monkeypatch.setattr(prepare, "LOCK", lock)
    return archive, tmp_path / "output", profile


def test_verified_cached_asset_publishes_complete_manifest(fixture_bundle):
    archive, output, profile = fixture_bundle
    executable = prepare.prepare("win32-x64", output, archive)
    assert executable.read_bytes() == b"MZ fixture executable"
    manifest = json.loads((output / "opencode-bundle.json").read_text())
    assert manifest["version"] == "test"
    assert manifest["asset"] == profile["asset"]
    assert manifest["archiveSha256"] == profile["sha256"]
    assert set(manifest["files"]) == {"opencode.exe", "LICENSE"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert not list(output.parent.glob(".opencode-stage-*"))


def test_verified_output_skips_a_second_download(fixture_bundle, monkeypatch):
    archive, output, _ = fixture_bundle
    executable = prepare.prepare("win32-x64", output, archive)
    monkeypatch.setattr(
        prepare,
        "run_download_worker",
        lambda *args: (_ for _ in ()).throw(AssertionError("download repeated")),
    )
    assert prepare.prepare("win32-x64", output) == executable


def test_tampered_archive_keeps_existing_bundle(fixture_bundle):
    archive, output, _ = fixture_bundle
    prepare.prepare("win32-x64", output, archive)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="integrity mismatch"):
        prepare.prepare("win32-x64", output, archive)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_download_deadline_failure_preserves_published_bundle(fixture_bundle, monkeypatch):
    archive, output, _ = fixture_bundle
    prepare.prepare("win32-x64", output, archive)
    before = {path.name: path.read_bytes() for path in output.iterdir()}

    def timeout(target, destination):
        assert target == "win32-x64"
        assert destination.name == "opencode-windows-x64.zip"
        raise subprocess.TimeoutExpired(["download"], 180)

    monkeypatch.setattr(prepare, "run_download_worker", timeout)
    monkeypatch.setattr(
        prepare,
        "verify_prepared_bundle",
        lambda *args: (_ for _ in ()).throw(ValueError("force refresh")),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        prepare.prepare("win32-x64", output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert not list(output.parent.glob(".opencode-stage-*"))


@pytest.mark.skipif(prepare.os.name != "nt", reason="Windows process-tree contract")
def test_windows_download_timeout_terminates_exact_process_tree(tmp_path, monkeypatch):
    class Process:
        pid = 43210
        waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(["download"], timeout)
            return 1

    process = Process()
    monkeypatch.setattr(prepare.subprocess, "Popen", lambda *args, **kwargs: process)
    tree_kill = []
    monkeypatch.setattr(
        prepare.subprocess,
        "run",
        lambda command, **kwargs: tree_kill.append((command, kwargs)),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        prepare.run_download_worker("win32-x64", tmp_path / "download.zip")
    assert process.waits == 2
    assert tree_kill[0][0] == ["taskkill", "/PID", "43210", "/T", "/F"]


@pytest.mark.parametrize(
    "kwargs",
    [{"link": True}, {"duplicate": True}, {"member": "unexpected.exe"}],
)
def test_invalid_zip_members_rejected(tmp_path, kwargs):
    archive = tmp_path / "opencode.zip"
    make_zip(archive, **kwargs)
    output = tmp_path / "stage"
    output.mkdir()
    profile = {
        "archiveFormat": "zip",
        "archiveMember": "opencode.exe",
        "executable": "opencode.exe",
        "executableMagic": "4d5a",
    }
    with pytest.raises(ValueError):
        prepare.extract_runtime(archive, output, profile)


def test_linux_tar_asset_extracts_one_regular_member(tmp_path):
    archive = tmp_path / "opencode-linux-x64.tar.gz"
    make_tar(archive)
    output = tmp_path / "stage"
    output.mkdir()
    profile = {
        "archiveFormat": "tar.gz",
        "archiveMember": "opencode",
        "executable": "opencode",
        "executableMagic": "7f454c46",
    }
    files = prepare.extract_runtime(archive, output, profile)
    assert set(files) == {"opencode"}
    assert (output / "opencode").read_bytes().startswith(b"\x7fELF")
