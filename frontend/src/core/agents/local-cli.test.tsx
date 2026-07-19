import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({ Authorization: "Bearer cli-test-token" }),
}));

import {
  dedupePersonaAgentsByDisplayName,
  useLocalCliAgents,
} from "./local-cli";
import type { Agent } from "./types";

const fetchMock = vi.fn();

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useLocalCliAgents", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("authenticates detection and maps every detected partner", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detected: [
            {
              agent_id: "local_trae_cli",
              partner_id: "trae-cli",
              command: "trae-cli",
            },
            {
              agent_id: "local_codebuddy_cli",
              partner_id: "codebuddy-cli",
              command: "codebuddy",
            },
          ],
          repo_root: "/repo",
          is_git_repo: true,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useLocalCliAgents(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isError).toBe(false);
    expect(result.current.cliAgents.map((agent) => agent.display_name)).toEqual(
      ["Trae CLI", "CodeBuddy CLI"],
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/cli-team/status",
      expect.objectContaining({
        cache: "no-store",
        headers: { Authorization: "Bearer cli-test-token" },
      }),
    );
  });

  it("exposes detection failures instead of presenting them as an empty scan", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }));

    const { result } = renderHook(() => useLocalCliAgents(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.cliAgents).toEqual([]);
  });
});

describe("dedupePersonaAgentsByDisplayName", () => {
  const agent = (name: string, displayName: string): Agent => ({
    name,
    display_name: displayName,
    description: "",
    model: null,
    tool_groups: null,
  });

  it("shows a persona and its slash-suffixed alias only once", () => {
    expect(
      dedupePersonaAgentsByDisplayName([
        agent("echo_eve", "Eve / Siren"),
        agent("general", "Eve"),
        agent("echo_kane", "Kane / Paladin"),
        agent("kane", "Kane"),
      ]).map((item) => item.name),
    ).toEqual(["general", "kane"]);
  });

  it("keeps external runtimes with the same friendly label distinct", () => {
    expect(
      dedupePersonaAgentsByDisplayName([
        agent("mobile_phone_one", "My phone"),
        agent("mobile_phone_two", "My phone"),
        agent("local_cli_one", "CLI"),
        agent("local_cli_two", "CLI"),
      ]),
    ).toHaveLength(4);
  });
});
