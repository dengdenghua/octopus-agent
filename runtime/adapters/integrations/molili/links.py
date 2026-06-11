
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime.platform.io import atomic_write_json

logger = logging.getLogger(__name__)

_STORE_FILENAME = "molili_links.json"


def _default_store_path() -> Path:
    project_root = Path(__file__).resolve().parents[4]  # Implementation note.
    data_dir = os.environ.get("OCTOPUS_DATA_DIR")
    if data_dir:
        base = Path(data_dir)
        base.mkdir(parents=True, exist_ok=True)
        return base / _STORE_FILENAME
    home_dir = os.environ.get("OCTOPUS_HOME")
    if home_dir:
        base = Path(home_dir)
        base.mkdir(parents=True, exist_ok=True)
        return base / _STORE_FILENAME
    base = project_root / ".octopus"
    base.mkdir(parents=True, exist_ok=True)
    return base / _STORE_FILENAME


@dataclass
class MoliliLink:

    octopus_user_id: str
    molili_user_id: str
    molili_token: str
    mobile: str | None = None
    linked_at: float = 0.0
    last_synced_at: float | None = None
    credits_snapshot: dict[str, Any] = field(default_factory=dict)
    token_invalid: bool = False
    token_invalid_reason: str | None = None


class MoliliLinkStore:

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else _default_store_path()
        self._lock = threading.Lock()
        self._cache: dict[str, MoliliLink] | None = None


    def _load(self) -> dict[str, MoliliLink]:
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            self._cache = {}
            return self._cache
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("molili link store unreadable (%s) · starting empty", exc)
            self._cache = {}
            return self._cache
        cache: dict[str, MoliliLink] = {}
        for key, blob in (raw or {}).items():
            try:
                cache[key] = MoliliLink(**blob)
            except Exception:  # noqa: BLE001
                logger.warning("molili link for %s malformed · dropping", key)
        self._cache = cache
        return cache

    def _flush(self) -> None:
        assert self._cache is not None
        payload = {k: asdict(v) for k, v in self._cache.items()}
        atomic_write_json(self._path, payload)


    def get(self, octopus_user_id: str) -> MoliliLink | None:
        with self._lock:
            return self._load().get(octopus_user_id)

    def put(self, link: MoliliLink) -> None:
        with self._lock:
            cache = self._load()
            cache[link.octopus_user_id] = link
            self._flush()

    def delete(self, octopus_user_id: str) -> bool:
        with self._lock:
            cache = self._load()
            if octopus_user_id not in cache:
                return False
            cache.pop(octopus_user_id)
            self._flush()
            return True

    def update_credits(
        self,
        octopus_user_id: str,
        credits: dict[str, Any],
        *,
        now: float,
    ) -> MoliliLink | None:
        with self._lock:
            cache = self._load()
            link = cache.get(octopus_user_id)
            if link is None:
                return None
            link.credits_snapshot = credits
            link.last_synced_at = now
            link.token_invalid = False
            link.token_invalid_reason = None
            self._flush()
            return link

    def mark_token_invalid(
        self, octopus_user_id: str, reason: str | None,
    ) -> MoliliLink | None:
        with self._lock:
            cache = self._load()
            link = cache.get(octopus_user_id)
            if link is None:
                return None
            link.token_invalid = True
            link.token_invalid_reason = reason
            self._flush()
            return link

    def all_actor_ids(self) -> list[str]:
        with self._lock:
            return list(self._load().keys())
