import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type { Subtask } from "./types";

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: (
    tasks:
      | Record<string, Subtask>
      | ((prev: Record<string, Subtask>) => Record<string, Subtask>),
  ) => void;
}

const NOOP_CONTEXT: SubtaskContextValue = {
  tasks: {},
  setTasks: () => {
    throw new Error("useSubtaskContext must be used within a SubtaskContext.Provider");
  },
};

export const SubtaskContext = createContext<SubtaskContextValue>(NOOP_CONTEXT);

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  const value = useMemo(() => ({ tasks, setTasks }), [tasks, setTasks]);
  return (
    <SubtaskContext.Provider value={value}>
      {children}
    </SubtaskContext.Provider>
  );
}

export function useSubtaskContext() {
  return useContext(SubtaskContext);
}

export function useSubtask(id: string) {
  const { tasks } = useSubtaskContext();
  return tasks[id];
}

export function useUpdateSubtask() {
  const { setTasks } = useSubtaskContext();
  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      setTasks((prevTasks) => {
        const existing = prevTasks[task.id];
        const merged = { ...(existing ?? {}), ...task } as Subtask;

        if (task.latestMessage) {
          const prev = existing?.messages ?? [];
          const isDup = prev.some(
            (m) => m.id && m.id === task.latestMessage!.id,
          );
          if (!isDup) {
            merged.messages = [...prev, task.latestMessage];
          }
        }

        return { ...prevTasks, [task.id]: merged };
      });
    },
    [setTasks],
  );
  return updateSubtask;
}
