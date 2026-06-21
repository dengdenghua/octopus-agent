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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  const [fieldErrors, setFieldErrors] = useState<{
    name?: string;
    command?: string;
    cron?: string;
  }>({});
  const [submitting, setSubmitting] = useState(false);
  const [taskToDelete, setTaskToDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const validate = useCallback(
    (values: { name: string; command: string; cron: string }) => {
      const errors: { name?: string; command?: string; cron?: string } = {};
      const name = values.name.trim();
      const command = values.command.trim();
      const cron = values.cron.trim();
      if (!name) errors.name = t.cronSettings.nameRequired;
      if (!command) errors.command = t.cronSettings.commandRequired;
      if (!cron) {
        errors.cron = t.cronSettings.cronRequired;
      } else if (!/^\S+\s+\S+\s+\S+\s+\S+\s+\S+$/.test(cron)) {
        errors.cron = t.cronSettings.cronInvalid;
      }
      return errors;
    },
    [
      t.cronSettings.commandRequired,
      t.cronSettings.cronInvalid,
      t.cronSettings.cronRequired,
      t.cronSettings.nameRequired,
    ],
  );

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
  }, [t.cronSettings.loadFailed]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const handleAdd = async () => {
    const values = { name: newName, command: newCommand, cron: newCron };
    const errors = validate(values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/cron/`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        credentials: "include",
        body: JSON.stringify({
          name: values.name.trim(),
          command: values.command.trim(),
          cron_expression: values.cron.trim(),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Create failed: ${res.status}`);
      }
      setNewName("");
      setNewCommand("");
      setNewCron("0 * * * *");
      setFieldErrors({});
      setShowAdd(false);
      toast.success(t.cronSettings.createSuccess);
      void fetchJobs();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.cronSettings.createFailed,
      );
    } finally {
      setSubmitting(false);
    }
  };

  const doDeleteTask = async (name: string) => {
    setDeleting(true);
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
    } finally {
      setDeleting(false);
    }
  };

  const handleDelete = (name: string) => {
    setTaskToDelete(name);
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
              {t.cronSettings.needsAuth}
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
            <div>
              <Input
                placeholder={t.cronSettings.jobName}
                value={newName}
                onChange={(e) => {
                  setNewName(e.target.value);
                  if (fieldErrors.name) {
                    setFieldErrors((prev) => ({ ...prev, name: undefined }));
                  }
                }}
                aria-invalid={!!fieldErrors.name}
              />
              {fieldErrors.name && (
                <p className="mt-1 text-xs text-destructive">
                  {fieldErrors.name}
                </p>
              )}
            </div>
            <div>
              <Input
                placeholder={t.cronSettings.commandToRun}
                value={newCommand}
                onChange={(e) => {
                  setNewCommand(e.target.value);
                  if (fieldErrors.command) {
                    setFieldErrors((prev) => ({ ...prev, command: undefined }));
                  }
                }}
                aria-invalid={!!fieldErrors.command}
              />
              {fieldErrors.command && (
                <p className="mt-1 text-xs text-destructive">
                  {fieldErrors.command}
                </p>
              )}
            </div>
            <div>
              <Input
                placeholder={t.cronSettings.cronExpression}
                value={newCron}
                onChange={(e) => {
                  setNewCron(e.target.value);
                  if (fieldErrors.cron) {
                    setFieldErrors((prev) => ({ ...prev, cron: undefined }));
                  }
                }}
                aria-invalid={!!fieldErrors.cron}
              />
              {fieldErrors.cron && (
                <p className="mt-1 text-xs text-destructive">
                  {fieldErrors.cron}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleAdd} disabled={submitting}>
                {submitting ? (
                  <Loader2Icon className="mr-1.5 size-3.5 animate-spin" />
                ) : null}
                {submitting ? t.common.loading : t.cronSettings.create}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowAdd(false)}
                disabled={submitting}
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

      <Dialog
        open={taskToDelete !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setTaskToDelete(null);
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="w-[min(360px,calc(100vw-2rem))] gap-3 rounded-lg p-4 shadow-xl sm:max-w-[360px]"
        >
          <DialogHeader className="gap-1 text-left">
            <DialogTitle className="text-[15px]">
              {t.cronSettings.deleteConfirmTitle}
            </DialogTitle>
            <DialogDescription className="text-[12.5px] leading-5">
              {taskToDelete
                ? t.cronSettings.deleteConfirmDescription(taskToDelete)
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-1 flex-row justify-end gap-2">
            <button
              type="button"
              disabled={deleting}
              onClick={() => setTaskToDelete(null)}
              className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-background px-3 text-[12.5px] font-medium text-foreground/80 transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-60"
            >
              {t.common.cancel}
            </button>
            <button
              type="button"
              disabled={deleting}
              onClick={() => {
                if (!taskToDelete) return;
                const target = taskToDelete;
                setTaskToDelete(null);
                void doDeleteTask(target);
              }}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-destructive/25 bg-destructive/[0.07] px-3 text-[12.5px] font-medium text-destructive transition-colors hover:border-destructive/35 hover:bg-destructive/[0.11] disabled:pointer-events-none disabled:opacity-60"
            >
              {deleting ? (
                <span className="size-3 animate-spin rounded-full border border-current border-t-transparent" />
              ) : (
                <Trash2Icon className="size-3.5" />
              )}
              {t.common.delete}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
