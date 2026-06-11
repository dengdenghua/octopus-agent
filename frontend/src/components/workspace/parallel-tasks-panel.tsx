import { Loader2Icon, PlayIcon, XIcon, CheckCircle2Icon, AlertCircleIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";
import { cn } from "@/lib/utils";

interface ParallelTask {
  id: string;
  prompt: string;
  agent_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  result: string;
  error: string;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  workspace_path: string;
}

export function ParallelTasksPanel({
  workspacePath,
  onSubmit,
  className,
}: {
  workspacePath: string;
  onSubmit?: (prompt: string) => void;
  className?: string;
}) {
  const [tasks, setTasks] = useState<ParallelTask[]>([]);
  const [input, setInput] = useState("");

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/tasks?workspace_path=${encodeURIComponent(workspacePath)}`,
        { headers: authHeaders() },
      );
      const data = await res.json();
      setTasks(data.tasks ?? []);
    } catch (e) { swallow(e); }
  }, [workspacePath]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  const submit = useCallback(async () => {
    if (!input.trim()) return;
    try {
      await fetch(`${getBackendBaseURL()}/api/tasks/submit`, {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: input.trim(),
          workspace_path: workspacePath,
          agent_id: "coder",
        }),
      });
      setInput("");
      onSubmit?.(input.trim());
      setTimeout(refresh, 500);
    } catch (e) { swallow(e); }
  }, [input, workspacePath, onSubmit, refresh]);

  const cancel = useCallback(async (taskId: string) => {
    try {
      await fetch(`${getBackendBaseURL()}/api/tasks/${taskId}/cancel`, {
        method: "POST",
        headers: authHeaders(),
      });
      setTimeout(refresh, 300);
    } catch (e) { swallow(e); }
  }, [refresh]);

  const statusIcon = (status: ParallelTask["status"]) => {
    switch (status) {
      case "queued": return <Loader2Icon className="size-3 text-muted-foreground" />;
      case "running": return <Loader2Icon className="size-3 animate-spin text-primary" />;
      case "completed": return <CheckCircle2Icon className="size-3 text-green-500" />;
      case "failed": return <AlertCircleIcon className="size-3 text-red-500" />;
      case "cancelled": return <XIcon className="size-3 text-muted-foreground" />;
    }
  };

  return (
    <div className={cn("flex flex-col gap-2 p-3", className)}>
      <div className="flex items-center gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="New parallel task..."
          className="flex-1 rounded-md border border-border/50 bg-muted/30 px-2 py-1 text-xs outline-none focus:border-primary/50"
        />
        <Button size="sm" variant="ghost" className="h-7 gap-1 text-xs" onClick={submit}>
          <PlayIcon className="size-3" />
          Run
        </Button>
      </div>

      {tasks.length === 0 ? (
        <p className="text-muted-foreground text-xs text-center py-4">No parallel tasks yet</p>
      ) : (
        <div className="flex flex-col gap-1.5 max-h-[400px] overflow-y-auto">
          {tasks.map((task) => (
            <div key={task.id} className="flex items-start gap-2 rounded-md border border-border/30 bg-muted/10 p-2">
              {statusIcon(task.status)}
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate">{task.prompt}</p>
                {task.error && <p className="text-[10px] text-red-500 mt-0.5">{task.error}</p>}
                {task.result && task.status === "completed" && (
                  <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">{task.result}</p>
                )}
              </div>
              {(task.status === "queued" || task.status === "running") && (
                <button
                  type="button"
                  onClick={() => cancel(task.id)}
                  className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                >
                  <XIcon className="size-3" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
