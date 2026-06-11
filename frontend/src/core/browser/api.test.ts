import { describe, expect, test } from "vitest";

import { createOctopusBrowserSessionIdentity } from "./api";

describe("browser session identity", () => {
  test("binds browser sessions to an Octopus workspace path", () => {
    const first = createOctopusBrowserSessionIdentity({
      threadId: "thread-1",
      workspacePath: "F:\\work\\octopus-agent",
    });
    const second = createOctopusBrowserSessionIdentity({
      threadId: "thread-2",
      workspacePath: "F:\\work\\octopus-agent",
    });

    expect(first).toEqual(second);
    expect(first.scope).toBe("workspace");
    expect(first.displayName).toBe("octopus-agent");
    expect(first.projectId).toBe("octopus-workspace:F:\\work\\octopus-agent");
    expect(first.sessionId).toMatch(/^octopus-workspace-octopus-agent-/);
    expect(first.profileId).toBe(first.sessionId);
  });

  test("keeps same-name workspace folders isolated", () => {
    const alpha = createOctopusBrowserSessionIdentity({
      workspacePath: "F:\\alpha\\octopus-agent",
    });
    const beta = createOctopusBrowserSessionIdentity({
      workspacePath: "F:\\beta\\octopus-agent",
    });

    expect(alpha.displayName).toBe(beta.displayName);
    expect(alpha.sessionId).not.toBe(beta.sessionId);
    expect(alpha.profileId).not.toBe(beta.profileId);
  });

  test("falls back to thread scope when no workspace is active", () => {
    const identity = createOctopusBrowserSessionIdentity({
      threadId: "thread-123456789",
    });

    expect(identity.scope).toBe("thread");
    expect(identity.displayName).toBe("thread/thread-1");
    expect(identity.projectId).toBe("octopus-thread:thread-123456789");
    expect(identity.sessionId).toMatch(/^octopus-thread-thread-thread-1-/);
  });
});
