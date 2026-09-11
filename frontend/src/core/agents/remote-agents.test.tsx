import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { remoteToGroupAgent, useRemoteGroupAgents } from "./remote-agents";

afterEach(() => vi.unstubAllGlobals());

describe("remote group members", () => {
  it("keeps the remote id and shows explicit dispatch and offline state", () => {
    const agent = remoteToGroupAgent({
      agent_id: "a2a_workbuddy",
      name: "WorkBuddy",
      status: "unreachable",
    });
    expect(agent.name).toBe("a2a_workbuddy");
    expect(agent.display_name).toBe("WorkBuddy");
    expect(agent.description).toContain("@点名");
    expect(agent.description).toContain("连接不可用");
  });

  it("loads registered roles when the group picker becomes visible", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        agents: [{ agent_id: "a2a_workbuddy", name: "WorkBuddy" }],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result, rerender } = renderHook(
      ({ enabled }) => useRemoteGroupAgents(enabled),
      {
        initialProps: { enabled: false },
        wrapper: ({ children }: PropsWithChildren) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
    expect(fetchMock).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current[0]?.name).toBe("a2a_workbuddy"));
  });
});
