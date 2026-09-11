"""Durable, atomic invitation budgets; no upstream credentials in this store."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException


class HotspotStore:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "hotspot.db"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS task_engines(member TEXT PRIMARY KEY, engine TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value INTEGER);
                INSERT OR IGNORE INTO settings VALUES('enabled',0);
                CREATE TABLE IF NOT EXISTS grants(
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
                    expires REAL NOT NULL, max_requests INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0,
                    revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS calls(
                    id TEXT PRIMARY KEY, member TEXT, mode TEXT, status TEXT,
                    started REAL, finished REAL, input_tokens INTEGER, output_tokens INTEGER);
                CREATE TABLE IF NOT EXISTS model_receipts(
                    member TEXT NOT NULL, request_key TEXT NOT NULL, body_digest TEXT NOT NULL,
                    PRIMARY KEY(member, request_key));
            """)

    def task_engine(self, member):
        with self.connect() as db:
            row = db.execute("SELECT engine FROM task_engines WHERE member=?", (member,)).fetchone()
            return row[0] if row else "codex"

    def set_task_engine(self, member, engine):
        if engine not in {"codex", "opencode"}:
            raise ValueError("unsupported task engine")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO task_engines VALUES(?,?)", (member, engine))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enabled(self):
        with self.connect() as db:
            return bool(db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()[0])

    def set_enabled(self, value: bool):
        with self.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='enabled'", (int(value),))

    def invite(self, label: str, hours: int = 8, max_requests: int = 100):
        if (
            not label.strip()
            or len(label) > 80
            or not 1 <= hours <= 168
            or not 1 <= max_requests <= 10000
        ):
            raise HTTPException(400, "名称、有效期或调用上限无效")
        token = secrets.token_urlsafe(40)
        grant_id = secrets.token_hex(12)
        with self.connect() as db:
            db.execute(
                "INSERT INTO grants(id,label,digest,expires,max_requests) VALUES(?,?,?,?,?)",
                (
                    grant_id,
                    label.strip(),
                    hashlib.sha256(token.encode()).hexdigest(),
                    time.time() + hours * 3600,
                    max_requests,
                ),
            )
        return {"id": grant_id, "token": token}

    def authorize(
        self, token: str, *, reserve: bool = False, request_key: str = "", body_digest: str = ""
    ):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()[0]:
                raise HTTPException(503, "热点已关闭")
            grant = db.execute(
                "SELECT * FROM grants WHERE digest=?", (hashlib.sha256(token.encode()).hexdigest(),)
            ).fetchone()
            if grant is None or grant["revoked"] or grant["expires"] <= time.time():
                raise HTTPException(401, "邀请无效、已撤销或已过期")
            if request_key and reserve:
                receipt = db.execute(
                    "SELECT body_digest FROM model_receipts WHERE member=? AND request_key=?",
                    (grant["id"], request_key),
                ).fetchone()
                if receipt:
                    detail = "此请求已接收，不会再次执行；请检查首次请求结果"
                    if receipt["body_digest"] != body_digest:
                        detail = "同一请求标识不能用于不同内容"
                    raise HTTPException(409, detail)
            if reserve and grant["used"] >= grant["max_requests"]:
                raise HTTPException(429, "此邀请的调用次数已用完")
            if reserve:
                db.execute("UPDATE grants SET used=used+1 WHERE id=?", (grant["id"],))
                if request_key:
                    db.execute(
                        "INSERT INTO model_receipts VALUES(?,?,?)",
                        (grant["id"], request_key, body_digest),
                    )
            return dict(grant)

    def active(self, grant_id: str):
        with self.connect() as db:
            grant = db.execute(
                "SELECT revoked,expires FROM grants WHERE id=?", (grant_id,)
            ).fetchone()
        return (
            self.enabled()
            and grant is not None
            and not grant["revoked"]
            and grant["expires"] > time.time()
        )

    def revoke(self, grant_id: str):
        with self.connect() as db:
            db.execute("UPDATE grants SET revoked=1 WHERE id=?", (grant_id,))

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,label,expires,max_requests,used,revoked FROM grants ORDER BY expires DESC"
                )
            ]

    def audit(self, call_id: str, member: str, mode: str, status: str, usage=None):
        usage = usage if isinstance(usage, dict) else {}
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO calls(id,member,mode,status,started) VALUES(?,?,?,?,?)",
                (call_id, member, mode, status, time.time()),
            )
            db.execute(
                "UPDATE calls SET status=?,finished=?,input_tokens=?,output_tokens=? WHERE id=?",
                (
                    status,
                    None if status == "running" else time.time(),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    call_id,
                ),
            )

    def usage(self):
        with self.connect() as db:
            return [
                dict(r) for r in db.execute("SELECT * FROM calls ORDER BY started DESC LIMIT 100")
            ]
