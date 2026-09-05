"""Engine-neutral artifact coordinates; content stays in scoped files."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    path: Path
    sha256: str
    size: int
    producer_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size": self.size,
            "producer_task_id": self.producer_task_id,
        }


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    inputs: tuple[ArtifactReference, ...]
    output_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class HandoffRecorder:
    """A host-installed durable writer, never a deserialized callback."""

    write: Callable[[dict[str, Any]], None] = field(repr=False)
