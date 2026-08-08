"""Auto-demote low-precision guards to advisory mode.

Reads guard precision from telemetry and automatically marks noisy guards
as "advisory" (record but don't block). This prevents false positives from
blocking valid work while keeping telemetry for future tuning.

Usage::

    # Dry run (show what would change)
    python -m runtime.safety.evolution.guard_auto_demote --dry-run

    # Apply changes
    python -m runtime.safety.evolution.guard_auto_demote

    # Custom precision threshold
    python -m runtime.safety.evolution.guard_auto_demote --min-precision 0.6

Strategy::

    1. Calculate precision for each guard from verdicts
    2. Guards with precision < threshold → mark as advisory
    3. Guards with no verdicts but high hits → warn (need judging)
    4. Output: environment variable for OCTOPUS_DISABLED_GUARDS

This is the data-driven alternative to hardcoded _ADVISORY_GUARD_LABELS.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runtime.safety.evolution.guard_telemetry import GuardTelemetry


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="guard_auto_demote",
        description="Auto-demote low-precision guards to advisory mode.",
    )
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=None,
        help="Path to guard telemetry file (default: auto-detect).",
    )
    parser.add_argument(
        "--min-precision",
        type=float,
        default=0.5,
        help="Precision threshold (default 0.5). Guards below this are demoted.",
    )
    parser.add_argument(
        "--min-verdicts",
        type=int,
        default=10,
        help="Min verdicts required to calculate precision (default 10).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without applying.",
    )
    parser.add_argument(
        "--output-env",
        type=Path,
        default=None,
        help="Write OCTOPUS_DISABLED_GUARDS to this file (default: stdout).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Auto-detect telemetry path
    telemetry_path = args.telemetry
    if telemetry_path is None:
        from runtime.core.cerebrum.react_loop_controls import _guard_hit_recorder

        _ = _guard_hit_recorder()
        from runtime.core.cerebrum.react_loop_controls import _GUARD_TELEMETRY_SINGLETON

        if _GUARD_TELEMETRY_SINGLETON is None:
            print("ERROR: Guard telemetry not available", file=sys.stderr)
            return 1
        telemetry_path = _GUARD_TELEMETRY_SINGLETON.path

    telemetry = GuardTelemetry(path=telemetry_path)
    digest = telemetry.digest(min_precision_for_tuning=args.min_precision)

    label_precision = digest["label_precision"]

    # Categorize guards
    noisy_guards = []  # precision < threshold, enough verdicts
    needs_judging = []  # no precision, high hits
    healthy_guards = []  # precision >= threshold

    for label, data in label_precision.items():
        prec = data["precision"]
        graded = data["tp"] + data["fp"]  # Exclude uncertain

        if prec is None:
            # No graded verdicts yet
            if data["unjudged"] >= 20:
                needs_judging.append((label, data["unjudged"]))
        elif graded >= args.min_verdicts:
            # Enough verdicts to calculate reliable precision
            if prec < args.min_precision:
                noisy_guards.append((label, prec, data["tp"], data["fp"]))
            else:
                healthy_guards.append((label, prec))
        # Else: too few verdicts, skip

    # Report
    print("=" * 80)
    print("GUARD AUTO-DEMOTE ANALYSIS")
    print("=" * 80)
    print(f"Precision threshold: {args.min_precision:.0%}")
    print(f"Min verdicts required: {args.min_verdicts}")
    print(f"Total hits: {digest['total_hits']}")
    print(f"Judged: {digest['judged_total']}")
    print()

    if noisy_guards:
        print(f"NOISY GUARDS ({len(noisy_guards)}) — precision < {args.min_precision:.0%}")
        print("-" * 80)
        for label, prec, tp, fp in sorted(noisy_guards, key=lambda x: x[1]):
            print(f"  {label:45s} {prec:5.1%}  (tp={tp}, fp={fp})")
        print()
    else:
        print("✓ No noisy guards found (all guards above threshold)")
        print()

    if needs_judging:
        print(f"NEEDS JUDGING ({len(needs_judging)}) — high hits, no verdicts")
        print("-" * 80)
        for label, unjudged in sorted(needs_judging, key=lambda x: -x[1])[:10]:
            print(f"  {label:45s} {unjudged} unjudged hits")
        if len(needs_judging) > 10:
            print(f"  ... and {len(needs_judging) - 10} more")
        print()
        print("Run: python -m runtime.safety.evolution.run_batch_cron --max-hits 100")
        print()

    if healthy_guards:
        print(f"HEALTHY GUARDS ({len(healthy_guards)}) — precision ≥ {args.min_precision:.0%}")
        print("-" * 80)
        for label, prec in sorted(healthy_guards, key=lambda x: -x[1])[:5]:
            print(f"  {label:45s} {prec:5.1%}")
        if len(healthy_guards) > 5:
            print(f"  ... and {len(healthy_guards) - 5} more")
        print()

    # Generate disable list
    if noisy_guards:
        disable_list = ",".join(label for label, _, _, _ in noisy_guards)
        env_line = f'export OCTOPUS_DISABLED_GUARDS="{disable_list}"'

        print("=" * 80)
        if args.dry_run:
            print("DRY RUN — would generate:")
        else:
            print("RECOMMENDED ACTION:")
        print("-" * 80)
        print(env_line)
        print()

        if args.output_env and not args.dry_run:
            args.output_env.write_text(env_line + "\n")
            print(f"✓ Written to {args.output_env}")
            print()
            print("To apply:")
            print(f"  source {args.output_env}")
            print("  # Then restart octopus-agent")
        elif not args.dry_run:
            print("To apply:")
            print("  1. Copy the export line above")
            print("  2. Add to your shell profile or .env")
            print("  3. Restart octopus-agent")

        print()
        print("=" * 80)
        return 0

    print("=" * 80)
    print("✓ No action needed — all guards are healthy or need more data")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
