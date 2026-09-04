import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

const pageSource = readFileSync(
  join(process.cwd(), "src/app/workspace/realtime/[thread_id]/page.tsx"),
  "utf8",
);

describe("realtime cowork response-mode persistence contract", () => {
  test("syncs the user's current mode intent instead of the stale saved mode", () => {
    expect(pageSource).toContain(
      "pendingRosterModeRef.current ??\n        normalizeTeamResponseMode(teamModeIntent)",
    );
    expect(pageSource).not.toContain(
      "pendingRosterModeRef.current ??\n        normalizeTeamResponseMode(savedCollaborationMode)",
    );
  });

  test("a failed save can retry the same signature and visibly rolls back", () => {
    expect(pageSource).toContain("lastCoworkSyncSignatureRef.current = null;");
    expect(pageSource).toContain('toast.error("AI 成员保存失败，请重试")');
  });

  test("uses the mutation's group-state cache as the authoritative mode source", () => {
    expect(pageSource).toContain(
      "coworkGroupQuery.data?.state.mode ?? collabSessionQuery.data?.mode",
    );
    expect(pageSource).toContain(
      "coworkGroupQuery.data?.state ?? sessionState ?? null",
    );
  });
});
