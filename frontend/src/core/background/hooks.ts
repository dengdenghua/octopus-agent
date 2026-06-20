/** React hooks for background task management. */

import { swallow } from "@/core/utils/log";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelBackgroundTask,
  connectOutputSSE,
  deleteBackgroundTask,
  getActiveBackgroundTaskCount,
  listBackgroundTasks,
  pauseBackgroundTask,
  pollBackgroundTaskOutput,
  resumeBackgroundTask,
  submitBackgroundTask,
} from "./api";
import type {
  BackgroundTask,
  BackgroundTaskOutput,
  SubmitBackgroundTaskRequest,
} from "./types";

// ---------------------------------------------------------------------------
// useBackgroundTasks — list + manage tasks
// ---------------------------------------------------------------------------

export function useBackgroundTasks() {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const data = await listBackgroundTasks();
      setTasks(data);
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    // Periodically refresh for live status updates
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const submit = useCallback(
    async (req: SubmitBackgroundTaskRequest) => {
      const task = await submitBackgroundTask(req);
      await refresh();
      return task;
    },
    [refresh],
  );

  const pause = useCallback(
    async (taskId: string) => {
      await pauseBackgroundTask(taskId);
      await refresh();
    },
    [refresh],
  );

  const resume = useCallback(
    async (taskId: string) => {
      await resumeBackgroundTask(taskId);
      await refresh();
    },
    [refresh],
  );

  const cancel = useCallback(
    async (taskId: string) => {
      await cancelBackgroundTask(taskId);
      await refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (taskId: string) => {
      await deleteBackgroundTask(taskId);
      await refresh();
    },
    [refresh],
  );

  return {
    tasks,
    loading,
    error,
    refresh,
    submit,
    pause,
    resume,
    cancel,
    remove,
  };
}

// ---------------------------------------------------------------------------
// useBackgroundTaskOutput — live output stream for a single task
// ---------------------------------------------------------------------------

export function useBackgroundTaskOutput(taskId: string | null) {
  const [messages, setMessages] = useState<BackgroundTaskOutput[]>([]);
  const [done, setDone] = useState(false);
  const [doneStatus, setDoneStatus] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!taskId) {
      setMessages([]);
      setDone(false);
      setDoneStatus(null);
      return;
    }

    // First, load existing messages via poll
    let cancelled = false;
    pollBackgroundTaskOutput(taskId, 0, 1000)
      .then((existing) => {
        if (cancelled) return;
        setMessages(existing);

        // Then connect SSE for live updates
        const lastSeq =
          existing.length > 0 ? existing[existing.length - 1]!.seq : -1;
        const controller = connectOutputSSE(
          taskId,
          {
            onMessage: (msg) => {
              setMessages((prev) => {
                // Deduplicate by seq
                if (prev.some((m) => m.seq === msg.seq)) return prev;
                return [...prev, msg];
              });
            },
            onDone: (data) => {
              setDone(true);
              setDoneStatus(data.status);
            },
            onError: () => {
              // SSE closed — fall back to polling
            },
          },
          lastSeq,
        );
        controllerRef.current = controller;
      })
      .catch(() => {
        // Ignore errors on initial load
      });

    return () => {
      cancelled = true;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [taskId]);

  return { messages, done, doneStatus };
}

// ---------------------------------------------------------------------------
// useActiveBackgroundTaskCount — for sidebar badge
// ---------------------------------------------------------------------------

export function useActiveBackgroundTaskCount() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const c = await getActiveBackgroundTaskCount();
        if (!cancelled) setCount(c);
      } catch (e) {
        swallow(e);
      }
    };

    // Delay the first poll so every workspace page mount doesn't
    // simultaneously fire this request during the already-busy startup
    // burst. 2s is imperceptible for a sidebar badge but cheap for the
    // gateway.
    const firstPoll = window.setTimeout(poll, 2000);
    // 15s is plenty for a passive badge; the old 5s created unnecessary
    // gateway pressure when multiple components instantiated this hook.
    const interval = setInterval(poll, 15000);

    return () => {
      cancelled = true;
      window.clearTimeout(firstPoll);
      clearInterval(interval);
    };
  }, []);

  return count;
}
