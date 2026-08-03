"""Related-file prefetching for the ReAct loop.

Extracted from ``react_context.py``. Pure helper — no behaviour change.
"""

from __future__ import annotations

from typing import Any


def _prefetch_related_files(
    action: str | None,
    working_set: dict[str, Any],
) -> str | None:
    if not action:
        return None
    try:
        import re

        _path_match = re.search(r'["\']([^"\']+\.(?:py|ts|tsx|js|jsx|go|rs))["\']', action)
        if not _path_match:
            return None
        edited_path = _path_match.group(1)
        import os

        if not os.path.isfile(edited_path):
            return None
        with open(edited_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        _import_patterns = [
            r'(?:from|import)\s+["\'](\.{1,2}/[^"\']+)["\']',
            r'(?:from|import)\s+["\'](\./[^"\']+)["\']',
            r'(?:from|import)\s+["\'](\.\./[^"\']+)["\']',
        ]
        local_imports = set()
        for pat in _import_patterns:
            for m in re.finditer(pat, content):
                imp = m.group(1)
                for ext in ("", ".ts", ".tsx", ".js", ".py", "/index.ts", "/index.py"):
                    candidate = imp + ext
                    if os.path.isfile(candidate) and candidate not in working_set:
                        local_imports.add(candidate)
                        break
        if not local_imports:
            return None
        parts = []
        total = 0
        for fp in sorted(local_imports)[:3]:
            with open(fp, encoding="utf-8", errors="replace") as f:
                fc = f.read()
            if total + len(fc) > 3000:
                fc = fc[: (3000 - total)] + "\n...(截断)"
            parts.append(f"--- {fp} ---\n{fc}")
            total += len(fc)
            if total >= 3000:
                break
        return "\n\n".join(parts) if parts else None
    except (OSError, ValueError):
        return None
