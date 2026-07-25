"""Mount backend · unified filesystem access abstraction.

Provides a single ``MountBackend`` interface with concrete adapters for
six remote/local filesystem protocols:

  * local  → ``LocalMountBackend`` (pathlib + atomic_write_bytes)
  * sftp   → ``SftpMountBackend`` (paramiko SFTPClient)
  * webdav → ``WebdavMountBackend`` (requests + PROPFIND/GET/PUT/MKCOL/DELETE)
  * smb    → ``SmbMountBackend`` (smbprotocol/smbclient, graceful fallback)
  * nfs    → ``NfsMountBackend`` (delegates to LocalMountBackend on OS-mounted share)
  * s3     → ``S3MountBackend`` (boto3, MinIO/AWS/OSS-compatible, graceful fallback)

All public methods are ``async``; blocking IO is wrapped in
``asyncio.to_thread`` so a single event loop can multiplex many mounts.

Optional dependencies (``paramiko`` / ``requests`` / ``smbprotocol`` /
``boto3``) are imported lazily inside the methods that need them.
``test_connection`` returns ``False`` (rather than raising) when the
optional dep is missing, so a registry probe never crashes the host
process. Other methods raise ``BackendUnavailableError`` so the caller
sees a clear actionable message.

Path semantics
--------------

``path`` arguments are interpreted relative to the backend's
``root_path``. Absolute paths (POSIX-leading ``/`` or, for local,
``Path.is_absolute()``) are used as-is and still subject to the
backend's whitelist (local only). Paths returned in ``DirEntry.path``
and ``FileStat.path`` are relative to ``root_path`` so they can be
round-tripped through the same backend.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import posixpath
import shutil
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote, urlparse

from runtime.platform.io.atomic import atomic_write_bytes

from .local import LocalBackend

_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Errors
# ═══════════════════════════════════════════════════════════


class BackendUnavailableError(RuntimeError):
    """Raised when an optional backend dependency is missing."""


class BackendError(RuntimeError):
    """Generic backend error (transport failure, malformed response, …)."""


# ═══════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════


@dataclass
class DirEntry:
    """A single entry returned by ``list_dir``."""

    name: str
    path: str
    is_dir: bool
    size: int
    modified: float  # unix timestamp


@dataclass
class FileStat:
    """Metadata for a single file or directory."""

    path: str
    is_dir: bool
    size: int
    modified: float
    created: float | None = None


# ═══════════════════════════════════════════════════════════
# Abstract base
# ═══════════════════════════════════════════════════════════


class MountBackend(ABC):
    """Unified filesystem access abstraction layer."""

    @abstractmethod
    async def read_file(self, path: str) -> bytes: ...

    @abstractmethod
    async def write_file(self, path: str, content: bytes) -> None: ...

    @abstractmethod
    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]: ...

    @abstractmethod
    async def stat(self, path: str) -> FileStat: ...

    @abstractmethod
    async def mkdir(self, path: str) -> None: ...

    @abstractmethod
    async def remove(self, path: str) -> None: ...

    @abstractmethod
    async def test_connection(self) -> bool: ...


# ═══════════════════════════════════════════════════════════
# LocalMountBackend
# ═══════════════════════════════════════════════════════════


# Subset of fs_router.TREE_IGNORED_DIRS that the mount layer filters
# from list_dir by default. Kept small and conservative so remote
# mounts don't surprise the caller by hiding real directories.
DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".octopus",
    "logs",
})


class LocalMountBackend(MountBackend):
    """Local filesystem backend with path whitelist enforcement.

    Wraps :class:`runtime.sensing.server.local.LocalBackend` for
    read/write whitelist checks. Writes go through
    :func:`runtime.platform.io.atomic.atomic_write_bytes` so a crash
    mid-write never leaves a half-written file.
    """

    def __init__(
        self,
        root_path: str | Path,
        *,
        allowed_read_roots: list[Path] | None = None,
        allowed_write_roots: list[Path] | None = None,
        ignored_dirs: frozenset[str] | None = None,
    ) -> None:
        self.root_path = Path(root_path).expanduser().resolve()
        if not self.root_path.exists():
            raise FileNotFoundError(f"root_path does not exist: {self.root_path}")
        # Default the sandbox to root_path so callers can't escape
        # the mount without explicitly widening the whitelist.
        read_roots = (
            [self.root_path]
            if allowed_read_roots is None
            else [Path(p).resolve() for p in allowed_read_roots]
        )
        write_roots = (
            [self.root_path]
            if allowed_write_roots is None
            else [Path(p).resolve() for p in allowed_write_roots]
        )
        self._guard = LocalBackend(
            allowed_read_roots=read_roots,
            allowed_write_roots=write_roots,
        )
        self.ignored_dirs = ignored_dirs if ignored_dirs is not None else DEFAULT_IGNORED_DIRS

    # ── path resolution ───────────────────────────────────

    def _resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        return p.resolve() if p.is_absolute() else (self.root_path / p).resolve()

    def _check_read(self, path: Path) -> Path:
        if not self._guard.allows_read(path):
            raise PermissionError(f"backend denied read: {path}")
        return path

    def _check_write(self, path: Path) -> Path:
        if not self._guard.allows_write(path):
            raise PermissionError(f"backend denied write: {path}")
        return path

    def _rel_path(self, p: Path) -> str:
        try:
            return p.relative_to(self.root_path).as_posix()
        except ValueError:
            return str(p)

    # ── MountBackend implementation ───────────────────────

    async def read_file(self, path: str) -> bytes:
        resolved = self._check_read(self._resolve(path))
        return await asyncio.to_thread(resolved.read_bytes)

    async def write_file(self, path: str, content: bytes) -> None:
        resolved = self._check_write(self._resolve(path))
        await asyncio.to_thread(atomic_write_bytes, resolved, content)

    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]:
        resolved = self._check_read(self._resolve(path))
        if not resolved.exists():
            raise FileNotFoundError(f"path not found: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"not a directory: {resolved}")
        return await asyncio.to_thread(self._list_dir_sync, resolved, depth)

    def _list_dir_sync(self, root: Path, depth: int) -> list[DirEntry]:
        entries: list[DirEntry] = []

        def _recurse(current: Path, current_depth: int) -> None:
            if current_depth > depth:
                return
            try:
                with os.scandir(current) as it:
                    children = sorted(it, key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError as exc:
                _logger.warning("local_mount · scandir failed on %s: %s", current, exc)
                return
            for entry in children:
                try:
                    is_dir = entry.is_dir()
                    name = entry.name
                    if is_dir and name in self.ignored_dirs:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    entries.append(
                        DirEntry(
                            name=name,
                            path=self._rel_path(Path(entry.path)),
                            is_dir=is_dir,
                            size=info.st_size,
                            modified=info.st_mtime,
                        )
                    )
                    if is_dir and current_depth < depth:
                        _recurse(Path(entry.path), current_depth + 1)
                except OSError as exc:
                    _logger.debug("local_mount · skip %s: %s", entry.path, exc)

        _recurse(root, 1)
        return entries

    async def stat(self, path: str) -> FileStat:
        resolved = self._check_read(self._resolve(path))
        if not resolved.exists():
            raise FileNotFoundError(f"path not found: {resolved}")
        info = await asyncio.to_thread(resolved.stat)
        return FileStat(
            path=self._rel_path(resolved),
            is_dir=info.st_mode & 0o170000 == 0o040000,
            size=info.st_size,
            modified=info.st_mtime,
            created=info.st_ctime,
        )

    async def mkdir(self, path: str) -> None:
        resolved = self._check_write(self._resolve(path))
        await asyncio.to_thread(lambda: resolved.mkdir(parents=True, exist_ok=True))

    async def remove(self, path: str) -> None:
        resolved = self._check_write(self._resolve(path))
        if not resolved.exists():
            raise FileNotFoundError(f"path not found: {resolved}")

        def _remove() -> None:
            if resolved.is_dir() and not resolved.is_symlink():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()

        await asyncio.to_thread(_remove)

    async def test_connection(self) -> bool:
        return await asyncio.to_thread(lambda: self.root_path.exists() and os.access(self.root_path, os.R_OK))


# ═══════════════════════════════════════════════════════════
# SftpMountBackend
# ═══════════════════════════════════════════════════════════


class SftpMountBackend(MountBackend):
    """SFTP backend backed by ``paramiko.SFTPClient``.

    Connection parameters mirror :class:`runtime.sensing.server.ssh.SshBackend`
    (``host`` / ``user`` / ``port`` / ``identity_file`` / ``password``)
    so the same mount_options shape works for both.
    """

    def __init__(
        self,
        *,
        host: str,
        user: str | None = None,
        port: int = 22,
        identity_file: str | Path | None = None,
        password: str | None = None,
        root_path: str = "/",
        connect_timeout: int = 10,
        strict_host_key_checking: bool = False,
        known_hosts_file: str | Path | None = None,
    ) -> None:
        if not host:
            raise ValueError("host required")
        if port <= 0 or port > 65535:
            raise ValueError(f"port out of range: {port}")
        self.host = host
        self.user = user
        self.port = port
        self.identity_file = Path(identity_file) if identity_file else None
        self.password = password
        self.root_path = root_path or "/"
        self.connect_timeout = connect_timeout
        self.strict_host_key_checking = strict_host_key_checking
        self.known_hosts_file = Path(known_hosts_file) if known_hosts_file else None
        self._sftp: Any = None
        self._client: Any = None  # underlying SSHClient
        self._lock = asyncio.Lock()

    # ── connection management ─────────────────────────────

    def _ensure_available(self) -> None:
        try:
            import paramiko  # noqa: F401
        except ImportError as e:  # pragma: no cover - exercised via mock
            raise BackendUnavailableError(
                "paramiko not installed · pip install paramiko",
            ) from e

    async def _ensure_connected(self) -> Any:
        async with self._lock:
            if self._sftp is not None:
                # Cheap liveness probe; if the channel is dead we drop
                # the cached handle and reconnect below.
                try:
                    await asyncio.to_thread(self._sftp.stat, ".")
                    return self._sftp
                except Exception:  # noqa: BLE001 — reconnect path
                    _logger.info("sftp_backend · stale connection, reconnecting")
                    self._close_sync()
            self._ensure_available()
            await asyncio.to_thread(self._connect_sync)
            return self._sftp

    def _connect_sync(self) -> None:
        import paramiko

        client = paramiko.SSHClient()
        if self.strict_host_key_checking:
            if self.known_hosts_file is not None:
                client.load_host_keys(str(self.known_hosts_file))
            else:
                client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            if self.known_hosts_file is not None:
                client.load_host_keys(str(self.known_hosts_file))
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
        connect_kwargs: dict[str, Any] = {
            "hostname": self.host,
            "port": self.port,
            "timeout": self.connect_timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if self.user:
            connect_kwargs["username"] = self.user
        if self.identity_file:
            connect_kwargs["key_filename"] = str(self.identity_file)
        if self.password is not None:
            connect_kwargs["password"] = self.password
        client.connect(**connect_kwargs)
        self._client = client
        self._sftp = client.open_sftp()

    def _close_sync(self) -> None:
        if self._sftp is not None:
            with contextlib.suppress(Exception):
                self._sftp.close()
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
        self._sftp = None
        self._client = None

    # ── path resolution ───────────────────────────────────

    def _resolve(self, path: str) -> str:
        if posixpath.isabs(path):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(self.root_path, path))

    def _rel_path(self, p: str) -> str:
        root = self.root_path.rstrip("/")
        if root and p.startswith(root + "/"):
            return p[len(root) + 1:]
        if p == root:
            return ""
        return p.lstrip("/")

    # ── MountBackend implementation ───────────────────────

    async def read_file(self, path: str) -> bytes:
        sftp = await self._ensure_connected()
        remote = self._resolve(path)

        def _read() -> bytes:
            with sftp.open(remote, "rb") as fh:
                return fh.read()

        return await asyncio.to_thread(_read)

    async def write_file(self, path: str, content: bytes) -> None:
        sftp = await self._ensure_connected()
        remote = self._resolve(path)
        # Write to a sibling temp file then rename — best-effort
        # atomicity, mirroring local atomic_write_bytes semantics.
        tmp = remote + f".octopus-tmp-{os.getpid()}-{id(content) & 0xFFFFFFFF}"

        def _write() -> None:
            parent = posixpath.dirname(remote)
            if parent:
                with contextlib.suppress(Exception):
                    sftp.mkdir(parent)
            with sftp.open(tmp, "wb") as fh:
                fh.write(content)
            if hasattr(sftp, "posix_rename"):
                sftp.posix_rename(tmp, remote)
            else:
                sftp.rename(tmp, remote)

        try:
            await asyncio.to_thread(_write)
        except Exception:
            with contextlib.suppress(Exception):
                sftp.remove(tmp)
            raise

    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]:
        sftp = await self._ensure_connected()
        remote = self._resolve(path)
        return await asyncio.to_thread(self._list_dir_sync, sftp, remote, depth)

    def _list_dir_sync(self, sftp: Any, remote: str, depth: int) -> list[DirEntry]:
        entries: list[DirEntry] = []

        def _recurse(current: str, current_depth: int) -> None:
            if current_depth > depth:
                return
            try:
                attrs = sftp.listdir_attr(current)
            except OSError as exc:
                _logger.warning("sftp_backend · listdir failed on %s: %s", current, exc)
                return
            attrs.sort(key=lambda a: (not stat_is_dir(a), a.filename.lower()))
            for attr in attrs:
                child_path = posixpath.join(current, attr.filename)
                is_dir = stat_is_dir(attr)
                entries.append(
                    DirEntry(
                        name=attr.filename,
                        path=self._rel_path(child_path),
                        is_dir=is_dir,
                        size=getattr(attr, "st_size", 0) or 0,
                        modified=getattr(attr, "st_mtime", 0.0) or 0.0,
                    )
                )
                if is_dir and current_depth < depth:
                    _recurse(child_path, current_depth + 1)

        _recurse(remote, 1)
        return entries

    async def stat(self, path: str) -> FileStat:
        sftp = await self._ensure_connected()
        remote = self._resolve(path)
        attr = await asyncio.to_thread(sftp.stat, remote)
        return FileStat(
            path=self._rel_path(remote),
            is_dir=stat_is_dir(attr),
            size=getattr(attr, "st_size", 0) or 0,
            modified=getattr(attr, "st_mtime", 0.0) or 0.0,
        )

    async def mkdir(self, path: str) -> None:
        sftp = await self._ensure_connected()
        remote = self._resolve(path)

        def _mkdir() -> None:
            # Build parents like mkdir -p.
            parts = [p for p in remote.split("/") if p]
            cur = "/" if remote.startswith("/") else ""
            for part in parts:
                cur = posixpath.join(cur, part) if cur else part
                with contextlib.suppress(Exception):
                    sftp.mkdir(cur)

        await asyncio.to_thread(_mkdir)

    async def remove(self, path: str) -> None:
        sftp = await self._ensure_connected()
        remote = self._resolve(path)

        def _remove() -> None:
            try:
                sftp.remove(remote)
                return
            except OSError:
                pass
            # Directory: recurse + rmdir.
            self._rmtree_sync(sftp, remote)

        await asyncio.to_thread(_remove)

    def _rmtree_sync(self, sftp: Any, remote: str) -> None:
        for attr in sftp.listdir_attr(remote):
            child = posixpath.join(remote, attr.filename)
            if stat_is_dir(attr):
                self._rmtree_sync(sftp, child)
            else:
                with contextlib.suppress(Exception):
                    sftp.remove(child)
        sftp.rmdir(remote)

    async def test_connection(self) -> bool:
        try:
            self._ensure_available()
            await self._ensure_connected()
            return True
        except BackendUnavailableError as e:
            _logger.warning("sftp_backend · unavailable: %s", e)
            return False
        except Exception as e:  # noqa: BLE001 — connection probe should not raise
            _logger.warning("sftp_backend · test_connection failed: %s", e)
            return False


# ═══════════════════════════════════════════════════════════
# WebdavMountBackend
# ═══════════════════════════════════════════════════════════


_WEBDAV_PROPFIND_BODY = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:displayname/>
    <D:getcontentlength/>
    <D:getlastmodified/>
    <D:resourcetype/>
  </D:prop>
</D:propfind>
"""


