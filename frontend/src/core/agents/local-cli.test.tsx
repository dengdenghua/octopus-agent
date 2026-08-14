import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({ Authorization: "Bearer cli-test-token" }),
}));

import {
  dedupePersonaAgentsByDisplayName,
  localCliPartnerVisualStatus,
  useLocalCliAgents,
  useLocalCliPartnerAgents,
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

  it("keeps supported but missing partners visible with their local avatar", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/cli-team/status")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detected: [
                {
                  agent_id: "local_trae_cli",
                  partner_id: "trae-cli",
                  command: "/Users/me/.local/bin/trae-cli",
                },
              ],
              repo_root: "/repo",
              is_git_repo: true,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            partners: [
              {
                id: "trae-cli",
                agent_id: "local_trae_cli",
                name: "Trae CLI",
                default_alias: "Trae CLI 伙伴",
                description: "本机 Trae CLI",
                avatar_url: "https://example.test/trae.png",
                detected: true,
                registered: false,
                status: "detected",
                effective_status: "ready",
                ready: true,
              },
              {
                id: "kimi-cli",
                agent_id: "local_kimi_cli",
                name: "Kimi CLI",
                default_alias: "Kimi CLI 伙伴",
                description: "本机 Kimi CLI",
                avatar_url: "https://www.kimi.com/favicon.ico",
                detected: false,
                registered: false,
                status: "missing",
                effective_status: "missing",
                ready: false,
                fix_hint: "安装对应官方 CLI，并确认命令在 PATH 中。",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    });

    const { result } = renderHook(() => useLocalCliPartnerAgents(), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(
      result.current.partners.map((row) => row.agent.display_name),
    ).toEqual(["Trae CLI", "Kimi CLI"]);
    expect(result.current.partners[0]).toMatchObject({
      detected: true,
      ready: true,
    });
    expect(
      result.current.partners[0]?.agent.capabilities?.local_partner_command,
    ).toBe("/Users/me/.local/bin/trae-cli");
    expect(result.current.partners[1]).toMatchObject({
      detected: false,
      ready: false,
      fixHint: "安装对应官方 CLI，并确认命令在 PATH 中。",
    });
    expect(result.current.partners[1]?.agent.avatar_url).toBe(
      "/api/agents/local-partners/kimi-cli/brand-avatar",
    );
  });
});

describe("localCliPartnerVisualStatus", () => {
  const labels = {
    connected: "已接入",
    detected: "已检测",
    notDetected: "未检测",
  };

  it("does not call a registered but unready partner connected", () => {
    expect(
      localCliPartnerVisualStatus(
        {
          detected: true,
          ready: false,
          registered: true,
          status: "model_unconfigured",
        },
        labels,
      ),
    ).toEqual({ label: "模型未配置", tone: "warning" });
  });

  it("distinguishes connectable from registered", () => {
    expect(
      localCliPartnerVisualStatus(
        { detected: true, ready: true, registered: false, status: "ready" },
        labels,
      ).label,
    ).toBe("可接入");
    expect(
      localCliPartnerVisualStatus(
        {
          detected: true,
          ready: true,
          registered: true,
          status: "registered",
        },
        labels,
      ).label,
    ).toBe("已注册");
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
