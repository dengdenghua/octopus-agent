from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.io import atomic_write_json


class BackupManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "1"
    created_at: str = ""
    octopus_version: str = "0.1.0"
    components: list[str] = Field(default_factory=list)
    total_bytes: int = 0
    total_files: int = 0


class BackupReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    output_path: str
    manifest: BackupManifest
    success: bool = True
    error: str = ""


class RestoreReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_path: str
    components_restored: list[str] = Field(default_factory=list)
    files_restored: int = 0
    success: bool = True
    error: str = ""


class BackupManager:
    COMPONENTS = {
        "journal": "events.jsonl",
        "kg": "knowledge_graph.json",
        "config": "config.yaml",
        "hot_cache": "hot_cache/",
        "skills": "skills/",
        "agents": "agents/",
    }

    def __init__(self, base_dir: str = "~/.octopus") -> None:
        self._base = Path(os.path.expanduser(base_dir))

    def backup(
        self,
        output: str | Path | None = None,
        components: list[str] | None = None,
    ) -> BackupReport:
        if output is None:
            ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            output = self._base / f"backup-{ts}.tar.gz"
        output = Path(os.path.expanduser(str(output)))
        output.parent.mkdir(parents=True, exist_ok=True)

        selected = components or list(self.COMPONENTS.keys())
        included_components: list[str] = []
        total_bytes = 0
        total_files = 0

        try:
            with tarfile.open(str(output), "w:gz") as tar:
                for comp_name in selected:
                    rel_path = self.COMPONENTS.get(comp_name)
                    if rel_path is None:
                        continue
                    abs_path = self._base / rel_path
                    if not abs_path.exists():
                        continue
                    included_components.append(comp_name)
                    if abs_path.is_file():
                        tar.add(str(abs_path), arcname=rel_path)
                        total_bytes += abs_path.stat().st_size
                        total_files += 1
                    elif abs_path.is_dir():
                        for f in abs_path.rglob("*"):
                            if f.is_file():
                                tar.add(str(f), arcname=str(f.relative_to(self._base)))
                                total_bytes += f.stat().st_size
                                total_files += 1

                manifest = BackupManifest(
                    created_at=datetime.now(UTC).isoformat(),
                    components=included_components,
                    total_bytes=total_bytes,
                    total_files=total_files,
                )
                manifest_data = manifest.model_dump_json(indent=2).encode("utf-8")
                info = tarfile.TarInfo(name="MANIFEST.json")
                info.size = len(manifest_data)
                tar.addfile(info, io.BytesIO(manifest_data))

            return BackupReport(
                output_path=str(output),
                manifest=manifest,
            )
        except Exception as exc:
            return BackupReport(
                output_path=str(output),
                manifest=BackupManifest(),
                success=False,
                error=str(exc),
            )

    def restore(
        self,
        input_path: str | Path,
        components: list[str] | None = None,
        overwrite: bool = False,
    ) -> RestoreReport:
        input_path = Path(os.path.expanduser(str(input_path)))
        if not input_path.exists():
            return RestoreReport(
                input_path=str(input_path),
                success=False,
                error=f"backup file not found: {input_path}",
            )

        selected = set(components or list(self.COMPONENTS.keys()))
        restored_components: list[str] = []
        files_restored = 0

        try:
            with tarfile.open(str(input_path), "r:gz") as tar:
                for member in tar.getmembers():
                    comp_name = self._component_from_path(member.name)
                    if comp_name is not None and comp_name not in selected:
                        continue
                    dest = self._base / member.name
                    if dest.exists() and not overwrite:
                        continue
                    if member.isdir():
                        dest.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(member) as src:
                            if src is not None:
                                dest.write_bytes(src.read())
                                files_restored += 1
                        if comp_name and comp_name not in restored_components:
                            restored_components.append(comp_name)

            return RestoreReport(
                input_path=str(input_path),
                components_restored=restored_components,
                files_restored=files_restored,
            )
        except Exception as exc:
            return RestoreReport(
                input_path=str(input_path),
                success=False,
                error=str(exc),
            )

    def export_json(
        self,
        output: str | Path,
        components: list[str] | None = None,
    ) -> Path:
        output = Path(os.path.expanduser(str(output)))
        output.parent.mkdir(parents=True, exist_ok=True)
        selected = components or list(self.COMPONENTS.keys())
        data: dict[str, Any] = {
            "exported_at": datetime.now(UTC).isoformat(),
            "octopus_version": "0.1.0",
        }

        for comp_name in selected:
            rel_path = self.COMPONENTS.get(comp_name)
            if rel_path is None:
                continue
            abs_path = self._base / rel_path
            if not abs_path.exists():
                continue
            if abs_path.is_file():
                try:
                    text = abs_path.read_text(encoding="utf-8")
                    if abs_path.suffix == ".json":
                        data[comp_name] = json.loads(text)
                    elif abs_path.suffix == ".jsonl":
                        data[comp_name] = [
                            json.loads(line) for line in text.strip().splitlines() if line.strip()
                        ]
                    else:
                        data[comp_name] = text
                except (OSError, json.JSONDecodeError):
                    data[comp_name] = f"<unreadable: {abs_path}>"
            elif abs_path.is_dir():
                file_list = sorted(
                    str(f.relative_to(self._base)) for f in abs_path.rglob("*") if f.is_file()
                )
                data[comp_name] = {"files": file_list, "count": len(file_list)}

        atomic_write_json(output, data)
        return output

    def _component_from_path(self, arcname: str) -> str | None:
        top = arcname.split("/", 1)[0] if "/" in arcname else arcname
        for comp_name, rel_path in self.COMPONENTS.items():
            if top == rel_path.rstrip("/"):
                return comp_name
        return None
