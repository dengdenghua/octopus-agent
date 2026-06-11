import { Loader2Icon, SendIcon, UsersIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";

import { ModelPicker } from "../model-picker";
import { dispatchParallel, splitTask } from "@/core/parallel-agents/api";
import { cn } from "@/lib/utils";

import { useSwarm } from "./swarm-context";

// Fallback model name if the models list hasn't loaded yet. Matches
// config.yaml's default_model setting.
const DEFAULT_MODEL = "claude-opus";

interface Props {
  className?: string;
  onLaunched?: (batchId: string) => void;
  initialPrompt?: string;
}

/**
 * Input box that actually kicks off a new swarm batch on the backend and
 * subscribes the workbench to its SSE stream — not a mock. Once the backend
 * returns a batch_id, we hand off to SwarmProvider.connectBatch(), which
 * listens to /api/agents/parallel/stream/:id and populates the session
 * from real task_update / batch_complete events.
 */
export function DispatchComposer({ className, onLaunched, initialPrompt }: Props) {
  const { t } = useI18n();
  const { connectBatch, openPanel, session } = useSwarm();
  const [prompt, setPrompt] = useState(initialPrompt ?? "");
  const [maxConcurrency, setMaxConcurrency] = useState(4);
  const [autoSplit, setAutoSplit] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [stage, setStage] = useState<"idle" | "splitting" | "dispatching">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const { models } = useModels();
  const [modelName, setModelName] = useState<string>(DEFAULT_MODEL);

  // Once the models list resolves, switch the default if it isn't present.
  useEffect(() => {
    if (models.length === 0) return;
    if (!models.find((m) => m.name === modelName)) {
      setModelName(models[0]!.name);
    }
  }, [models, modelName]);

  useEffect(() => {
    if (initialPrompt) {
      setPrompt(initialPrompt);
    }
  }, [initialPrompt]);

  const connectedBatchId = session.id !== "idle" && session.agents.length > 0
    ? session.id
    : null;

  const handleLaunch = async () => {
    const task = prompt.trim();
    if (!task) return;
    setLaunching(true);
    setError(null);

    let tasks: Array<{ description: string; subagent_name?: string }> = [
      { description: task, subagent_name: "general-purpose" },
    ];

    if (autoSplit) {
      setStage("splitting");
      const split = await splitTask(task, {
        max_subtasks: maxConcurrency,
        model_name: modelName,
      });
      if (split && split.tasks.length > 0) {
        tasks = split.tasks.map((t) => ({
          description: t.description,
          subagent_name: t.subagent_name,
        }));
      }
      // If split fails, silently fall back to single-task dispatch.
    }

    setStage("dispatching");
    const res = await dispatchParallel(tasks, {
      max_concurrency: maxConcurrency,
      model_name: modelName,
    });
    setStage("idle");
    setLaunching(false);
    if (!res) {
      setError(t.dispatchComposer.dispatchFailed);
      return;
    }
    connectBatch(res.batch_id);
    openPanel();
    onLaunched?.(res.batch_id);
    setPrompt("");
  };

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-border bg-card p-3",
        className,
      )}
    >
      <div className="flex items-center gap-2 text-xs font-medium">
        <UsersIcon className="size-3.5 text-muted-foreground" />
        <span>{t.dispatchComposer.title}</span>
        {connectedBatchId && (
          <span className="ml-auto flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
            <span className="size-1.5 rounded-lg bg-emerald-500 animate-pulse" />
            {t.dispatchComposer.connectedBatch(connectedBatchId)}
          </span>
        )}
      </div>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void handleLaunch();
          }
        }}
        placeholder={t.dispatchComposer.placeholder}
        rows={3}
        className="resize-none rounded-lg bg-transparent p-2 text-sm outline-none placeholder:text-muted-foreground/50"
      />
      <div className="flex items-center gap-2 text-xs">
        <label className="flex items-center gap-1.5 text-muted-foreground">
          {t.dispatchComposer.concurrency}
          <input
            type="number"
            min={1}
            max={20}
            value={maxConcurrency}
            onChange={(e) => setMaxConcurrency(Number(e.target.value) || 4)}
            className="w-12 rounded border border-border bg-background px-1.5 py-0.5 text-center"
          />
        </label>
        <label className="flex items-center gap-1.5 text-muted-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={autoSplit}
            onChange={(e) => setAutoSplit(e.target.checked)}
            className="size-3"
          />
          {t.dispatchComposer.autoSplit}
        </label>
        <label className="flex items-center gap-1.5 text-muted-foreground">
          {t.common.model}
          <ModelPicker
            models={models.length > 0 ? models : [{ name: DEFAULT_MODEL, display_name: DEFAULT_MODEL }]}
            value={modelName}
            onChange={setModelName}
          />
        </label>
        <div className="flex-1" />
        {error && (
          <span className="text-xs text-red-500 truncate max-w-xs">{error}</span>
        )}
        <button
          type="button"
          onClick={handleLaunch}
          disabled={launching || !prompt.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-sm disabled:opacity-60"
        >
          {launching ? (
            <>
              <Loader2Icon className="size-3 animate-spin" />
              {stage === "splitting"
                ? t.dispatchComposer.splitting
                : stage === "dispatching"
                  ? t.dispatchComposer.dispatching
                  : t.dispatchComposer.processing}
            </>
          ) : (
            <>
              <SendIcon className="size-3" />
              {t.dispatchComposer.dispatchButton}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
