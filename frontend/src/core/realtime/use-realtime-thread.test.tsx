// Approval lifecycle of useRealtimeThread: client-side expiry mirrors
// the server timeout (params.timeoutMs), and a socket drop clears all
// pending approval dialogs (the server cancelled their futures, so the
// request ids are dead).

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonRpcRequest } from "./envelope";
import { useRealtimeThread } from "./use-realtime-thread";

type IncomingRequestFn = (req: JsonRpcRequest) => Promise<unknown>;

interface FakeClientHandles {
  emitRequest: (req: JsonRpcRequest) => Promise<unknown>;
  emitClose: (code: number, reason: string) => void;
}

function makeFakeClientFactory(handles: FakeClientHandles[]) {
  return (deps: {
    onIncomingRequest: IncomingRequestFn;
    onNotification: (n: { method: string; params: Record<string, unknown> }) => void;
    onOpen?: () => void;
    onClose?: (code: number, reason: string) => void;
  }) => {
    handles.push({
      emitRequest: (req) => deps.onIncomingRequest(req),
      emitClose: (code, reason) => deps.onClose?.(code, reason),
    });
    return {
      connect: () => {
        deps.onOpen?.();
      },
      close: () => {},
      // thread/resume resolves empty so the hook settles immediately.
      request: () => Promise.resolve({ thread: { id: "th" }, turns: [] }),
      notify: () => {},
    };
  };
}

describe("useRealtimeThread approval lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function setup() {
    const handles: FakeClientHandles[] = [];
    const factory = makeFakeClientFactory(handles);
    const rendered = renderHook(() =>
      useRealtimeThread({
        threadId: "th",
        clientFactory: factory as never,
      }),
    );
    const handle = handles[0]!;
    return { rendered, handle };
  }

  it("expires a pending approval after params.timeoutMs", async () => {
    const { rendered, handle } = setup();

    let reply: unknown = null;
    act(() => {
      void handle
        .emitRequest({
          jsonrpc: "2.0",
          id: 7,
          method: "item/commandExecution/requestApproval",
          params: { tool: "exec_shell", timeoutMs: 5_000 },
        } as JsonRpcRequest)
        .then((decision) => {
          reply = decision;
        });
    });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(5_001);
    });

    expect(rendered.result.current.state.pendingApprovals).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(reply).toMatchObject({ action: "decline", reason: "timeout" });
  });

  it("a user resolution cancels the expiry timer", async () => {
    const { rendered, handle } = setup();

    let reply: unknown = null;
    act(() => {
      void handle
        .emitRequest({
          jsonrpc: "2.0",
          id: 8,
          method: "item/commandExecution/requestApproval",
          params: { tool: "exec_shell", timeoutMs: 5_000 },
        } as JsonRpcRequest)
        .then((decision) => {
          reply = decision;
        });
    });

    act(() => {
      rendered.result.current.resolveApproval(8, true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(reply).toMatchObject({ action: "accept" });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(0);

    // The timer must not fire a second resolution later.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(reply).toMatchObject({ action: "accept" });
  });

  it("drops all pending approvals when the socket closes", () => {
    const { rendered, handle } = setup();

    act(() => {
      void handle.emitRequest({
        jsonrpc: "2.0",
        id: 9,
        method: "item/commandExecution/requestApproval",
        params: { tool: "exec_shell", timeoutMs: 60_000 },
      } as JsonRpcRequest);
    });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(1);

    act(() => {
      handle.emitClose(1006, "abnormal");
    });

    expect(rendered.result.current.state.pendingApprovals).toHaveLength(0);
  });
});

describe("useRealtimeThread backwards pagination", () => {
  function turn(id: string) {
    return {
      id,
      threadId: "th",
      status: "completed",
      items: [],
      startedAt: new Date().toISOString(),
    };
  }

  function makePagingFactory() {
    const requests: Array<{ method: string; params: Record<string, unknown> }> =
      [];
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => ({
      connect: () => deps.onOpen?.(),
      close: () => {},
      notify: () => {},
      request: (method: string, params: Record<string, unknown>) => {
        requests.push({ method, params });
        if (method !== "thread/resume") return Promise.resolve({});
        if (params.beforeTurnId === "t-8") {
          return Promise.resolve({
            turns: [turn("t-6"), turn("t-7")],
            hasMore: false,
          });
        }
        return Promise.resolve({
          thread: { id: "th" },
          turns: [turn("t-8"), turn("t-9")],
          hasMore: true,
        });
      },
    });
    return { factory, requests };
  }

  it("resumes with a limit and pages older turns in front", async () => {
    const { factory, requests } = makePagingFactory();
    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );

    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );
    expect(rendered.result.current.state.turns.map((t) => t.id)).toEqual([
      "t-8",
      "t-9",
    ]);
    expect(rendered.result.current.state.hasMoreTurns).toBe(true);
    const initialResume = requests.find((r) => r.method === "thread/resume");
    expect(initialResume?.params.limit).toBeGreaterThan(0);

    await act(async () => {
      await rendered.result.current.loadOlderTurns();
    });

    expect(rendered.result.current.state.turns.map((t) => t.id)).toEqual([
      "t-6",
      "t-7",
      "t-8",
      "t-9",
    ]);
    expect(rendered.result.current.state.hasMoreTurns).toBe(false);

    // Exhausted — further calls are no-ops, no extra RPC.
    const callCount = requests.length;
    await act(async () => {
      await rendered.result.current.loadOlderTurns();
    });
    expect(requests.length).toBe(callCount);
  });
});
