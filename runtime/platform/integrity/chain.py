"""Tamper-evident hash-chain seals for append-only records.

A seal makes a record *auditable*, not unreadable: anyone with DB access can
still edit a row, but the edit breaks the chain and `verify_chain` pinpoints
where. Each entry's seal covers its own content plus the previous entry's
seal, so any retroactive mutation (edit, delete, reorder, insert) is detected.

This is deliberately not a signature scheme: there is no secret here, so it
does not prove *who* sealed — it proves the *sequence is intact* since the
genesis entry. Pairing with a real signing key is a later concern; the chain
shape (genesis → prev) is designed so a signer can be slotted in by replacing
the digest input, not by restructuring the tables.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64


def canonical(payload: Any) -> str:
    """Stable serialization: sorted keys, no whitespace, UTF-8 safe."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def seal_step(
    prev_seal: str,
    *,
    scope: str,
    seq: int,
    record_id: str,
    payload: str,
    ts: str | float,
) -> str:
    """One link of the chain: digest(prev + everything that must not change).

    ``prev_seal`` must be the real previous seal (or :data:`GENESIS`). ``seq``
    and ``record_id`` are folded in so deleting a middle row, renumbering, or
    re-inserting with a new id all break verification, not just content edits.
    """
    if not prev_seal or len(prev_seal) != 64:
        raise ValueError("prev_seal must be a 64-char hex digest (or GENESIS)")
    material = "|".join(
        (
            prev_seal,
            str(scope),
            str(int(seq)),
            str(record_id),
            payload,
            str(ts),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_chain(
    rows: list[dict[str, Any]],
    *,
    scope: str,
) -> dict[str, Any]:
    """Recompute the chain over ordered rows and report the first break.

    Each row must carry: ``seq``, ``record_id``, ``payload`` (canonical string
    or JSON-serializable), ``ts``, ``prev_seal``, ``seal``. Rows must be in
    ascending ``seq`` order — the caller decides the sort, because the seq
    column name differs per store.

    The chain is anchored at the *first sealed row* (its ``prev_seal`` must be
    :data:`GENESIS`, whatever its seq) — sealing may start mid-history on a
    legacy table, and rows before that point were never guaranteed.
    """
    prev = GENESIS
    first = True
    for row in rows:
        seq = int(row["seq"])
        expected_prev = GENESIS if first else prev
        if str(row.get("prev_seal") or "") != expected_prev:
            return {
                "ok": False,
                "broken_seq": seq,
                "reason": "prev_seal mismatch (row deleted, reordered, or inserted)",
            }
        expected = seal_step(
            expected_prev,
            scope=scope,
            seq=seq,
            record_id=str(row.get("record_id") or ""),
            payload=str(row.get("payload") or ""),
            ts=row.get("ts", ""),
        )
        if str(row.get("seal") or "") != expected:
            return {
                "ok": False,
                "broken_seq": seq,
                "reason": "content mutated after sealing",
            }
        prev = str(row.get("seal"))
        first = False
    return {"ok": True, "broken_seq": None, "reason": None, "length": len(rows)}