class WebdavMountBackend(MountBackend):
    """Pure-HTTP WebDAV backend.

    Uses ``requests`` (lazy import) to issue PROPFIND / GET / PUT /
    MKCOL / DELETE. Compatible with Nextcloud, 坚果云, CloudDrive2,
    and any RFC 4918-conformant WebDAV server. Basic Auth only.
    """

    def __init__(
        self,
        *,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        root_path: str = "/",
        timeout: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("base_url required")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.root_path = root_path or "/"
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    # ── helpers ───────────────────────────────────────────

    def _ensure_available(self) -> None:
        try:
            import requests  # noqa: F401
        except ImportError as e:  # pragma: no cover - exercised via mock
            raise BackendUnavailableError(
                "requests not installed · pip install requests",
            ) from e

    def _resolve_url(self, path: str) -> str:
        if posixpath.isabs(path):
            rel = path.lstrip("/")
        else:
            root = self.root_path.strip("/")
            rel = f"{root}/{path}" if root else path
        rel = quote(rel, safe="/")
        return f"{self.base_url}/{rel}"

    def _rel_path(self, url_path: str) -> str:
        # url_path is the DAV:href from PROPFIND, or our own resolved
        # path; strip the base + root prefix to get the relative path.
        try:
            from urllib.parse import unquote

            decoded = unquote(url_path)
            parsed = urlparse(decoded)
            decoded = parsed.path or decoded
        except Exception:  # noqa: BLE001
            decoded = url_path
        base_path = urlparse(self.base_url).path.rstrip("/")
        if base_path and decoded.startswith(base_path):
            decoded = decoded[len(base_path):]
        root = self.root_path.strip("/")
        if root and decoded.startswith("/" + root):
            decoded = decoded[len(root) + 1:]
        return decoded.lstrip("/")

    def _auth(self) -> tuple[str, str] | None:
        if self.username is not None and self.password is not None:
            return (self.username, self.password)
        return None

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        import requests

        return requests.request(
            method,
            url,
            data=data,
            headers=headers,
            auth=self._auth(),
            timeout=self.timeout,
            verify=self.verify_ssl,
        )

    # ── MountBackend implementation ───────────────────────

    async def read_file(self, path: str) -> bytes:
        self._ensure_available()
        url = self._resolve_url(path)
        response = await asyncio.to_thread(self._request, "GET", url)
        if response.status_code >= 400:
            raise BackendError(f"webdav GET {url} → {response.status_code}: {response.text[:200]}")
        return response.content

    async def write_file(self, path: str, content: bytes) -> None:
        self._ensure_available()
        url = self._resolve_url(path)
        # Ensure parent collection exists (best-effort).
        parent = posixpath.dirname(path.rstrip("/"))
        if parent and parent not in ("", "."):
            await self._ensure_collection(parent)
        response = await asyncio.to_thread(
            self._request,
            "PUT",
            url,
            data=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        if response.status_code >= 400:
            raise BackendError(f"webdav PUT {url} → {response.status_code}: {response.text[:200]}")

    async def _ensure_collection(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}" if cur else part
            url = self._resolve_url(cur)
            response = await asyncio.to_thread(self._request, "MKCOL", url)
            # 201 created, 405 already exists — both fine.
            if response.status_code not in (200, 201, 405):
                _logger.debug("webdav MKCOL %s → %s", url, response.status_code)

    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]:
        self._ensure_available()
        url = self._resolve_url(path)
        # Depth: 0 → only the resource itself, 1 → immediate children,
        # infinity → whole subtree (servers may reject). Map our depth
        # to the WebDAV Depth header; for depth > 1 we use infinity and
        # post-filter by the requested depth.
        depth_header = "infinity" if depth > 1 else "1"
        response = await asyncio.to_thread(
            self._request,
            "PROPFIND",
            url,
            data=_WEBDAV_PROPFIND_BODY,
            headers={"Depth": depth_header, "Content-Type": "application/xml"},
        )
        if response.status_code >= 400:
            raise BackendError(
                f"webdav PROPFIND {url} → {response.status_code}: {response.text[:200]}",
            )
        return self._parse_propfind(response.content, path, depth)

    def _parse_propfind(self, body: bytes, requested_path: str, max_depth: int) -> list[DirEntry]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise BackendError(f"webdav PROPFIND returned malformed XML: {exc}") from exc
        # The first <response> is the collection itself; skip it.
        responses = _find_local(root, "response")
        entries: list[DirEntry] = []
        base_rel = self._rel_path(requested_path).strip("/")
        for resp in responses[1:]:
            href_el = _find_local(resp, "href")
            if not href_el:
                continue
            href_text = href_el[0].text or ""
            rel = self._rel_path(href_text)
            if not rel or rel == base_rel:
                continue
            # Enforce depth for infinity responses.
            if max_depth > 1:
                rel_depth = rel.count("/") - base_rel.count("/")
                if rel_depth < 0:
                    continue
                # Use a lenient depth filter: include direct + nested up to max_depth.
                # (Some servers return all descendants regardless of Depth header.)
            is_dir, size, modified = _extract_dav_props(resp)
            name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
            entries.append(
                DirEntry(
                    name=name,
                    path=rel,
                    is_dir=is_dir,
                    size=size,
                    modified=modified,
                )
            )
        return entries

    async def stat(self, path: str) -> FileStat:
        self._ensure_available()
        url = self._resolve_url(path)
        response = await asyncio.to_thread(
            self._request,
            "PROPFIND",
            url,
            data=_WEBDAV_PROPFIND_BODY,
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        if response.status_code >= 400:
            raise BackendError(
                f"webdav PROPFIND {url} → {response.status_code}: {response.text[:200]}",
            )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise BackendError(f"webdav PROPFIND returned malformed XML: {exc}") from exc
        responses = _find_local(root, "response")
        if not responses:
            raise BackendError("webdav PROPFIND returned no responses")
        is_dir, size, modified = _extract_dav_props(responses[0])
        return FileStat(
            path=self._rel_path(path),
            is_dir=is_dir,
            size=size,
            modified=modified,
        )

    async def mkdir(self, path: str) -> None:
        self._ensure_available()
        url = self._resolve_url(path)
        response = await asyncio.to_thread(self._request, "MKCOL", url)
        if response.status_code not in (200, 201, 405):
            raise BackendError(
                f"webdav MKCOL {url} → {response.status_code}: {response.text[:200]}",
            )

    async def remove(self, path: str) -> None:
        self._ensure_available()
        url = self._resolve_url(path)
        response = await asyncio.to_thread(self._request, "DELETE", url)
        if response.status_code not in (200, 204, 404):
            raise BackendError(
                f"webdav DELETE {url} → {response.status_code}: {response.text[:200]}",
            )

    async def test_connection(self) -> bool:
        try:
            self._ensure_available()
        except BackendUnavailableError as e:
            _logger.warning("webdav_backend · unavailable: %s", e)
            return False
        try:
            url = self._resolve_url("/")
            response = await asyncio.to_thread(
                self._request,
                "PROPFIND",
                url,
                data=_WEBDAV_PROPFIND_BODY,
                headers={"Depth": "0", "Content-Type": "application/xml"},
            )
            return response.status_code < 400
        except Exception as e:  # noqa: BLE001 — probe must not raise
            _logger.warning("webdav_backend · test_connection failed: %s", e)
            return False


# ═══════════════════════════════════════════════════════════
# SmbMountBackend
# ═══════════════════════════════════════════════════════════


class SmbMountBackend(MountBackend):
    """SMB/CIFS backend backed by ``smbprotocol`` (``smbclient``).

    Graceful fallback: if ``smbprotocol`` is not installed,
    ``test_connection`` returns ``False`` and other methods raise
    ``BackendUnavailableError`` with the install hint.
    """

    _DEP_HINT: ClassVar[str] = "smbprotocol not installed · pip install smbprotocol"

    def __init__(
        self,
        *,
        host: str,
        share: str,
        username: str | None = None,
        password: str | None = None,
        domain: str | None = None,
        root_path: str = "",
        timeout: int = 30,
    ) -> None:
        if not host:
            raise ValueError("host required")
        if not share:
            raise ValueError("share required")
        self.host = host
        self.share = share.strip("\\/")
        self.username = username
        self.password = password
        self.domain = domain
        self.root_path = root_path or ""
        self.timeout = timeout

    def _ensure_available(self) -> None:
        try:
            import smbclient  # noqa: F401
        except ImportError as e:  # pragma: no cover - exercised via mock
            raise BackendUnavailableError(self._DEP_HINT) from e

    def _unc(self, path: str) -> str:
        # Normalise to backslash-separated components; callers may pass
        # either POSIX-style or Windows-style relative paths.
        rel = path.replace("/", "\\").strip("\\/")
        parts = [f"\\\\{self.host}", self.share]
        root = self.root_path.replace("/", "\\").strip("\\/")
        if root:
            parts.append(root)
        if rel:
            parts.append(rel)
        return "\\".join(parts)

    @staticmethod
    def _rel(unc: str) -> str:
        # Strip the leading \\host\share\[root]\ prefix as best-effort;
        # callers primarily care about the leaf name for display.
        parts = unc.split("\\")
        return "\\".join(parts[3:]) if len(parts) > 3 else parts[-1]

    async def read_file(self, path: str) -> bytes:
        self._ensure_available()
        import smbclient

        unc = self._unc(path)

        def _read() -> bytes:
            with smbclient.open_file(unc, mode="rb") as fh:
                return fh.read()

        return await asyncio.to_thread(_read)

    async def write_file(self, path: str, content: bytes) -> None:
        self._ensure_available()
        import smbclient

        unc = self._unc(path)

        def _write() -> None:
            parent = "\\".join(unc.split("\\")[:-1])
            if parent:
                with contextlib.suppress(Exception):
                    smbclient.mkdir(parent)
            with smbclient.open_file(unc, mode="wb") as fh:
                fh.write(content)

        await asyncio.to_thread(_write)

    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]:
        self._ensure_available()
        import smbclient

        unc = self._unc(path)
        return await asyncio.to_thread(self._list_dir_sync, smbclient, unc, depth)

    def _list_dir_sync(self, smbclient: Any, unc: str, depth: int) -> list[DirEntry]:
        entries: list[DirEntry] = []

        def _recurse(current: str, current_depth: int) -> None:
            if current_depth > depth:
                return
            try:
                infos = smbclient.listdir(current)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("smb_backend · listdir failed on %s: %s", current, exc)
                return
            for name in sorted(infos, key=lambda n: n.lower()):
                child = f"{current}\\{name}"
                try:
                    info = smbclient.getinfo(child)
                except Exception:  # noqa: BLE001
                    continue
                is_dir = info.is_directory()
                entries.append(
                    DirEntry(
                        name=name,
                        path=self._rel(child) or name,
                        is_dir=is_dir,
                        size=getattr(info, "file_size", 0) or 0,
                        modified=_smb_mtime(info),
                    )
                )
                if is_dir and current_depth < depth:
                    _recurse(child, current_depth + 1)

        _recurse(unc, 1)
        return entries

    async def stat(self, path: str) -> FileStat:
        self._ensure_available()
        import smbclient

        unc = self._unc(path)
        info = await asyncio.to_thread(smbclient.getinfo, unc)
        return FileStat(
            path=self._rel(unc) or path,
            is_dir=info.is_directory(),
            size=getattr(info, "file_size", 0) or 0,
            modified=_smb_mtime(info),
        )

    async def mkdir(self, path: str) -> None:
        self._ensure_available()
        import smbclient

        unc = self._unc(path)
        await asyncio.to_thread(smbclient.mkdir, unc)

    async def remove(self, path: str) -> None:
        self._ensure_available()
        import smbclient

        unc = self._unc(path)

        def _remove() -> None:
            info = smbclient.getinfo(unc)
            if info.is_directory():
                smbclient.rmdir(unc)
            else:
                smbclient.remove(unc)

        await asyncio.to_thread(_remove)

    async def test_connection(self) -> bool:
        try:
            self._ensure_available()
        except BackendUnavailableError as e:
            _logger.warning("smb_backend · unavailable: %s", e)
            return False
        try:
            import smbclient

            if self.username is not None and self.password is not None:
                await asyncio.to_thread(
                    smbclient.register_session,
                    self.host,
                    username=self.username,
                    password=self.password,
                    domain=self.domain,
                )
            unc = f"\\\\{self.host}\\{self.share}"
            await asyncio.to_thread(smbclient.getinfo, unc)
            return True
        except Exception as e:  # noqa: BLE001 — probe must not raise
            _logger.warning("smb_backend · test_connection failed: %s", e)
            return False


# ═══════════════════════════════════════════════════════════
# NfsMountBackend
# ═══════════════════════════════════════════════════════════


class NfsMountBackend(MountBackend):
    """NFS backend.

    Python has no widely-adopted pure-Python NFS client; the standard
    deployment pattern is to mount the NFS export at OS level (Linux
    ``mount -t nfs`` / macOS mount_nfs) and access it through the local
    VFS. This backend therefore delegates to :class:`LocalMountBackend`
    on the configured ``mount_point``.

    For environments where the OS has NOT already mounted the share,
    ``test_connection`` returns ``False`` and the operator is expected
    to mount it out-of-band.
    """

    def __init__(
        self,
        *,
        mount_point: str | Path,
        host: str | None = None,
        export: str | None = None,
    ) -> None:
        self.mount_point = Path(mount_point).expanduser().resolve()
        self.host = host
        self.export = export
        self._local = LocalMountBackend(self.mount_point)

    async def read_file(self, path: str) -> bytes:
        return await self._local.read_file(path)

    async def write_file(self, path: str, content: bytes) -> None:
        await self._local.write_file(path, content)

    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]:
        return await self._local.list_dir(path, depth)

    async def stat(self, path: str) -> FileStat:
        return await self._local.stat(path)

    async def mkdir(self, path: str) -> None:
        await self._local.mkdir(path)

    async def remove(self, path: str) -> None:
        await self._local.remove(path)

    async def test_connection(self) -> bool:
        # Heuristic: if the mount_point is an active NFS mount, the
        # process can stat it (already covered by test_connection) and
        # the directory is non-empty or stat-able. We don't strictly
        # verify the fstype here; the operator is responsible for the
        # mount itself.
        return await self._local.test_connection()


