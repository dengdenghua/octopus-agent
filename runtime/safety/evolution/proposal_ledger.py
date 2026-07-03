from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("octopus.evolution.proposal_ledger")

_FILE_LOCK = threading.Lock()


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


@dataclass
class ProposalRecord:
    proposal_id: str
    kind: str
    description: str
    status: ProposalStatus
    proposer: str
    ts: str
    fitness_before: float | None = None
    fitness_after: float | None = None
    model: str | None = None
    cost_tokens: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    applied_ts: str | None = None
    rolled_back_ts: str | None = None
    rejection_reason: str | None = None


class ProposalLedger:
    def __init__(self, path: str | Path = "data/proposal_ledger.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: ProposalRecord) -> Path:
        line = json.dumps(asdict(record), ensure_ascii=False, default=str) + "\n"
        with _FILE_LOCK, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return self._path

    def propose(
        self,
        *,
        kind: str,
        description: str,
        proposer: str = "system",
        fitness_before: float | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProposalRecord:
        h = (
            __import__("hashlib")
            .sha256(f"{kind}:{description}:{datetime.now().isoformat()}".encode())
            .hexdigest()[:12]
        )
        record = ProposalRecord(
            proposal_id=h,
            kind=kind,
            description=description,
            status=ProposalStatus.PROPOSED,
            proposer=proposer,
            ts=datetime.now().isoformat(timespec="seconds"),
            fitness_before=fitness_before,
            model=model,
            metadata=metadata or {},
        )
        self.append(record)
        return record

    def accept(self, proposal_id: str) -> ProposalRecord | None:
        return self._update_status(
            proposal_id,
            ProposalStatus.ACCEPTED,
        )

    def reject(self, proposal_id: str, reason: str | None = None) -> ProposalRecord | None:
        record = self._update_status(
            proposal_id,
            ProposalStatus.REJECTED,
        )
        if record is not None and reason is not None:
            record.rejection_reason = reason
            self._rewrite_record(record)
        return record

    def mark_applied(
        self, proposal_id: str, fitness_after: float | None = None
    ) -> ProposalRecord | None:
        record = self._update_status(
            proposal_id,
            ProposalStatus.APPLIED,
        )
        if record is not None:
            record.applied_ts = datetime.now().isoformat(timespec="seconds")
            if fitness_after is not None:
                record.fitness_after = fitness_after
            self._rewrite_record(record)
        return record

    def mark_rolled_back(self, proposal_id: str) -> ProposalRecord | None:
        record = self._update_status(
            proposal_id,
            ProposalStatus.ROLLED_BACK,
        )
        if record is not None:
            record.rolled_back_ts = datetime.now().isoformat(timespec="seconds")
            self._rewrite_record(record)
        return record

    def query(
        self,
        *,
        status: ProposalStatus | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[ProposalRecord]:
        records = self._read_all()
        if status is not None:
            records = [r for r in records if r.status == status]
        if kind is not None:
            records = [r for r in records if r.kind == kind]
        return records[-limit:]

    def stats(self) -> dict[str, Any]:
        records = self._read_all()
        by_status: dict[str, int] = {}
        total_cost_usd = 0.0
        total_tokens = 0
        for r in records:
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
            total_cost_usd += r.cost_usd
            total_tokens += r.cost_tokens
        return {
            "total": len(records),
            "by_status": by_status,
            "total_cost_usd": round(total_cost_usd, 4),
            "total_tokens": total_tokens,
        }

    def _read_all(self) -> list[ProposalRecord]:
        if not self._path.exists():
            return []
        records: list[ProposalRecord] = []
        with _FILE_LOCK, self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    records.append(
                        ProposalRecord(
                            proposal_id=str(d.get("proposal_id", "")),
                            kind=str(d.get("kind", "")),
                            description=str(d.get("description", "")),
                            status=ProposalStatus(d.get("status", "proposed")),
                            proposer=str(d.get("proposer", "system")),
                            ts=str(d.get("ts", "")),
                            fitness_before=d.get("fitness_before"),
                            fitness_after=d.get("fitness_after"),
                            model=d.get("model"),
                            cost_tokens=int(d.get("cost_tokens", 0) or 0),
                            cost_usd=float(d.get("cost_usd", 0.0) or 0.0),
                            metadata=d.get("metadata") or {},
                            applied_ts=d.get("applied_ts"),
                            rolled_back_ts=d.get("rolled_back_ts"),
                            rejection_reason=d.get("rejection_reason"),
                        )
                    )
                except Exception as _exc:
                    _LOG.debug("proposal ledger parse failed: %s", _exc)
                    continue
        return records

    def _update_status(
        self,
        proposal_id: str,
        new_status: ProposalStatus,
    ) -> ProposalRecord | None:
        records = self._read_all()
        for r in records:
            if r.proposal_id == proposal_id:
                r.status = new_status
                self._rewrite_record(r)
                return r
        return None

    def _rewrite_record(self, record: ProposalRecord) -> None:
        target_id = record.proposal_id
        lines: list[str] = []
        with _FILE_LOCK:
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line_stripped = line.strip()
                        if not line_stripped:
                            continue
                        try:
                            d = json.loads(line_stripped)
                            if d.get("proposal_id") == target_id:
                                lines.append(
                                    json.dumps(asdict(record), ensure_ascii=False, default=str)
                                    + "\n"
                                )
                            else:
                                lines.append(line)
                        except json.JSONDecodeError:
                            lines.append(line)
            with self._path.open("w", encoding="utf-8") as fh:
                fh.writelines(lines)


__all__ = [
    "ProposalLedger",
    "ProposalRecord",
    "ProposalStatus",
]
