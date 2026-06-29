import { describe, expect, test } from "vitest";

import { collaborationRosterFromThread } from "./thread-collaboration";

describe("thread collaboration recovery", () => {
  test("recovers a saved agent roster from thread metadata context", () => {
    expect(
      collaborationRosterFromThread(
        {
          context: {
            agent_roster: [
              {
                agent_id: "general",
                display_name: "General",
                role: "tl",
              },
              {
                agent_id: "local_codex_cli",
                display_name: "Codex CLI",
                avatar_url: "/avatar/codex.png",
                role: "member",
              },
            ],
          },
        },
        {},
        "general",
      ),
    ).toEqual([
      {
        agent_id: "general",
        avatar_url: null,
        display_name: "General",
        icon: null,
        name: "general",
        role: "tl",
      },
      {
        agent_id: "local_codex_cli",
        avatar_url: "/avatar/codex.png",
        display_name: "Codex CLI",
        icon: null,
        name: "local_codex_cli",
        role: "member",
      },
    ]);
  });

  test("falls back to task agent refs for older collaboration threads", () => {
    expect(
      collaborationRosterFromThread(
        {},
        {
          task_agent_refs: ["general", "coder", "coder", "local_claude_code"],
        },
        "general",
      ),
    ).toEqual([
      {
        agent_id: "general",
        display_name: "general",
        name: "general",
        role: "tl",
      },
      {
        agent_id: "coder",
        display_name: "coder",
        name: "coder",
        role: "member",
      },
      {
        agent_id: "local_claude_code",
        display_name: "local_claude_code",
        name: "local_claude_code",
        role: "member",
      },
    ]);
  });
});