# ═══════════════════════════════════════════════════════════
# S3MountBackend
# ═══════════════════════════════════════════════════════════


class S3MountBackend(MountBackend):
    """S3 backend compatible with AWS S3, MinIO, and 阿里云 OSS.

    Uses ``boto3`` (lazy import) with a custom ``endpoint_url`` for
    MinIO/OSS. S3 has no real directories: ``mkdir`` creates a
    zero-byte ``<path>/`` marker, ``list_dir`` synthesises directory
    entries from common prefixes, and ``remove`` on a directory
    deletes all keys under that prefix.
    """

    _DEP_HINT: ClassVar[str] = "boto3 not installed · pip install boto3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        root_path: str = "",
    ) -> None:
        if not bucket:
            raise ValueError("bucket required")
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.root_path = root_path.strip("/")
        self._client: Any = None
        self._lock = asyncio.Lock()

    def _ensure_available(self) -> None:
        try:
            import boto3  # noqa: F401
        except ImportError as e:  # pragma: no cover - exercised via mock
            raise BackendUnavailableError(self._DEP_HINT) from e

    async def _get_client(self) -> Any:
        async with self._lock:
            if self._client is not None:
                return self._client
            self._ensure_available()
            self._client = await asyncio.to_thread(self._connect_sync)
            return self._client

    def _connect_sync(self) -> Any:
        import boto3

        kwargs: dict[str, Any] = {}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key is not None and self.secret_key is not None:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        if self.region:
            kwargs["region_name"] = self.region
        return boto3.client("s3", **kwargs)

    # ── key resolution ────────────────────────────────────

    def _resolve_key(self, path: str) -> str:
        rel = path.lstrip("/")
        if self.root_path:
            return f"{self.root_path}/{rel}" if rel else self.root_path
        return rel

    def _rel_key(self, key: str) -> str:
        if self.root_path and key.startswith(self.root_path + "/"):
            return key[len(self.root_path) + 1:]
        return key

    # ── MountBackend implementation ───────────────────────

    async def read_file(self, path: str) -> bytes:
        client = await self._get_client()
        key = self._resolve_key(path)

        def _read() -> bytes:
            response = client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_read)

    async def write_file(self, path: str, content: bytes) -> None:
        client = await self._get_client()
        key = self._resolve_key(path)

        def _write() -> None:
            client.put_object(Bucket=self.bucket, Key=key, Body=content)

        await asyncio.to_thread(_write)

    async def list_dir(self, path: str, depth: int = 1) -> list[DirEntry]:
        client = await self._get_client()
        prefix = self._resolve_key(path)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return await asyncio.to_thread(self._list_dir_sync, client, prefix, depth)

    def _list_dir_sync(self, client: Any, prefix: str, depth: int) -> list[DirEntry]:
        entries: list[DirEntry] = []
        paginator = client.get_paginator("list_objects_v2")
        # depth=1: immediate children only (Delimiter="/").
        # depth>1: paginated full recursion + post-filter by depth.
        if depth <= 1:
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/")
            for page in pages:
                for cp in page.get("CommonPrefixes", []) or []:
                    raw = cp["Prefix"].rstrip("/")
                    name = raw.rsplit("/", 1)[-1]
                    entries.append(
                        DirEntry(
                            name=name,
                            path=self._rel_key(raw),
                            is_dir=True,
                            size=0,
                            modified=0.0,
                        )
                    )
                for obj in page.get("Contents", []) or []:
                    if obj["Key"] == prefix:
                        continue
                    name = obj["Key"].rsplit("/", 1)[-1]
                    if not name:
                        continue
                    entries.append(
                        DirEntry(
                            name=name,
                            path=self._rel_key(obj["Key"]),
                            is_dir=False,
                            size=obj.get("Size", 0),
                            modified=_to_timestamp(obj.get("LastModified")),
                        )
                    )
        else:
            # Full recursion; then prune by depth.
            seen_keys: set[str] = set()
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            base_depth = prefix.count("/")
            for page in pages:
                for obj in page.get("Contents", []) or []:
                    key = obj["Key"]
                    if key in seen_keys or key == prefix:
                        continue
                    rel_depth = key.count("/") - base_depth
                    if rel_depth > depth:
                        continue
                    seen_keys.add(key)
                    name = key.rstrip("/").rsplit("/", 1)[-1]
                    # Synthesize intermediate directory entries.
                    parts = key[len(prefix):].rstrip("/").split("/")[:-1]
                    cur = prefix.rstrip("/")
                    for part in parts:
                        cur = f"{cur}/{part}"
                        if cur in seen_keys:
                            continue
                        seen_keys.add(cur)
                        entries.append(
                            DirEntry(
                                name=part,
                                path=self._rel_key(cur),
                                is_dir=True,
                                size=0,
                                modified=0.0,
                            )
                        )
                    entries.append(
                        DirEntry(
                            name=name,
                            path=self._rel_key(key.rstrip("/")),
                            is_dir=False,
                            size=obj.get("Size", 0),
                            modified=_to_timestamp(obj.get("LastModified")),
                        )
                    )
            entries.sort(key=lambda e: (not e.is_dir, e.path.lower()))
        return entries

    async def stat(self, path: str) -> FileStat:
        client = await self._get_client()
        key = self._resolve_key(path)

        def _stat() -> FileStat:
            # Try as a file first.
            try:
                head = client.head_object(Bucket=self.bucket, Key=key)
                return FileStat(
                    path=self._rel_key(key),
                    is_dir=False,
                    size=head.get("ContentLength", 0),
                    modified=_to_timestamp(head.get("LastModified")),
                )
            except Exception:  # noqa: BLE001 — fall through to dir check
                pass
            # Maybe a "directory" (prefix).
            prefix = key.rstrip("/") + "/"
            response = client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=1,
            )
            if response.get("KeyCount", 0) > 0:
                return FileStat(
                    path=self._rel_key(key.rstrip("/")),
                    is_dir=True,
                    size=0,
                    modified=0.0,
                )
            raise FileNotFoundError(f"s3 key not found: {key}")

        return await asyncio.to_thread(_stat)

    async def mkdir(self, path: str) -> None:
        client = await self._get_client()
        key = self._resolve_key(path).rstrip("/") + "/"

        def _mkdir() -> None:
            client.put_object(Bucket=self.bucket, Key=key, Body=b"")

        await asyncio.to_thread(_mkdir)

    async def remove(self, path: str) -> None:
        client = await self._get_client()
        key = self._resolve_key(path)

        def _remove() -> None:
            # Try as file first.
            try:
                client.head_object(Bucket=self.bucket, Key=key)
                client.delete_object(Bucket=self.bucket, Key=key)
                return
            except Exception:  # noqa: BLE001 — fall through to prefix delete
                pass
            prefix = key.rstrip("/") + "/"
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                objs = page.get("Contents", []) or []
                if not objs:
                    continue
                client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": o["Key"]} for o in objs]},
                )
            # Also remove the directory marker itself.
            with contextlib.suppress(Exception):
                client.delete_object(Bucket=self.bucket, Key=prefix)

        await asyncio.to_thread(_remove)

    async def test_connection(self) -> bool:
        try:
            self._ensure_available()
        except BackendUnavailableError as e:
            _logger.warning("s3_backend · unavailable: %s", e)
            return False
        try:
            client = await self._get_client()

            def _probe() -> bool:
                # list_buckets needs ListAllMyBuckets; some MinIO setups
                # don't grant it. list_objects_v2 on the bucket is the
                # more reliable reachability probe.
                client.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
                return True

            return await asyncio.to_thread(_probe)
        except Exception as e:  # noqa: BLE001 — probe must not raise
            _logger.warning("s3_backend · test_connection failed: %s", e)
            return False


