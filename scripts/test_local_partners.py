#!/usr/bin/env python3
"""
Test all local CLI partners for compatibility.

Quick smoke test to verify each supported CLI partner can be invoked
in non-interactive mode and returns a response.
"""

import subprocess
import sys
from pathlib import Path

# Add runtime to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime.execution.agents.local_partner_bridge import build_partner_argv


def test_cli_partner(partner_id: str, command: str, prompt: str = "echo hello") -> dict:
    """Test a CLI partner's non-interactive invocation."""
    result = {
        "partner_id": partner_id,
        "command": command,
        "installed": False,
        "works": False,
        "error": None,
        "output": None,
    }

    # Check if CLI is installed
    try:
        subprocess.run([command, "--version"], capture_output=True, timeout=5)
        result["installed"] = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result["error"] = "Not installed or --version not supported"
        return result

    # Build argv
    argv = build_partner_argv(partner_id, command, prompt)
    if not argv:
        result["error"] = "build_partner_argv returned None (unsupported)"
        return result

    # Try to run
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            result["works"] = True
            result["output"] = proc.stdout[:200]  # First 200 chars
        else:
            result["error"] = f"Exit {proc.returncode}: {proc.stderr[:200]}"
    except subprocess.TimeoutExpired:
        result["error"] = "Timed out (30s)"
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    """Test all supported CLI partners."""
    partners = [
        ("claude-code", "claude"),
        ("codex-cli", "codex"),
        ("opencode-cli", "opencode"),
        ("trae-cli", "trae-cli"),
        ("qoder-cli", "qodercli"),
        ("codebuddy-cli", "codebuddy"),
    ]

    print("Testing Local CLI Partners\n" + "=" * 60)

    results = []
    for partner_id, command in partners:
        print(f"\n{partner_id} ({command}):")
        result = test_cli_partner(partner_id, command)
        results.append(result)

        if not result["installed"]:
            print(f"  ❌ {result['error']}")
        elif result["works"]:
            print(f"  ✅ Working")
            if result["output"]:
                print(f"  Output: {result['output'][:80]}...")
        else:
            print(f"  ⚠️  Installed but failed: {result['error']}")

    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    installed = sum(1 for r in results if r["installed"])
    working = sum(1 for r in results if r["works"])
    print(f"  Installed: {installed}/{len(partners)}")
    print(f"  Working:   {working}/{len(partners)}")

    if working < installed:
        print("\n⚠️  Some installed CLIs are not working.")
        print("   Check error messages above for details.")
    elif working > 0:
        print("\n✅ All installed CLIs are working!")


if __name__ == "__main__":
    main()
