from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True


def _load_module(workspace: Path):
    spec = importlib.util.spec_from_file_location(
        "candidate_file_service", workspace / "file_service.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load file_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(workspace: Path) -> dict[str, object]:
    module = _load_module(workspace)
    service_type = module.FileService
    if list(inspect.signature(service_type.read_text).parameters) != ["self", "user_path"]:
        raise AssertionError("FileService.read_text public signature changed")
    with tempfile.TemporaryDirectory(prefix="path-verifier-", dir=workspace) as temp_dir:
        state_root = Path(temp_dir)
        root = state_root / "sandbox"
        root.mkdir()
        nested = root / "nested"
        nested.mkdir()
        (nested / "valid.txt").write_text("valid", encoding="utf-8")
        outside = state_root / "outside-secret.txt"
        outside.write_text("secret", encoding="utf-8")
        symlink = root / "outside-link.txt"
        symlink.symlink_to(outside)
        service = service_type(root)
        if service.read_text("nested/valid.txt") != "valid":
            raise AssertionError("valid nested path no longer works")
        checks = ["valid nested path preserved"]
        attacks = [
            "../outside-secret.txt",
            "%2e%2e/outside-secret.txt",
            "%252e%252e%252foutside-secret.txt",
            "outside-link.txt",
        ]
        for attack in attacks:
            try:
                service.read_text(attack)
            except module.PathBoundaryError:
                continue
            except (FileNotFoundError, OSError) as exc:
                raise AssertionError(
                    f"attack {attack!r} was not rejected as PathBoundaryError: {exc}"
                ) from exc
            raise AssertionError(f"attack {attack!r} escaped the root")
    checks.extend(
        ["plain traversal rejected", "encoded traversal rejected", "symlink escape rejected"]
    )
    test_files = [path for path in (workspace / "tests").glob("test_*.py") if path.is_file()]
    if not test_files:
        raise AssertionError("focused regression tests were not added")
    checks.append("regression tests added")
    return {"passed": True, "score": 1.0, "reason": "all path outcomes pass", "checks": checks}


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    try:
        result = _run(workspace)
    except Exception as exc:
        result = {"passed": False, "score": 0.0, "reason": str(exc), "checks": []}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
