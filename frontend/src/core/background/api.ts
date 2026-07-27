/** API client for the Background Tasks subsystem. */

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { openSseStream } from "@/core/streaming/sse";

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
 * The stream is reconnectable: the shared SSE transport auto-retries
 * with backoff and forwards the last seen event id as Last-Event-ID so
 * the server can resume from the correct offset.
 *
 * Returns an AbortController to close the stream.
 */
export function connectOutputSSE(
  taskId: string,
  callbacks: OutputStreamCallbacks,
  _lastSeq = -1,
): AbortController {
  const controller = new AbortController();
  let lastEventId: string | null = null;

  openSseStream({
    url: `${BASE()}/tasks/${taskId}/output`,
    signal: controller.signal,
    lastEventId: () => lastEventId,
    onEvent: (msg) => {
      if (msg.id != null) lastEventId = msg.id;
      if (msg.event === "output") {
        try {
          callbacks.onMessage(JSON.parse(msg.data) as BackgroundTaskOutput);
        } catch (e) {
          swallow(e);
        }
        return;
      }
      if (msg.event === "done") {
        try {
          callbacks.onDone(
            JSON.parse(msg.data) as {
              task_id: string;
              status: string;
              error: string | null;
            },
          );
        } catch (e) {
          swallow(e);
        }
        return true;
      }
      if (msg.event === "timeout") {
        return true;
      }
    },
    onError: (err) => {
      callbacks.onError?.(err);
    },
  });

  return controller;
}