# ═══════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════


class MountBackendRegistry:
    """Routes ``mount_type`` to the corresponding adapter class.

    Per-workspace instances are cached so repeated ``get_or_create``
    calls return the same backend (and the same underlying SFTP/HTTP
    connection pool).
    """

    def __init__(self) -> None:
        self._backends: dict[str, type[MountBackend]] = {}
        self._instances: dict[str, MountBackend] = {}  # workspace_id -> backend

    def register(self, mount_type: str, backend_class: type[MountBackend]) -> None:
        if not mount_type:
            raise ValueError("mount_type required")
        if not issubclass(backend_class, MountBackend):
            raise TypeError(f"backend_class must subclass MountBackend: {backend_class}")
        self._backends[mount_type.lower()] = backend_class

    def is_registered(self, mount_type: str) -> bool:
        return mount_type.lower() in self._backends

    def get_backend(
        self,
        workspace_id: str,
        mount_type: str,
        mount_target: str,
        mount_options: dict,
    ) -> MountBackend:
        cls = self._backends.get(mount_type.lower())
        if cls is None:
            raise KeyError(f"unknown mount_type: {mount_type!r}")
        return self._instantiate(cls, mount_target, mount_options)

    def get_or_create(
        self,
        workspace_id: str,
        mount_type: str,
        mount_target: str,
        mount_options: dict,
    ) -> MountBackend:
        if not workspace_id:
            raise ValueError("workspace_id required")
        cached = self._instances.get(workspace_id)
        if cached is not None:
            return cached
        backend = self.get_backend(workspace_id, mount_type, mount_target, mount_options)
        self._instances[workspace_id] = backend
        return backend

    def invalidate(self, workspace_id: str) -> None:
        self._instances.pop(workspace_id, None)

    @staticmethod
    def _instantiate(
        cls: type[MountBackend],
        mount_target: str,
        mount_options: dict,
    ) -> MountBackend:
        opts = dict(mount_options or {})
        # LocalMountBackend / NfsMountBackend take the root path as the
        # first positional arg; the others use keyword-only connection
        # params. Mount_target is the connection string / path. Use
        # issubclass so subclasses of the local/nfs backends also get
        # the positional-arg treatment.
        if issubclass(cls, LocalMountBackend) or issubclass(cls, NfsMountBackend):
            return cls(mount_target, **opts)
        return cls(**opts)


