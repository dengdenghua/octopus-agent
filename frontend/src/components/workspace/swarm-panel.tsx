/* Implementation note. */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ActivityIcon,
  BotIcon,
  CheckCircle2Icon,
  CircleDotIcon,
  Loader2Icon,
  NetworkIcon,
  XCircleIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

type StatusEntry = { icon: ReactNode; className: string; label: string };
type StatusKey = "pending" | "running" | "completed" | "failed";

interface AgentTask {
  id: string;
  agent_name: string;
  goal: string;
  status: "pending" | "running" | "completed" | "failed";
  progress?: number;
}

interface SwarmState {
  status: string;
  tasks: AgentTask[];
}

function authHeaders(): Record<string, string> {
  if (typeof window === "undefined" || import.meta.env.MODE === "test")
    return {};
  const token = window.localStorage.getItem("octopus:token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function SwarmPanel() {
  const { t } = useI18n();
  const [swarmState, setSwarmState] = useState<SwarmState | null>(null);
  const [loading, setLoading] = useState(true);

  // Status config lives inside the component so the icons read from the
  // current theme and the labels resolve against the active locale.
  // Fallback to the `pending` entry when an unknown status shows up.
  const STATUS_CONFIG: Record<StatusKey, StatusEntry> = useMemo(
    () => ({
      pending: {
        icon: <CircleDotIcon className="h-4 w-4 text-muted-foreground" />,
        className: "bg-gray-500/10 text-gray-600",
        label: t.swarmPanel.panelStatusPending,
      },
      running: {
        icon: <ActivityIcon className="h-4 w-4 text-blue-500 animate-pulse" />,
        className: "bg-blue-500/10 text-blue-600",
        label: t.swarmPanel.panelStatusRunning,
      },
      completed: {
        icon: <CheckCircle2Icon className="h-4 w-4 text-green-500" />,
        className: "bg-green-500/10 text-green-600",
        label: t.swarmPanel.panelStatusCompleted,
      },
      failed: {
        icon: <XCircleIcon className="h-4 w-4 text-red-500" />,
        className: "bg-red-500/10 text-red-600",
        label: t.swarmPanel.panelStatusFailed,
      },
    }),
    [t],
  );
  const statusConfig = useCallback(
    (status: string): StatusEntry =>
      (STATUS_CONFIG as Record<string, StatusEntry>)[status] ??
      STATUS_CONFIG.pending,
    [STATUS_CONFIG],
  );

  const loadData = useCallback(async () => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/swarm/status`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error("Failed to fetch swarm status");
      const data = await res.json();
      setSwarmState(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.swarmPanel.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData]);

  // IMPORTANT: hooks must come BEFORE any early return. The previous
  // version had ``if (loading) return <Loader />`` above this
  // ``useMemo`` · which violates the Rules of Hooks: on the first
  // render the memo was skipped, on the second (loading=false) it
  // ran, and React threw "Rendered more hooks than during the
  // previous render". Hoisting the memo fixes the crash.
  const tasks = swarmState?.tasks ?? [];
  const stats = useMemo(
    () => ({
      total: tasks.length,
      running: tasks.filter((t) => t.status === "running").length,
      completed: tasks.filter((t) => t.status === "completed").length,
      failed: tasks.filter((t) => t.status === "failed").length,
    }),
    [tasks],
  );

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2Icon className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Empty state · swarm is idle with no tasks. Without this the
  // page renders 4 zero-count cards and an empty list — looks
  // broken on first visit before any swarm has run.
  if (tasks.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
        <div className="rounded-xl bg-gradient-to-br from-blue-500/10 to-cyan-500/5 p-3 text-blue-600 dark:text-blue-400">
          <NetworkIcon className="h-5 w-5" />
        </div>
        <div className="space-y-1">
          <div className="font-medium">{t.swarmPanel.noSwarmTasksTitle}</div>
          <p className="max-w-sm text-sm leading-6 text-muted-foreground">
            {t.swarmPanel.noSwarmTasksHint}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Implementation note. */}
      <div className="grid gap-3 sm:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.swarmPanel.statTotal}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.swarmPanel.statRunning}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {stats.running}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.swarmPanel.statCompleted}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {stats.completed}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.swarmPanel.statFailed}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">
              {stats.failed}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Implementation note. */}
      <section>
        <h3 className="mb-4 text-lg font-semibold flex items-center gap-2">
          <NetworkIcon className="h-5 w-5 text-primary" />
          {t.swarmPanel.taskListHeader}
        </h3>
        <div className="space-y-3">
          {tasks.map((task) => (
            <Card key={task.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <BotIcon className="h-4 w-4 text-muted-foreground" />
                    <CardTitle className="text-base">
                      {task.agent_name}
                    </CardTitle>
                  </div>
                  {(() => {
                    const sc = statusConfig(task.status);
                    return (
                      <Badge className={sc.className}>
                        {sc.icon}
                        <span className="ml-1">{sc.label}</span>
                      </Badge>
                    );
                  })()}
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-2">
                  {task.goal}
                </p>
                {task.progress !== undefined && (
                  <Progress value={task.progress} className="h-2" />
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
