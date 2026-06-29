import { describe, expect, test } from "vitest";

import {
  legacyAgentChatWorkspaceTarget,
  legacyTeamWorkspaceTarget,
} from "./legacy-workspace-routes";

describe("legacy workspace route targets", () => {
  test("sends old team entrypoints to the unified task composer", () => {
    expect(legacyTeamWorkspaceTarget()).toBe("/workspace/realtime/new");
    expect(legacyTeamWorkspaceTarget("new", "?draft=1")).toBe(
      "/workspace/realtime/new?draft=1",
    );
  });

  test("sends old team threads to the same thread in realtime", () => {
    expect(legacyTeamWorkspaceTarget("team-thread")).toBe(
      "/workspace/realtime/team-thread",
    );
    expect(legacyTeamWorkspaceTarget("team thread", "surface=chat")).toBe(
      "/workspace/realtime/team%20thread?surface=chat",
    );
  });

  test("sends old agent chat entrypoints to realtime with agent query", () => {
    expect(legacyAgentChatWorkspaceTarget("coder", "new")).toBe(
      "/workspace/realtime/new?agent=coder",
    );
    expect(
      legacyAgentChatWorkspaceTarget("local coder", "thread-1", "?prompt=fix"),
    ).toBe("/workspace/realtime/thread-1?prompt=fix&agent=local+coder");
  });

  test("preserves explicit agent query when redirecting old agent chats", () => {
    expect(
      legacyAgentChatWorkspaceTarget(
        "coder",
        "thread / 中文",
        "?agent=reviewer",
      ),
    ).toBe(
      "/workspace/realtime/thread%20%2F%20%E4%B8%AD%E6%96%87?agent=reviewer",
    );
  });
});
