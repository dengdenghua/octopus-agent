import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { swallow } from "@/core/utils/log";

interface UseThreadStopControllerOptions {
  threadId: string;
  stopThread: () => void | Promise<void>;
  pauseActiveTask?: () => Promise<unknown>;
  isRunning?: boolean;
  onFailure: (error: unknown) => void;
  terminalWaitMs?: number;
}

interface StopOperation {
  threadId: string;
  promise: Promise<void>;
  resolve: () => void;
  settled: boolean;
}

interface StopVisualState {
  threadId: string;
  acknowledged: boolean;
}

export const STOP_TERMINAL_WAIT_MS = 15_000;

type StopAttemptResult =
  | { succeeded: true }
  | { succeeded: false; error: unknown };

function settleCall<T>(call: () => T | Promise<T>): Promise<T> {
  try {
    return Promise.resolve(call());
  } catch (error) {
    return Promise.reject(error);
  }
}

function runStopAttempt(call: () => unknown | Promise<unknown>) {
  return settleCall(call).then<StopAttemptResult, StopAttemptResult>(
    () => ({ succeeded: true }),
    (error: unknown) => ({ succeeded: false, error }),
  );
}

/**
 * Coordinate every visible stop entry point for a thread.
 *
 * The realtime interrupt and the durable task pause are independent recovery
 * paths. Run both, consider either acknowledgement sufficient, and keep a
 * single in-flight Promise so rapid clicks cannot create duplicate requests.
 * Operations are tagged with their thread so a late result from a route we
 * already left cannot clear or report against the new conversation.
 */
export function useThreadStopController({
  threadId,
  stopThread,
  pauseActiveTask,
  isRunning,
  onFailure,
  terminalWaitMs = STOP_TERMINAL_WAIT_MS,
}: UseThreadStopControllerOptions): {
  stop: () => Promise<void>;
  isStopping: boolean;
} {
  const activeThreadIdRef = useRef(threadId);
  useLayoutEffect(() => {
    activeThreadIdRef.current = threadId;
  }, [threadId]);
  const operationRef = useRef<StopOperation | null>(null);
  const [stopState, setStopState] = useState<StopVisualState | null>(null);

  useLayoutEffect(() => {
    const operation = operationRef.current;
    if (!operation || operation.threadId === threadId) return;
    if (!operation.settled) {
      operation.settled = true;
      operation.resolve();
    }
    operationRef.current = null;
  }, [threadId]);

  useEffect(() => {
    setStopState((current) =>
      current?.threadId === threadId ? current : null,
    );
  }, [threadId]);

  useEffect(() => {
    if (stopState?.threadId !== threadId || isRunning === true) return;
    // With an explicit running signal, the authoritative terminal edge wins
    // even if both stop RPC acknowledgements are still pending. Settling the
    // operation prevents a late acknowledgement from locking the ready
    // composer again. Callers that omit the signal keep the legacy
    // acknowledgement-only behavior.
    if (!stopState.acknowledged && isRunning !== false) return;
    const operation = operationRef.current;
    if (
      operation?.threadId === threadId &&
      !operation.settled &&
      isRunning === false
    ) {
      operation.settled = true;
      operation.resolve();
    }
    setStopState(null);
  }, [isRunning, stopState, threadId]);

  useEffect(() => {
    if (stopState?.threadId !== threadId || isRunning !== true) {
      return;
    }
    const timer = window.setTimeout(() => {
      if (activeThreadIdRef.current !== threadId) return;
      const operation = operationRef.current;
      if (operation?.threadId === threadId && !operation.settled) {
        operation.settled = true;
        operation.resolve();
      }
      setStopState((current) =>
        current?.threadId === threadId ? null : current,
      );
      try {
        onFailure(new Error("stop acknowledgement did not become terminal"));
      } catch (error) {
        swallow(error);
      }
    }, terminalWaitMs);
    return () => window.clearTimeout(timer);
  }, [isRunning, onFailure, stopState, terminalWaitMs, threadId]);

  const stop = useCallback((): Promise<void> => {
    const current = operationRef.current;
    if (current?.threadId === threadId) return current.promise;

    const operation: StopOperation = {
      threadId,
      promise: Promise.resolve(),
      resolve: () => undefined,
      settled: false,
    };
    setStopState({ threadId, acknowledged: false });
    const attempts = [runStopAttempt(stopThread)];
    if (pauseActiveTask) attempts.push(runStopAttempt(pauseActiveTask));
    operation.promise = new Promise<void>((resolve) => {
      operation.resolve = resolve;
      let failedAttempts = 0;
      let firstError: unknown;
      for (const attempt of attempts) {
        void attempt.then((result) => {
          if (operation.settled) {
            if (!result.succeeded) swallow(result.error);
            return;
          }
          if (result.succeeded) {
            operation.settled = true;
            if (
              operationRef.current === operation &&
              activeThreadIdRef.current === threadId
            ) {
              setStopState({ threadId, acknowledged: true });
            }
            operation.resolve();
            return;
          }
          swallow(result.error);
          failedAttempts += 1;
          firstError ??= result.error;
          if (failedAttempts !== attempts.length) return;
          operation.settled = true;
          if (
            operationRef.current === operation &&
            activeThreadIdRef.current === threadId
          ) {
            setStopState(null);
            try {
              onFailure(firstError);
            } catch (error) {
              swallow(error);
            }
          }
          operation.resolve();
        });
      }
    }).finally(() => {
      if (operationRef.current === operation) {
        operationRef.current = null;
      }
    });
    operationRef.current = operation;
    return operation.promise;
  }, [onFailure, pauseActiveTask, stopThread, threadId]);

  return {
    stop,
    isStopping:
      stopState?.threadId === threadId &&
      (!stopState.acknowledged || isRunning === true),
  };
}
