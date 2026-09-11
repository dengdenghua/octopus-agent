"""Measure public host imports in fresh processes, without starting services.

This is an import-boundary probe, not an application startup benchmark.
"""

from __future__ import annotations

import argparse
import importlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "runtime.platform.config.schema",
    "runtime.execution.request",
    "runtime.execution.opencode_backend",
    "runtime.sensing.gateway.realtime_opencode_backend",
)


def working_set_bytes() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working_set",
                "paged_peak",
                "paged",
                "nonpaged_peak",
                "nonpaged",
                "pagefile",
                "pagefile_peak",
            )
        ]

    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = wintypes.HANDLE
    measure = ctypes.windll.psapi.GetProcessMemoryInfo
    measure.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    measure.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not measure(current(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.working_set


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", choices=TARGETS)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.probe:
        sys.path.insert(0, str(ROOT))
        started = time.perf_counter()
        importlib.import_module(args.probe)
        elapsed = time.perf_counter() - started
        modules = len(sys.modules)
        print(
            json.dumps(
                {
                    "seconds": elapsed,
                    "modules": modules,
                    "native_planner_loaded": "runtime.core.cerebrum.llm_planner" in sys.modules,
                    "working_set_bytes": working_set_bytes(),
                }
            )
        )
        return
    if args.samples < 1:
        parser.error("--samples must be positive")
    report = {
        "python": sys.version,
        "platform": sys.platform,
        "samples": args.samples,
        "targets": {},
    }
    for target in TARGETS:
        samples = []
        for _ in range(args.samples):
            process = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--probe", target],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            samples.append(json.loads(process.stdout))
        report["targets"][target] = {
            "median_seconds": statistics.median(row["seconds"] for row in samples),
            "samples": samples,
        }
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
