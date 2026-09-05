import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCoderModelProfile } from "@/core/coder/api";
import { previewExecutionEngine } from "@/core/realtime/execution-policy";

import { useExecutionEngine } from "./use-execution-engine";

vi.mock("@/core/coder/api", async (original) => ({
  ...(await original<typeof import("@/core/coder/api")>()),
  getCoderModelProfile: vi.fn(),
}));

beforeEach(() => {
  localStorage.clear();
  vi.mocked(getCoderModelProfile).mockResolvedValue({
    execution_available: true,
  } as never);
});

describe("per-task engine preference", () => {
  it.each([
    ["auto", undefined, false, false, true, "octopus"],
    ["auto", undefined, true, false, true, "codex"],
    ["auto", undefined, true, false, false, "octopus"],
    ["auto", "codex_app_server", false, true, true, "octopus"],
    ["octopus", "codex_app_server", true, false, true, "octopus"],
    ["codex", undefined, false, false, false, "codex"],
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
    await waitFor(() => expect(result.current.engine).toBe("codex"));
    act(() => result.current.setPreference("octopus"));
    expect(result.current.engine).toBe("octopus");
    act(() => result.current.rememberForThread("assigned-id"));
    rerender({ principal: "alice", threadId: "assigned-id" });
    expect(result.current.preference).toBe("octopus");
    rerender({ principal: "bob", threadId: "assigned-id" });
    expect(result.current.preference).toBe("auto");
    rerender({ principal: "alice", threadId: "assigned-id" });
    expect(result.current.preference).toBe("octopus");
    rerender({ principal: "alice", threadId: "another-task" });
    expect(result.current.preference).toBe("auto");
  });
});
