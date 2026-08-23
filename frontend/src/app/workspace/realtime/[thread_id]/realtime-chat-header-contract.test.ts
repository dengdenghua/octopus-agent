import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const pageSource = readFileSync(
  join(process.cwd(), "src/app/workspace/realtime/[thread_id]/page.tsx"),
  "utf8",
);

function sourceBetween(start: string, end: string): string {
  const startIndex = pageSource.indexOf(start);
  expect(startIndex).toBeGreaterThanOrEqual(0);
  const endIndex = pageSource.indexOf(end, startIndex + start.length);
  expect(endIndex).toBeGreaterThan(startIndex);
  return pageSource.slice(startIndex, endIndex);
}

describe("realtime compact chat header contract", () => {
  it("uses one responsive shell for every non-Octopus conversation", () => {
    const header = sourceBetween("header={", "messageList={");

    expect(header).toContain("!isOctopusAssistant ? (");
    expect(header).toContain("<RealtimeGroupHeaderLayout");
    expect(header).not.toContain("isGroupConversation ? (");
    expect(header).toContain(
      'className="absolute left-3 top-1/2 -translate-y-1/2 md:hidden"',
    );
    expect(pageSource).toContain(
      'headerClassName={!isOctopusAssistant ? "md:pl-3" : undefined}',
    );
  });

  it("combines the two member domains without merging their counts", () => {
    const memberSurface = sourceBetween(
      "const headerMemberSurface",
      "const headerActions",
    );

    expect(memberSurface).toContain("<RealtimeChatHeaderMemberSurface");
    expect(memberSurface).toContain("aiMembers={headerMemberControl}");
    expect(memberSurface).toContain("humanInvite={headerHumanInvite}");
  });

  it("keeps active REC primary and sends idle REC plus sharing to More", () => {
    const actions = sourceBetween("const headerActions", "return (");

    expect(actions).toContain(
      "recording={recIsRecording ? headerRecorder : null}",
    );
    expect(actions).toContain("<RealtimeChatHeaderOverflowMenu");
    expect(actions).toContain(
      "recIsRecording ? undefined : () => setRecOverlayOpen(true)",
    );
    expect(actions).toContain("share={headerShareOptions ?? undefined}");
  });
});
