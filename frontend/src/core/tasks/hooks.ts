import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteTask,
  listTasks,
  pauseTask,
  resumeTask,
  type PauseReason,
} from "./api";

const TASKS_KEY = ["tasks"] as const;

export function useTasks(status?: "paused" | "pending" | "active" | "all") {
  return useQuery({
    queryKey: [...TASKS_KEY, status ?? "all"],
    queryFn: () => listTasks(status),
    // Implementation note.
    // Implementation note.
    // Implementation note.
    refetchInterval: (query) => {
      const d = query.state.data;
      const hasHot =
        (d?.active?.length ?? 0) > 0 || (d?.pending?.length ?? 0) > 0;
      return hasHot ? 1500 : 5000;
    },
    // Implementation note.
    // Implementation note.
    refetchIntervalInBackground: true,
    staleTime: 1000,
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
