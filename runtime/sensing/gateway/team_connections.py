"""Durable receiving-side team connections; secrets never need a browser roundtrip."""

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager

import httpx
from fastapi import HTTPException

from .hotspot_discovery import normalize_hotspot_url


class TeamConnections:
    def __init__(self, path, apply_catalog, *, transport=None):
        self.path = path
        self.apply_catalog = apply_catalog
        self.transport = transport
        self.locks = {}
        self.worker = None

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS connections("
                    "id TEXT PRIMARY KEY, invite_hash TEXT UNIQUE, base_url TEXT, code TEXT, "
                    "exchange_key TEXT, token TEXT, models TEXT, error TEXT, updated REAL)"
                )
                yield db
        finally:
            db.close()

    def rows(self, *, private=False):
        if not self.path.exists():
            return []
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM connections ORDER BY rowid")]
        if private:
            return rows
        return [
            {
                "id": row["id"],
                "base_url": row["base_url"],
                "models": json.loads(row["models"]),
                "error": row["error"],
                "updated": row["updated"],
                "connected": bool(row["token"]),
            }
            for row in rows
        ]

    def start(self, base_url, code):
        base = normalize_hotspot_url(base_url)
        if not isinstance(code, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{20,200}", code):
            raise HTTPException(400, "兑换码格式无效")
        invite_hash = hashlib.sha256((base + "\0" + code).encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO connections VALUES(?,?,?,?,?,?,?, ?,?)",
                (
                    uuid.uuid4().hex,
                    invite_hash,
                    base,
                    code,
                    secrets.token_urlsafe(32),
                    "",
                    "[]",
                    "",
                    0,
                ),
            )
            return db.execute(
                "SELECT id FROM connections WHERE invite_hash=?", (invite_hash,)
            ).fetchone()[0]

    async def remote(self, method, url, **kwargs):
        async with asyncio.timeout(35):
            async with httpx.AsyncClient(
                timeout=30, trust_env=False, transport=self.transport
            ) as client:
                async with client.stream(method, url, **kwargs) as response:
                    if response.status_code != 200:
                        raise HTTPException(response.status_code, "团队网关请求失败")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 1024 * 1024:
                            raise ValueError("response too large")
        return json.loads(data)

    @staticmethod
    def catalog(payload):
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("data"), list)
            or len(payload["data"]) > 100
        ):
            raise ValueError("invalid catalog")
        models = []
        ids = set()
        for row in payload["data"]:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", row["id"])
            ):
                raise ValueError("invalid model id")
            if row.get("wire_api") not in {"responses", "chat_completions"} or row["id"] in ids:
                raise ValueError("invalid model protocol or duplicate id")
            ids.add(row["id"])
            models.append(
                {
                    "id": row["id"],
                    "display_name": str(row.get("display_name") or row["id"])[:100],
                    "wire_api": row["wire_api"],
                }
            )
        return models

    async def sync(self, connection_id):
        async with self.locks.setdefault(connection_id, asyncio.Lock()):
            connection = next(
                (r for r in self.rows(private=True) if r["id"] == connection_id), None
            )
            if not connection:
                raise HTTPException(404, "团队连接不存在")
            try:
                if not connection["token"]:
                    result = await self.remote(
                        "POST",
                        connection["base_url"].removesuffix("/v1") + "/join",
                        json={
                            "code": connection["code"],
                            "exchange_key": connection["exchange_key"],
                        },
                    )
                    token = result.get("token") if isinstance(result, dict) else None
                    if (
                        not isinstance(token, str)
                        or not 20 <= len(token) <= 4096
                        or any(not 33 <= ord(c) <= 126 for c in token)
                    ):
                        raise ValueError("invalid credential")
                    # Commit the credential before fetching the catalog or building routes.
                    with self.connect() as db:
                        db.execute(
                            "UPDATE connections SET token=?,code='',exchange_key='' WHERE id=?",
                            (token, connection_id),
                        )
                    connection["token"] = token
                result = await self.remote(
                    "GET",
                    connection["base_url"] + "/models",
                    headers={"Authorization": "Bearer " + connection["token"]},
                )
                models = self.catalog(result)
                self.apply_catalog(connection, models)
                with self.connect() as db:
                    db.execute(
                        "UPDATE connections SET models=?,error=?,updated=? WHERE id=?",
                        (json.dumps(models), "", time.time(), connection_id),
                    )
            except (httpx.HTTPError, HTTPException, ValueError, TimeoutError, OSError):
                # An unavailable or unauthorized catalog must not remain selectable.
                self.apply_catalog(connection, [])
                with self.connect() as db:
                    db.execute(
                        "UPDATE connections SET models=?,error=?,updated=? WHERE id=?",
                        (
                            "[]",
                            "目录同步失败：请检查网关状态或成员授权，然后重试同步。",
                            time.time(),
                            connection_id,
                        ),
                    )
            return next(r for r in self.rows() if r["id"] == connection_id)

    async def disconnect(self, connection_id):
        async with self.locks.setdefault(connection_id, asyncio.Lock()):
            connection = next(
                (r for r in self.rows(private=True) if r["id"] == connection_id), None
            )
            if connection:
                self.apply_catalog(connection, [])
                with self.connect() as db:
                    db.execute("DELETE FROM connections WHERE id=?", (connection_id,))
        return {"ok": True}

    async def sync_all(self):
        for row in self.rows():
            await self.sync(row["id"])

    async def start_worker(self):
        async def work():
            while True:
                # Keep the next refresh alive if an unrelated route rebuild failed.
                with contextlib.suppress(Exception):
                    await self.sync_all()
                await asyncio.sleep(60)

        self.worker = asyncio.create_task(work())

    async def stop_worker(self):
        if self.worker:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker
