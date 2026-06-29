import { describe, expect, test } from "vitest";

import { coworkGroupToCollaborationRoster } from "./roster";
import type { CoworkGroupResponse } from "./types";

function group(ids: string[]): CoworkGroupResponse {
  return {
    thread_id: "thread-1",
    state: {
      mode: "cluster",
      event_count: ids.length,
      is_one_to_one: ids.length <= 1,
      roster: ids.map((id) => ({
        id,
        kind: "agent",
        role: "participant",
        joined_at_message: null,
        grant: { scope: "all" },
        muted: false,
        invited_by: "user",
      })),
    },
    blackboard: {},
    events: [],
    responders: ids,
  };
}

describe("cowork roster mapping", () => {
  test("keeps the current task agent as leader and enriches cowork members", () => {
    const roster = coworkGroupToCollaborationRoster(
      group(["general", "codex-cli"]),
      "general",
      [
        {
          name: "general",
          display_name: "Eve",
          avatar_url: "/api/agents/general/avatar",
        },
        { name: "codex-cli", display_name: "Codex CLI", icon: "C" },
      ],
    );

    expect(roster).toEqual([
      {
        agent_id: "general",
        name: "general",
        display_name: "Eve",
        avatar_url: "/api/agents/general/avatar",
        icon: null,
        role: "tl",
      },
      {
        agent_id: "codex-cli",
        name: "codex-cli",
        display_name: "Codex CLI",
        avatar_url: null,
        icon: "C",
        role: "member",
      },
    ]);
  });

  test("returns empty when the thread group has no agent members", () => {
    expect(
      coworkGroupToCollaborationRoster(
        { ...group([]), responders: [] },
        "general",
        [],
      ),
    ).toEqual([]);
  });
});
