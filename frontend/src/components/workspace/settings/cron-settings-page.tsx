import {
  AlertCircleIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  ClockIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { SettingsSection } from "./settings-section";

interface CronJob {
  name: string;
  command: string;
  cron_expression?: string;
  last_run?: string;
  last_status?: string;
}

export function CronSettingsPage() {
  const { t } = useI18n();
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCommand, setNewCommand] = useState("");
  const [newCron, setNewCron] = useState("0 * * * *");

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/cron/`, {
        credentials: "include",
        headers: authHeaders(),
      });
      if (res.status === 401 || res.status === 403) {
        setJobs([]);
        setNeedsAuth(true);
        setLoadError(null);
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load cron jobs: ${res.status}`);
      }
      const data = await res.json();
      setJobs(Array.isArray(data) ? data : []);
      setNeedsAuth(false);
      setLoadError(null);
    } catch (error) {
      console.error(error);
      setLoadError(
        error instanceof Error ? error.message : t.cronSettings.loadFailed,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const handleAdd = async () => {
    if (!newName || !newCommand) return;
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/cron/`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        credentials: "include",
        body: JSON.stringify({
          name: newName,
          command: newCommand,
          cron_expression: newCron,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Create failed: ${res.status}`);
      }
      setNewName("");
      setNewCommand("");
      setNewCron("0 * * * *");
      setShowAdd(false);
      toast.success(t.cronSettings.createSuccess);
      void fetchJobs();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.cronSettings.createFailed,
      );
    }
  };

  const handleDelete = async (name: string) => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/cron/${name}`, {
        method: "DELETE",
        credentials: "include",
        headers: authHeaders(),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Delete failed: ${res.status}`);
      }
      toast.success(t.cronSettings.deleteSuccess);
      void fetchJobs();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.cronSettings.deleteFailed,
      );
    }
  };

  return (
    <div className="space-y-4">
      <SettingsSection
        title={t.cronSettings.title}
        description={t.cronSettings.description}
      >
        <div className="mb-3 flex items-center justify-end">
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            disabled={loading}
            onClick={fetchJobs}
          >
            {loading ? (
              <Loader2Icon className="size-3.5 animate-spin" />
            ) : (
              <RefreshCwIcon className="size-3.5" />
            )}
            {t.taskBoard.refresh}
          </Button>
        </div>

        <div className="space-y-2">
          {loading && jobs.length === 0 ? (
            <div className="flex items-center justify-center rounded-lg border border-border/60 bg-card/40 py-8 text-sm text-muted-foreground">
              <Loader2Icon className="mr-2 size-4 animate-spin" />
              {t.cronSettings.title}
            </div>
          ) : needsAuth ? (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-3 text-sm text-amber-700 dark:text-amber-300">
              <AlertCircleIcon className="mr-2 inline-block size-4" />
              定时任务涉及本机命令执行，需要登录或授权后管理。
            </div>
          ) : loadError ? (
            <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-3 text-sm text-destructive">
              <AlertCircleIcon className="mr-2 inline-block size-4" />
              {t.cronSettings.loadFailed}
              <Button
                variant="ghost"
                size="sm"
                className="ml-2 h-7 px-2"
                onClick={fetchJobs}
              >
                {t.taskBoard.refresh}
              </Button>
            </div>
          ) : (
            jobs.map((job) => (
              <div
                key={job.name}
                className="flex items-center justify-between rounded-lg border p-3"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <ClockIcon className="size-4 text-muted-foreground" />
                    <span className="font-medium">{job.name}</span>
                    {job.cron_expression && (
                      <code className="text-xs text-muted-foreground">
                        {job.cron_expression}
                      </code>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1 pl-6">
                    {job.command}
                  </div>
                  {job.last_status && (
                    <div className="text-xs text-muted-foreground mt-0.5 pl-6">
                      {t.cronSettings.last}: {job.last_status}
                    </div>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(job.name)}
                >
                  <Trash2Icon className="size-4 text-destructive" />
                </Button>
              </div>
            ))
          )}
          {!loading && !needsAuth && !loadError && jobs.length === 0 && (
            <div className="text-sm text-muted-foreground text-center py-4">
              {t.cronSettings.noTasks}
            </div>
          )}
        </div>

        {showAdd ? (
          <div className="space-y-2 rounded-lg border p-3 mt-3">
            <Input
              placeholder={t.cronSettings.jobName}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <Input
              placeholder={t.cronSettings.commandToRun}
              value={newCommand}
              onChange={(e) => setNewCommand(e.target.value)}
            />
            <Input
              placeholder={t.cronSettings.cronExpression}
              value={newCron}
              onChange={(e) => setNewCron(e.target.value)}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleAdd}>
                {t.cronSettings.create}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowAdd(false)}
              >
                {t.cronSettings.cancel}
              </Button>
            </div>
          </div>
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            disabled={needsAuth}
            onClick={() => setShowAdd(true)}
          >
            <PlusIcon className="size-4 mr-1" /> {t.cronSettings.addTask}
          </Button>
        )}
      </SettingsSection>
    </div>
  );
}
