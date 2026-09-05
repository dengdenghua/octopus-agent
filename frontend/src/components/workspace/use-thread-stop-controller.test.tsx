import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  STOP_TERMINAL_WAIT_MS,
  useThreadStopController,
} from "./use-thread-stop-controller";

function deferred() {
  let resolve!: () => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useThreadStopController", () => {
  it("shares one operation and clears busy after the first stop path succeeds", async () => {
    const interrupt = deferred();
    const pause = deferred();
    const stopThread = vi.fn(() => interrupt.promise);
    const pauseActiveTask = vi.fn(() => pause.promise);
    const onFailure = vi.fn();
    const { result, rerender } = renderHook(
      ({ isRunning }) =>
        useThreadStopController({
          threadId: "thread-a",
          stopThread,
          pauseActiveTask,
          isRunning,
          onFailure,
        }),
      { initialProps: { isRunning: true } },
    );

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.stop();
      second = result.current.stop();
    });

    expect(first).toBe(second);
    expect(result.current.isStopping).toBe(true);
    expect(stopThread).toHaveBeenCalledTimes(1);
    expect(pauseActiveTask).toHaveBeenCalledTimes(1);

    interrupt.resolve();
    await act(async () => first);

    expect(result.current.isStopping).toBe(true);
    expect(onFailure).not.toHaveBeenCalled();

    rerender({ isRunning: false });
    expect(result.current.isStopping).toBe(false);

    // A late fallback completion is still observed without reopening or
    // changing the already successful stop operation.
    pause.resolve();
    await act(async () => pause.promise);
    expect(result.current.isStopping).toBe(false);
  });

  it("unlocks and reports when an acknowledged stop never becomes terminal", async () => {
    vi.useFakeTimers();
    try {
      const onFailure = vi.fn();
      const { result } = renderHook(() =>
        useThreadStopController({
          threadId: "thread-a",
          stopThread: vi.fn().mockResolvedValue(undefined),
          isRunning: true,
          onFailure,
        }),
      );

      await act(async () => result.current.stop());
      expect(result.current.isStopping).toBe(true);

      await act(async () => {
        vi.advanceTimersByTime(STOP_TERMINAL_WAIT_MS);
      });
      expect(result.current.isStopping).toBe(false);
      expect(onFailure).toHaveBeenCalledWith(expect.any(Error));
    } finally {
      vi.useRealTimers();
    }
  });

  it("treats a terminal edge as success before either RPC acknowledges", async () => {
    const interrupt = deferred();
    const pause = deferred();
    const onFailure = vi.fn();
    const { result, rerender } = renderHook(
      ({ isRunning }) =>
        useThreadStopController({
          threadId: "thread-a",
          stopThread: () => interrupt.promise,
          pauseActiveTask: () => pause.promise,
          isRunning,
          onFailure,
        }),
      { initialProps: { isRunning: true } },
    );

    let operation!: Promise<void>;
    act(() => {
      operation = result.current.stop();
    });
    expect(result.current.isStopping).toBe(true);

    rerender({ isRunning: false });
    await act(async () => operation);
    expect(result.current.isStopping).toBe(false);
    expect(onFailure).not.toHaveBeenCalled();

    interrupt.resolve();
    pause.resolve();
    await act(async () => Promise.all([interrupt.promise, pause.promise]));
    expect(result.current.isStopping).toBe(false);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("times out pending stop requests and ignores their late acknowledgements", async () => {
    vi.useFakeTimers();
    try {
      const interrupt = deferred();
      const pause = deferred();
      const onFailure = vi.fn();
      const { result } = renderHook(() =>
        useThreadStopController({
          threadId: "thread-a",
          stopThread: () => interrupt.promise,
          pauseActiveTask: () => pause.promise,
          isRunning: true,
          onFailure,
        }),
      );

      let operation!: Promise<void>;
      act(() => {
        operation = result.current.stop();
      });
      expect(result.current.isStopping).toBe(true);

      await act(async () => {
        vi.advanceTimersByTime(STOP_TERMINAL_WAIT_MS);
        await operation;
      });
      expect(result.current.isStopping).toBe(false);
      expect(onFailure).toHaveBeenCalledTimes(1);

      interrupt.resolve();
      pause.resolve();
      await act(async () => Promise.all([interrupt.promise, pause.promise]));
      expect(result.current.isStopping).toBe(false);
      expect(onFailure).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("accepts a durable pause when the realtime interrupt is rejected", async () => {
    const onFailure = vi.fn();
    const { result } = renderHook(() =>
      useThreadStopController({
        threadId: "thread-a",
        stopThread: vi.fn().mockRejectedValue(new Error("socket closed")),
        pauseActiveTask: vi.fn().mockResolvedValue(undefined),
        onFailure,
      }),
    );

    await act(async () => result.current.stop());

    expect(onFailure).not.toHaveBeenCalled();
    expect(result.current.isStopping).toBe(false);
  });

  it("reports failure only when neither stop path succeeds", async () => {
    const onFailure = vi.fn();
    const { result } = renderHook(() =>
      useThreadStopController({
        threadId: "thread-a",
        stopThread: vi.fn().mockRejectedValue(new Error("interrupt failed")),
        pauseActiveTask: vi.fn().mockRejectedValue(new Error("pause failed")),
        onFailure,
      }),
    );

    await act(async () => result.current.stop());

    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onFailure).toHaveBeenCalledWith(expect.any(Error));
  });

  it("does not let an old thread completion clear or report on a new stop", async () => {
    const stopA = deferred();
    const stopB = deferred();
    const onFailure = vi.fn();
    const { result, rerender } = renderHook(
      ({ threadId, stopThread }) =>
        useThreadStopController({ threadId, stopThread, onFailure }),
      {
        initialProps: {
          threadId: "thread-a",
          stopThread: vi.fn(() => stopA.promise),
        },
      },
    );

    let operationA!: Promise<void>;
    act(() => {
      operationA = result.current.stop();
    });
    rerender({
      threadId: "thread-b",
      stopThread: vi.fn(() => stopB.promise),
    });
    let operationB!: Promise<void>;
    act(() => {
      operationB = result.current.stop();
    });

    stopA.reject(new Error("late A failure"));
    await act(async () => operationA);
    expect(result.current.isStopping).toBe(true);
    expect(onFailure).not.toHaveBeenCalled();

    stopB.resolve();
    await act(async () => operationB);
    expect(result.current.isStopping).toBe(false);
  });

  it("invalidates a pending stop so returning to the thread can retry", async () => {
    const firstA = deferred();
    const retryA = deferred();
    const stopFirstA = vi.fn(() => firstA.promise);
    const stopRetryA = vi.fn(() => retryA.promise);
    const onFailure = vi.fn();
    const { result, rerender } = renderHook(
      ({ threadId, stopThread }) =>
        useThreadStopController({ threadId, stopThread, onFailure }),
      {
        initialProps: {
          threadId: "thread-a",
          stopThread: stopFirstA,
        },
      },
    );

    let abandonedOperation!: Promise<void>;
    act(() => {
      abandonedOperation = result.current.stop();
    });
    expect(stopFirstA).toHaveBeenCalledTimes(1);

    rerender({
      threadId: "thread-b",
      stopThread: vi.fn().mockResolvedValue(undefined),
    });
    await act(async () => abandonedOperation);
    rerender({ threadId: "thread-a", stopThread: stopRetryA });

    let retryOperation!: Promise<void>;
    act(() => {
      retryOperation = result.current.stop();
    });
    expect(stopRetryA).toHaveBeenCalledTimes(1);
    expect(result.current.isStopping).toBe(true);

    firstA.resolve();
    await act(async () => firstA.promise);
    expect(result.current.isStopping).toBe(true);

    retryA.resolve();
    await act(async () => retryOperation);
    expect(result.current.isStopping).toBe(false);
    expect(onFailure).not.toHaveBeenCalled();
  });
});
