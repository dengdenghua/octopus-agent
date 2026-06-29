import type { AgentRunState } from "@/components/workspace/agent-run-status";
import {
  isSubtaskActive,
  type Subtask,
  type SubtaskStatus,
} from "@/core/tasks/types";

export function subtaskRunState(status: SubtaskStatus): AgentRunState {
  if (status === "completed") return "done";
  if (status === "failed" || status === "timed_out" || status === "cancelled")
    return "error";
  if (status === "pending") return "waiting";
  if (isSubtaskActive(status)) return "running";
  return "pending";
}

export function subtaskProgress(
  task: Pick<Subtask, "status" | "progress">,
): number {
  if (
    task.status === "completed" ||
    task.status === "failed" ||
    task.status === "cancelled" ||
    task.status === "timed_out"
  ) {
    return 1;
  }
  if (task.status === "pending") return 0.08;
  return Math.max(0.18, Math.min(0.92, task.progress || 0.45));
}
