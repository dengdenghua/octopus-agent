import { describe, expect, test } from "vitest";

import {
  coworkGroupToCollaborationRoster,
  coworkSessionToCollaborationRoster,
} from "./roster";
import type { CollaborationSession, CoworkGroupResponse } from "./types";

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

function session(ids: string[]): CollaborationSession {
  return {
    session_id: "thread-1",
    room_id: null,
    mode: "cluster",
    roster: group(ids).state.roster,
    blackboard: {},
    tasks: [],
    presence: [],
    room_messages: [],
    room_participants: [],
    room_tasks: [],
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
        // AI-side members now carry the identity axes (数字员工 vs bare AI,
        // 托管 vs 接管); bare agents fold to the defaults.
        kind: "agent",
        driver: "ai",
        accountable_owner: "",
      },
      {
        agent_id: "codex-cli",
        name: "codex-cli",
        display_name: "Codex CLI",
        avatar_url: null,
        icon: "C",
        role: "member",
        kind: "agent",
        driver: "ai",
        accountable_owner: "",
      },
    ]);
  });

  test("passes 数字员工 identity through to the collaboration roster", () => {
    const state = group(["general", "reviewer"]).state;
    const roleMember = state.roster[1];
    state.roster[1] = {
      ...roleMember,
      kind: "role",
      driver: "human",
      accountable_owner: "user-1",
      is_takeover: true,
    };
    const roster = coworkGroupToCollaborationRoster(
      { ...group(["general", "reviewer"]), state },
      "general",
      [],
    );
    expect(
      roster.map((entry) => ({
        agent_id: entry.agent_id,
        kind: entry.kind,
        driver: entry.driver,
        accountable_owner: entry.accountable_owner,
      })),
    ).toEqual([
      { agent_id: "general", kind: "agent", driver: "ai", accountable_owner: "" },
      {
        agent_id: "reviewer",
        kind: "role",
        driver: "human",
        accountable_owner: "user-1",
      },
    ]);
  });

  test("keeps 数字员工 on the collaboration roster while humans stay off", () => {
    const state = group(["general", "reviewer", "alice"]).state;
    state.roster[1] = { ...state.roster[1], kind: "role" };
    state.roster[2] = { ...state.roster[2], kind: "human" as never };
    const roster = coworkGroupToCollaborationRoster(
      { ...group(["general", "reviewer", "alice"]), state },
      "general",
      [],
    );
    expect(roster.map((entry) => entry.agent_id)).toEqual([
      "general",
      "reviewer",
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

  test("maps unified collaboration session roster with the same semantics", () => {
    const roster = coworkSessionToCollaborationRoster(
      session(["general", "analyst"]),
      "general",
      [
        { name: "general", display_name: "General" },
        { name: "analyst", display_name: "Analyst" },
      ],
    );

    expect(roster.map((entry) => [entry.agent_id, entry.role])).toEqual([
      ["general", "tl"],
      ["analyst", "member"],
    ]);
  });
});
