/** API client for the unified Task Board. */

import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";

import type {
  TaskBoardAllResponse,
  TaskBoardStats,
  TaskBoardTimelineResponse,
} from "./types";

const BASE = () => `${getBackendBaseURL()}/api/task-board`;

/**
 * Fetch all tasks in a unified format.
 */
export async function fetchAllTasks(params?: {
  type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<TaskBoardAllResponse> {
  const sp = new URLSearchParams();
  if (params?.type) sp.set("type", params.type);
  if (params?.status) sp.set("status", params.status);
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString();
  const url = `${BASE()}/all${qs ? `?${qs}` : ""}`;

  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to fetch tasks: ${res.statusText}`);
  return res.json() as Promise<TaskBoardAllResponse>;
}

/**
 * Fetch aggregate statistics.
 */
export async function fetchStats(): Promise<TaskBoardStats> {
  const res = await fetch(`${BASE()}/stats`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.statusText}`);
  return res.json() as Promise<TaskBoardStats>;
}

/**
 * Fetch tasks formatted for a timeline view.
 */
export async function fetchTimeline(params?: {
  type?: string;
  hours?: number;
}): Promise<TaskBoardTimelineResponse> {
  const sp = new URLSearchParams();
  if (params?.type) sp.set("type", params.type);
  if (params?.hours) sp.set("hours", String(params.hours));
  const qs = sp.toString();
  const url = `${BASE()}/timeline${qs ? `?${qs}` : ""}`;

  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to fetch timeline: ${res.statusText}`);
  return res.json() as Promise<TaskBoardTimelineResponse>;
}
