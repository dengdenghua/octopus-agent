import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteTask,
  listTasks,
  pauseTask,
  resumeTask,
  type PauseReason,
} from "./api";

const TASKS_KEY = ["tasks"] as const;

function tasksRefetchInterval(query: { state: { data?: { active?: Array<unknown>; pending?: Array<unknown> } } }) {
  const d = query.state.data;
  const hasHot = (d?.active?.length ?? 0) > 0 || (d?.pending?.length ?? 0) > 0;
  return hasHot ? 2000 : 5000;
}

export function useTasks(status?: "paused" | "pending" | "active" | "all") {
  const statusValue = status ?? "all";
  return useQuery({
    queryKey: [...TASKS_KEY, statusValue],
    queryFn: ({ signal }) => listTasks(statusValue, signal),
    refetchInterval: tasksRefetchInterval,
    refetchIntervalInBackground: true,
    staleTime: 2000,
    gcTime: 30000,
  });
}

export function usePauseTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      reason = "user_request",
      note = "",
    }: {
      taskId: string;
      reason?: PauseReason;
      note?: string;
    }) => pauseTask(taskId, reason, note),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TASKS_KEY });
    },
  });
}

export function useResumeTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      extra_iterations,
      extra_tokens,
      extra_usd,
    }: {
      taskId: string;
      extra_iterations?: number;
      extra_tokens?: number;
      extra_usd?: number;
    }) => resumeTask(taskId, { extra_iterations, extra_tokens, extra_usd }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TASKS_KEY });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId }: { taskId: string }) => deleteTask(taskId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TASKS_KEY });
    },
  });
}
