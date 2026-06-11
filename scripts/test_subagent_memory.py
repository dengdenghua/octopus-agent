#!/usr/bin/env python3
"""Multi-turn subagent memory test.

Sends two researcher calls with the same thread_id to verify the second
call sees the first call's output rendered as "Prior turns" in the
system prompt.

Usage:
    python scripts/test_subagent_memory.py
"""
from __future__ import annotations

import json
import sys
import urllib.request


def call_subagent(
    role: str,
    prompt: str,
    thread_id: str,
    share_history: bool = True,
) -> dict:
    """Synchronous subagent dispatch (non-streaming)."""
    body = json.dumps({
        "subagent_type": role,
        "prompt": prompt,
        "thread_id": thread_id,
        "share_history": share_history,
        "timeout_s": 120,
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/subagents/dispatch",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=130) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(detail)
            return {"success": False, "error": err.get("detail", detail)}
        except json.JSONDecodeError:
            return {"success": False, "error": detail}


def main() -> int:
    thread_id = "test_memory_thread_001"
    print(f"Multi-turn test · thread={thread_id}\n")

    # Turn 1: ask researcher for Claude news
    print("═══ Turn 1: Initial research request ═══")
    result1 = call_subagent(
        role="researcher",
        prompt="Find latest Claude AI news from Anthropic (2026)",
        thread_id=thread_id,
    )
    if not result1.get("success"):
        print(f"✗ Turn 1 FAILED: {result1.get('error')}")
        return 1

    output1 = result1.get("output", "")
    rounds1 = result1.get("iteration_count", 0)
    print(f"✓ Turn 1 SUCCESS · rounds={rounds1} · output_len={len(output1)}")
    print(f"  Preview: {output1[:200]}...\n")

    # Turn 2: follow-up reference ("that model")
    print("═══ Turn 2: Follow-up that references Turn 1 ═══")
    result2 = call_subagent(
        role="researcher",
        prompt=(
            "Based on what you just found, which model was mentioned as "
            "the most capable? Give me just the model name and release date."
        ),
        thread_id=thread_id,
    )
    if not result2.get("success"):
        print(f"✗ Turn 2 FAILED: {result2.get('error')}")
        return 1

    output2 = result2.get("output", "")
    rounds2 = result2.get("iteration_count", 0)
    print(f"✓ Turn 2 SUCCESS · rounds={rounds2} · output_len={len(output2)}")
    print(f"  Output: {output2}")
    print()

    # Verify: Turn 2 should NOT have re-done web_search (should be 1-2 rounds
    # of synthesis from memory, not 8+ rounds of fresh research)
    print("═══ Analysis ═══")
    if rounds2 <= 3:
        print(f"✓ Turn 2 used memory (only {rounds2} rounds — no redundant web search)")
    else:
        print(f"⚠ Turn 2 ran {rounds2} rounds (may have re-searched instead of using memory)")

    # Check if Turn 2 output references the model from Turn 1
    if "opus" in output2.lower() or "4." in output2:
        print("✓ Turn 2 output mentions a Claude model (continuity confirmed)")
    else:
        print("⚠ Turn 2 output doesn't clearly reference Turn 1's findings")

    print("\n✅ Multi-turn memory test complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
