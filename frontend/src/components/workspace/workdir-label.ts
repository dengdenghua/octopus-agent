import { basename } from "@/lib/path-utils";
import type { Project } from "@/core/projects/hooks";

export function managedWorkdirThreadId(path: string): string | undefined {
  return path.trim().replace(/\\/g, "/").replace(/\/+$/, "")
    .match(/(?:^|\/)data\/workspaces\/[a-f0-9]{24}\/[a-f0-9]{24}\/([^/]+)$/i)?.[1];
}

export function workdirDisplayName(path: string, projects: Project[], fallback: string): string {
  const threadId = managedWorkdirThreadId(path);
  if (!threadId) return path ? basename(path) : "";
  const project = projects.find((item) => item.execution_thread_id === threadId || item.thread_ids?.includes(threadId));
  return project?.name?.trim() || fallback;
}
