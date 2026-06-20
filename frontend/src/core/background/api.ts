/** API client for the Background Tasks subsystem. */

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";

import type {
  BackgroundTask,
  BackgroundTaskOutput,
  SubmitBackgroundTaskRequest,
} from "./types";

const BASE = () => `${getBackendBaseURL()}/api/background`;

// ---------------------------------------------------------------------------
// Task CRUD
// ---------------------------------------------------------------------------

export async function submitBackgroundTask(
  req: SubmitBackgroundTaskRequest,
): Promise<BackgroundTask> {
  const res = await fetch(`${BASE()}/submit`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      (err as { detail?: string }).detail ??
        `Failed to submit task: ${res.statusText}`,
    );
  }
  return res.json() as Promise<BackgroundTask>;
}

export async function listBackgroundTasks(
  status?: string,
): Promise<BackgroundTask[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`${BASE()}/tasks${qs}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to list tasks: ${res.statusText}`);
  return res.json() as Promise<BackgroundTask[]>;
}

export async function getBackgroundTask(
  taskId: string,
): Promise<BackgroundTask> {
  const res = await fetch(`${BASE()}/tasks/${taskId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Task '${taskId}' not found`);
  return res.json() as Promise<BackgroundTask>;
}

export async function pauseBackgroundTask(
  taskId: string,
): Promise<BackgroundTask> {
  const res = await fetch(`${BASE()}/tasks/${taskId}/pause`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to pause task: ${res.statusText}`);
  return res.json() as Promise<BackgroundTask>;
}

export async function resumeBackgroundTask(
  taskId: string,
): Promise<BackgroundTask> {
  const res = await fetch(`${BASE()}/tasks/${taskId}/resume`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to resume task: ${res.statusText}`);
  return res.json() as Promise<BackgroundTask>;
}

export async function cancelBackgroundTask(
  taskId: string,
): Promise<BackgroundTask> {
  const res = await fetch(`${BASE()}/tasks/${taskId}/cancel`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to cancel task: ${res.statusText}`);
  return res.json() as Promise<BackgroundTask>;
}

export async function deleteBackgroundTask(taskId: string): Promise<void> {
  const res = await fetch(`${BASE()}/tasks/${taskId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to delete task: ${res.statusText}`);
}

// ---------------------------------------------------------------------------
// Output polling (fallback for non-SSE clients)
// ---------------------------------------------------------------------------

export async function pollBackgroundTaskOutput(
  taskId: string,
  since = 0,
  limit = 200,
): Promise<BackgroundTaskOutput[]> {
  const res = await fetch(
    `${BASE()}/tasks/${taskId}/output/poll?since=${since}&limit=${limit}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to poll output: ${res.statusText}`);
  return res.json() as Promise<BackgroundTaskOutput[]>;
}

// ---------------------------------------------------------------------------
// Active count (for badge)
// ---------------------------------------------------------------------------

export async function getActiveBackgroundTaskCount(): Promise<number> {
  const res = await fetch(`${BASE()}/active-count`, {
    headers: authHeaders(),
  });
  if (!res.ok) return 0;
  const data = (await res.json()) as { count: number };
  return data.count;
}

// ---------------------------------------------------------------------------
// SSE output stream (reconnectable)
// ---------------------------------------------------------------------------

export interface OutputStreamCallbacks {
  onMessage: (msg: BackgroundTaskOutput) => void;
  onDone: (data: {
    task_id: string;
    status: string;
    error: string | null;
  }) => void;
  onError?: (err: Error) => void;
}

/**
 * Connect to a background task's SSE output stream.
 *
 * The stream is reconnectable: on disconnect, the browser automatically
 * sends Last-Event-ID so the server can resume from the correct offset.
 *
 * Returns an AbortController to close the stream.
 */
export function connectOutputSSE(
  taskId: string,
  callbacks: OutputStreamCallbacks,
  _lastSeq = -1,
): AbortController {
  const controller = new AbortController();
  const url = `${BASE()}/tasks/${taskId}/output`;

  const connect = () => {
    const eventSource = new EventSource(url);

    eventSource.addEventListener("output", (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data) as BackgroundTaskOutput;
        callbacks.onMessage(msg);
      } catch (e) {
        swallow(e);
      }
    });

    eventSource.addEventListener("done", (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as {
          task_id: string;
          status: string;
          error: string | null;
        };
        callbacks.onDone(data);
      } catch (e) {
        swallow(e);
      }
      eventSource.close();
    });

    eventSource.addEventListener("timeout", () => {
      eventSource.close();
    });

    eventSource.onerror = () => {
      // EventSource auto-reconnects on most errors.
      // We only call onError for permanent failures.
      if (eventSource.readyState === EventSource.CLOSED) {
        callbacks.onError?.(new Error("SSE connection closed permanently"));
      }
    };

    // Close on abort
    controller.signal.addEventListener("abort", () => {
      eventSource.close();
    });
  };

  connect();
  return controller;
}
