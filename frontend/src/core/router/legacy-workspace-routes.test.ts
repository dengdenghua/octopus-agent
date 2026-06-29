import { describe, expect, test } from "vitest";

import { legacyTeamWorkspaceTarget } from "./legacy-workspace-routes";

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
});
