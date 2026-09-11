"""Team model catalog and single-use invitation exchange, backed by SQLite."""

import hashlib
import hmac
import json
import secrets
import time

from fastapi import HTTPException

from .hotspot_store import HotspotStore


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class TeamStore(HotspotStore):
    def __init__(self, root):
        super().__init__(root)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS team_models(
                    id TEXT PRIMARY KEY, config TEXT NOT NULL,
                    version INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS team_access(
                    member TEXT PRIMARY KEY, code TEXT UNIQUE, redeemed INTEGER DEFAULT 0,
                    models TEXT NOT NULL, concurrency INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS team_exchanges(
                    code TEXT PRIMARY KEY, proof TEXT NOT NULL, nonce TEXT NOT NULL,
                    member TEXT NOT NULL);
            """)

    def models(self, *, private=False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM team_models ORDER BY id").fetchall()
        result = []
        for row in rows:
            entry = {
                **json.loads(row["config"]),
                "id": row["id"],
                "version": row["version"],
                "published": bool(row["published"]),
            }
            if not private:
                entry["has_key"] = bool(entry.pop("api_key", ""))
            result.append(entry)
        return result

    def model(self, model_id):
        entry = next((m for m in self.models(private=True) if m["id"] == model_id), None)
        if entry is None:
            raise HTTPException(404, "模型不存在")
        return entry

    def save_model(self, model_id, config):
        with self.connect() as db:
            db.execute(
                "INSERT INTO team_models VALUES(?,?,1,0) ON CONFLICT(id) DO UPDATE SET "
                "config=excluded.config, version=team_models.version+1, published=0",
                (model_id, json.dumps(config)),
            )

    def publish(self, model_id, version):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE team_models SET published=1 WHERE id=? AND version=?",
                (model_id, version),
            ).rowcount
        if not changed:
            raise HTTPException(409, "测试期间配置已修改，请重新测试发布")

    def pause(self, model_id):
        with self.connect() as db:
            db.execute(
                "UPDATE team_models SET published=0,version=version+1 WHERE id=?", (model_id,)
            )

    def invitation(self, label, hours, max_requests, models, concurrency):
        available = {m["id"] for m in self.models() if m["published"]}
        if not models or not set(models) <= available or not 1 <= concurrency <= 8:
            raise HTTPException(400, "请选择已发布模型，并发上限为 1–8")
        grant = self.invite(label, hours, max_requests)
        code = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute(
                "INSERT INTO team_access VALUES(?,?,0,?,?)",
                (grant["id"], digest(code), json.dumps(models), concurrency),
            )
        return {"id": grant["id"], "code": code}

    def exchange(self, code, exchange_key=""):
        token = secrets.token_urlsafe(40)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = db.execute(
                "SELECT * FROM team_exchanges WHERE code=?", (digest(code),)
            ).fetchone()
            if (
                receipt
                and exchange_key
                and hmac.compare_digest(receipt["proof"], digest(exchange_key))
            ):
                row = db.execute("SELECT * FROM grants WHERE id=?", (receipt["member"],)).fetchone()
                token = hmac.new(
                    exchange_key.encode(), receipt["nonce"].encode(), hashlib.sha256
                ).hexdigest()
                if (
                    row
                    and not row["revoked"]
                    and row["expires"] > time.time()
                    and hmac.compare_digest(row["digest"], digest(token))
                ):
                    return {"token": token, "member_id": row["id"], "label": row["label"]}
                raise HTTPException(401, "邀请已过期或撤销")
            row = db.execute(
                "SELECT g.*,a.redeemed FROM grants g JOIN team_access a ON a.member=g.id "
                "WHERE a.code=?",
                (digest(code),),
            ).fetchone()
            if not row or row["redeemed"] or row["revoked"] or row["expires"] <= time.time():
                raise HTTPException(401, "邀请已兑换、过期或撤销")
            if exchange_key:
                nonce = secrets.token_hex(32)
                token = hmac.new(exchange_key.encode(), nonce.encode(), hashlib.sha256).hexdigest()
                db.execute(
                    "INSERT INTO team_exchanges VALUES(?,?,?,?)",
                    (digest(code), digest(exchange_key), nonce, row["id"]),
                )
            db.execute("UPDATE grants SET digest=? WHERE id=?", (digest(token), row["id"]))
            db.execute("UPDATE team_access SET redeemed=1,code=NULL WHERE member=?", (row["id"],))
        return {"token": token, "member_id": row["id"], "label": row["label"]}

    def permitted_model(self, member, model_id):
        # One read transaction binds publication, ACL and upstream configuration
        # to the same version, even if an administrator edits the model.
        with self.connect() as db:
            row = db.execute(
                "SELECT m.config,m.version FROM team_models m JOIN team_access a ON a.member=? "
                "WHERE m.id=? AND m.published=1 AND a.redeemed=1 "
                "AND EXISTS(SELECT 1 FROM json_each(a.models) WHERE value=m.id)",
                (member, model_id),
            ).fetchone()
        if not row:
            raise HTTPException(403, "模型未发布或未授权")
        return {**json.loads(row["config"]), "id": model_id, "version": row["version"]}

    def access(self, member):
        with self.connect() as db:
            row = db.execute("SELECT * FROM team_access WHERE member=?", (member,)).fetchone()
        if not row or not row["redeemed"]:
            raise HTTPException(401, "请先兑换邀请")
        return json.loads(row["models"]), row["concurrency"]

    def catalog(self, member):
        allowed, _ = self.access(member)
        return [
            {"id": m["id"], "display_name": m["name"], "wire_api": m["wire_api"]}
            for m in self.models()
            if m["published"] and m["id"] in allowed
        ]

    def members(self):
        with self.connect() as db:
            access = {r["member"]: dict(r) for r in db.execute("SELECT * FROM team_access")}
        return [
            {
                **m,
                "redeemed": bool(access.get(m["id"], {}).get("redeemed")),
                "models": json.loads(access.get(m["id"], {}).get("models", "[]")),
                "concurrency": access.get(m["id"], {}).get("concurrency", 1),
            }
            for m in self.list()
        ]