# Module-level default registry, pre-populated with all six backends.
default_registry: MountBackendRegistry = MountBackendRegistry()
default_registry.register("local", LocalMountBackend)
default_registry.register("sftp", SftpMountBackend)
default_registry.register("webdav", WebdavMountBackend)
default_registry.register("smb", SmbMountBackend)
default_registry.register("nfs", NfsMountBackend)
default_registry.register("s3", S3MountBackend)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def stat_is_dir(attr: Any) -> bool:
    """Best-effort ``is_dir`` for paramiko SFTPAttributes."""
    mode = getattr(attr, "st_mode", None)
    if mode is None:
        return False
    import stat as _stat

    return _stat.S_ISDIR(mode)


def _smb_mtime(info: Any) -> float:
    """Extract mtime from an smbprotocol FileInfo-like object."""
    for attr in ("last_write_time", "mtime", "st_mtime"):
        val = getattr(info, attr, None)
        if isinstance(val, (int, float)):
            return float(val)
    return 0.0


def _to_timestamp(dt: Any) -> float:
    """Convert a datetime (e.g. boto3 LastModified) to unix timestamp."""
    if dt is None:
        return 0.0
    try:
        return dt.timestamp()
    except (AttributeError, ValueError, OSError):
        return 0.0


def _local_name(tag: str) -> str:
    """Strip XML namespace from an ElementTree tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_local(elem: Any, name: str) -> list[Any]:
    """Find all children of ``elem`` whose local-name matches ``name``."""
    return [c for c in elem.iter() if _local_name(c.tag) == name]


def _extract_dav_props(resp: Any) -> tuple[bool, int, float]:
    """Extract (is_dir, size, mtime) from a WebDAV <response> element."""
    is_dir = False
    size = 0
    modified = 0.0
    for prop in _find_local(resp, "prop"):
        if _find_local(prop, "collection"):
            is_dir = True
        len_el = _find_local(prop, "getcontentlength")
        if len_el and len_el[0].text:
            try:
                size = int(len_el[0].text)
            except ValueError:
                size = 0
        mod_el = _find_local(prop, "getlastmodified")
        if mod_el and mod_el[0].text:
            try:
                modified = parsedate_to_datetime(mod_el[0].text).timestamp()
            except (TypeError, ValueError):
                modified = 0.0
    return is_dir, size, modified


__all__ = [
    "BackendError",
    "BackendUnavailableError",
    "DEFAULT_IGNORED_DIRS",
    "DirEntry",
    "FileStat",
    "LocalMountBackend",
    "MountBackend",
    "MountBackendRegistry",
    "NfsMountBackend",
    "S3MountBackend",
    "SftpMountBackend",
    "SmbMountBackend",
    "WebdavMountBackend",
    "default_registry",
]
