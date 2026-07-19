import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSearxngControl, useSearxngStatus } from "./use-searxng-status";

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSearxngStatus", () => {
  it("preserves an unavailable status as an error instead of Docker missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503 }),
    );

    const { result } = renderHook(() => useSearxngStatus(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.status).toBeUndefined();
  });

  it("rejects a successful HTTP response when Docker could not start", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: "docker_not_running",
          up: false,
          heartbeat: false,
          docker_present: true,
          managed: false,
          autostart: false,
        }),
      }),
    );

    const { result } = renderHook(() => useSearxngControl(), {
      wrapper: createWrapper(),
    });

    await expect(result.current.setEnabled(true)).rejects.toThrow(
      "docker_not_running",
    );
  });
});
