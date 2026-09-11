import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getCoderModelProfile } from "@/core/coder/api";
import type * as CoderApi from "@/core/coder/api";
import { previewExecutionEngine } from "@/core/realtime/execution-policy";

import { useExecutionEngine } from "./use-execution-engine";

vi.mock("@/core/coder/api", async (original) => ({
  ...(await original<typeof CoderApi>()),
  getCoderModelProfile: vi.fn(),
}));

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ available: false, reason: "not configured" }),
    }),
  );
  vi.mocked(getCoderModelProfile).mockResolvedValue({
    execution_available: true,
  } as never);
});

afterEach(() => vi.unstubAllGlobals());

describe("per-task engine preference", () => {
  it("inherits a fork's engine once within the same principal, then keeps its own choice", () => {
    localStorage.setItem("octopus:execution-engine:alice:parent", "codex");
    localStorage.setItem("octopus:execution-engine:bob:parent", "opencode");
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      () =>
        useExecutionEngine({
          threadId: "child",
          parentThreadId: "parent",
          principal: "alice",
          codingTask: false,
          orchestrated: false,
          enabled: false,
        }),
      { wrapper },
    );
    expect(result.current.preference).toBe("codex");
    expect(localStorage.getItem("octopus:execution-engine:alice:child")).toBe(
      "codex",
    );
    act(() => result.current.setPreference("opencode"));
    rerender();
    expect(result.current.preference).toBe("opencode");
    expect(localStorage.getItem("octopus:execution-engine:alice:parent")).toBe(
      "codex",
    );
  });
  it.each(["opencode", "codex"] as const)(
    "keeps a ready %s engine available when a second member joins",
    async (preference) => {
      localStorage.setItem("octopus:execution-engine:alice:team", preference);
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        json: async () => ({ available: true, reason: null }),
      } as Response);
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
      const { result, rerender } = renderHook(
        ({ orchestrated, nativeTopology }) =>
          useExecutionEngine({
            threadId: "team",
            principal: "alice",
            codingTask: false,
            orchestrated,
            nativeTopology,
            enabled: true,
          }),
        {
          wrapper,
          initialProps: { orchestrated: false, nativeTopology: false },
        },
      );
      await waitFor(() => {
        expect(result.current.opencodeAvailable).toBe(true);
        expect(result.current.codexAvailable).toBe(true);
      });
      rerender({ orchestrated: true, nativeTopology: false });
      expect(result.current.preference).toBe(preference);
      expect(result.current.engine).toBe(preference);
      expect(result.current.opencodeAvailable).toBe(true);
      expect(result.current.codexAvailable).toBe(true);
      expect(result.current.codexUnavailableReason).toBeNull();
      expect(result.current.opencodeUnavailableReason).not.toContain("团队");
      // Topology planning now uses the selected external engine too.
      rerender({ orchestrated: true, nativeTopology: true });
      expect(result.current.opencodeAvailable).toBe(true);
      expect(result.current.codexAvailable).toBe(true);
      expect(result.current.codexUnavailableReason).toBeNull();
      expect(result.current.preference).toBe(preference);
      rerender({ orchestrated: true, nativeTopology: false });
      expect(result.current.opencodeAvailable).toBe(true);
      expect(result.current.codexAvailable).toBe(true);
    },
  );

  it.each(["pending", "failed", "unavailable"])(
    "keeps OpenCode selected when readiness is %s",
    async (status) => {
      if (status === "pending")
        vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
      if (status === "failed")
        vi.mocked(fetch).mockRejectedValue(new Error("offline"));
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
      const { result } = renderHook(
        () =>
          useExecutionEngine({
            threadId: "new",
            principal: "alice",
            codingTask: true,
            orchestrated: false,
            enabled: true,
          }),
        { wrapper },
      );
      expect(result.current.preference).toBe("opencode");
      expect(result.current.engine).toBe("opencode");
      if (status !== "pending") {
        await waitFor(() =>
          expect(
            client.getQueryState(["opencode-status", "alice"])?.status,
          ).toBe(status === "failed" ? "error" : "success"),
        );
      }
      expect(result.current.engine).toBe("opencode");
      expect(result.current.opencodeAvailable).toBe(false);
      act(() => result.current.setPreference("auto"));
      act(() =>
        client.setQueryData(["opencode-status", "alice"], {
          available: true,
          reason: null,
        }),
      );
      expect(result.current.preference).toBe("auto");
    },
  );

  it("uses team orchestration before an unset task is sent and pins the sent choice", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ orchestrated, enabled }) =>
        useExecutionEngine({
          threadId: "new",
          principal: "alice",
          codingTask: false,
          orchestrated,
          enabled,
        }),
      { wrapper, initialProps: { orchestrated: false, enabled: false } },
    );
    expect(result.current.preference).toBe("auto");
    rerender({ orchestrated: false, enabled: true });
    expect(result.current.preference).toBe("opencode");
    rerender({ orchestrated: true, enabled: true });
    expect(result.current.preference).toBe("auto");
    expect(result.current.engine).toBe("opencode");
    act(() => result.current.rememberForThread("assigned"));
    rerender({ orchestrated: false, enabled: true });
    expect(result.current.preference).toBe("auto");
  });

  it.each([
    [null, false, undefined, "opencode"],
    ["auto", false, undefined, "auto"],
    ["octopus", false, undefined, "octopus"],
    ["codex", false, undefined, "codex"],
    [null, true, undefined, "auto"],
    [null, false, "codex_app_server", "auto"],
  ] as const)(
    "defaults an unset independent task to OpenCode (%s, team=%s, role=%s)",
    async (saved, orchestrated, roleBackend, expected) => {
      const key = "octopus:execution-engine:alice:new";
      if (saved !== null) localStorage.setItem(key, saved);
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        json: async () => ({ available: true, reason: null }),
      } as Response);
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
      const { result } = renderHook(
        () =>
          useExecutionEngine({
            threadId: "new",
            principal: "alice",
            codingTask: false,
            orchestrated,
            roleBackend,
            enabled: true,
          }),
        { wrapper },
      );
      await waitFor(() =>
        expect(client.getQueryState(["opencode-status", "alice"])?.status).toBe(
          "success",
        ),
      );
      await waitFor(() => expect(result.current.preference).toBe(expected));
      if (expected === "opencode") {
        expect(result.current.engine).toBe("opencode");
        expect(localStorage.getItem(key)).toBeNull();
        act(() => result.current.rememberForThread("assigned"));
        expect(
          localStorage.getItem("octopus:execution-engine:alice:assigned"),
        ).toBe("opencode");
        act(() =>
          client.setQueryData(["opencode-status", "alice"], {
            available: false,
            reason: "offline",
          }),
        );
        await waitFor(() =>
          expect(result.current.opencodeAvailable).toBe(false),
        );
        expect(result.current.engine).toBe("opencode");
      } else {
        expect(localStorage.getItem(key)).toBe(saved);
      }
    },
  );

  it.each([
    ["auto", undefined, false, false, true, "opencode"],
    ["auto", undefined, true, false, true, "opencode"],
    ["auto", undefined, true, false, false, "opencode"],
    ["auto", "codex_app_server", false, true, true, "opencode"],
    ["octopus", "codex_app_server", true, false, true, "octopus"],
    ["codex", undefined, false, false, false, "codex"],
    ["opencode", "codex_app_server", true, false, false, "opencode"],
  ] as const)(
    "previews %s independently of the role %s",
    (
      preference,
      roleBackend,
      codingTask,
      orchestrated,
      codexAvailable,
      expected,
    ) => {
      expect(
        previewExecutionEngine({
          preference,
          roleBackend,
          codingTask,
          orchestrated,
          codexAvailable,
        }),
      ).toBe(expected);
    },
  );

  it("scopes saved choices to the principal and task and follows a new task's assigned id", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ principal, threadId }) =>
        useExecutionEngine({
          principal,
          threadId,
          codingTask: true,
          orchestrated: false,
          enabled: true,
        }),
      { initialProps: { principal: "alice", threadId: "new" }, wrapper },
    );
    expect(result.current.engine).toBe("opencode");
    act(() => result.current.setPreference("octopus"));
    expect(result.current.engine).toBe("octopus");
    act(() => result.current.rememberForThread("assigned-id"));
    rerender({ principal: "alice", threadId: "assigned-id" });
    expect(result.current.preference).toBe("octopus");
    rerender({ principal: "bob", threadId: "assigned-id" });
    expect(result.current.preference).toBe("opencode");
    rerender({ principal: "alice", threadId: "assigned-id" });
    expect(result.current.preference).toBe("octopus");
    rerender({ principal: "alice", threadId: "another-task" });
    expect(result.current.preference).toBe("opencode");
  });
});
