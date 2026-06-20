"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  InfoIcon,
  Loader2Icon,
  RefreshCwIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { cn } from "@/lib/utils";
import type { PreviewDiagnostic } from "./live-preview-panel";

interface SessionInfo {
  thread_id: string;
  workspace_path: string;
  workspace_exists: boolean;
  workspace_resolved: string | null;
  project: { kind: string; checks: string[] };
  rules_file: string | null;
  git_initialized: boolean;
  thread_metadata: {
    mode: string | null;
    sandbox_mode: string | null;
    workspace_path: string | null;
    extra_workspaces: string[] | null;
    agent_name: string | null;
  } | null;
  write_scope: {
    mode: string;
    roots: string[];
    requested_mode: string;
    error?: string;
  } | null;
  server_cwd: string;
  python_executable: string;
}

interface DiagnosticsPanelProps {
  threadId: string;
  workDir: string;
  previewDiagnostics?: PreviewDiagnostic[];
  className?: string;
}

export function DiagnosticsPanel({
  threadId,
  workDir,
  previewDiagnostics = [],
  className,
}: DiagnosticsPanelProps) {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const base = getBackendBaseURL();
      const params = new URLSearchParams({
        thread_id: threadId,
        workspace_path: workDir,
      });
      const res = await fetch(`${base}/api/debug/session-info?${params}`);
      if (res.ok) setInfo(await res.json());
    } catch (e) {
      swallow(e);
    }
    setLoading(false);
  }, [threadId, workDir]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className={cn("flex flex-col h-full", className)}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/50">
        <div className="flex items-center gap-2">
          <InfoIcon className="size-4 text-primary" />
          <span className="text-sm font-medium">Diagnostics</span>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        >
          {loading ? (
            <Loader2Icon className="size-3 animate-spin" />
          ) : (
            <RefreshCwIcon className="size-3" />
          )}
        </button>
      </div>

      <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
        {!info ? (
          <div className="flex items-center justify-center h-full text-muted-foreground/50">
            <Loader2Icon className="size-6 animate-spin" />
          </div>
        ) : (
          <>
            <Section title="Preview">
              {previewDiagnostics.length === 0 ? (
                <div className="flex items-center gap-1.5 text-[10px] text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2Icon className="size-3 shrink-0" />
                  No preview diagnostics reported
                </div>
              ) : (
                <div className="space-y-1">
                  {previewDiagnostics.map((item) => (
                    <PreviewDiagnosticRow key={item.id} item={item} />
                  ))}
                </div>
              )}
            </Section>

            <Section title="Workspace">
              <Row label="Path" value={info.workspace_path} />
              <Row label="Resolved" value={info.workspace_resolved ?? "—"} />
              <StatusRow label="Exists" ok={info.workspace_exists} />
              <StatusRow label="Git" ok={info.git_initialized} />
              <Row label="Rules" value={info.rules_file ?? "none"} />
            </Section>

            <Section title="Project">
              <Row label="Type" value={info.project.kind} />
              <Row
                label="Checks"
                value={info.project.checks.join(", ") || "none"}
              />
            </Section>

            {info.thread_metadata && (
              <Section title="Thread">
                <Row label="Mode" value={info.thread_metadata.mode ?? "—"} />
                <Row
                  label="Sandbox"
                  value={info.thread_metadata.sandbox_mode ?? "—"}
                />
                <Row
                  label="Agent"
                  value={info.thread_metadata.agent_name ?? "—"}
                />
                {info.thread_metadata.workspace_path && (
                  <Row
                    label="Persisted WD"
                    value={info.thread_metadata.workspace_path}
                  />
                )}
              </Section>
            )}

            {info.write_scope && (
              <Section title="Write Scope">
                {info.write_scope.error ? (
                  <div className="text-[10px] text-rose-500">
                    {info.write_scope.error}
                  </div>
                ) : (
                  <>
                    <Row label="Mode" value={info.write_scope.mode} />
                    <Row
                      label="Requested"
                      value={info.write_scope.requested_mode}
                    />
                    {info.write_scope.roots.map((r, i) => (
                      <Row
                        key={i}
                        label={i === 0 ? "Primary root" : `Root ${i + 1}`}
                        value={r}
                      />
                    ))}
                  </>
                )}
              </Section>
            )}

            <Section title="Server">
              <Row label="CWD" value={info.server_cwd} />
              <Row label="Python" value={info.python_executable} />
              {info.server_cwd !== info.workspace_path && (
                <div className="flex items-center gap-1.5 mt-1 text-[10px] text-amber-600 dark:text-amber-400">
                  <AlertTriangleIcon className="size-3 shrink-0" />
                  Server CWD differs from workspace
                </div>
              )}
            </Section>
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
        {title}
      </div>
      <div className="space-y-0.5 ml-1">{children}</div>
    </div>
  );
}

function PreviewDiagnosticRow({ item }: { item: PreviewDiagnostic }) {
  const isError = item.level === "error";
  return (
    <div
      className={cn(
        "rounded border px-2 py-1.5 text-[10px]",
        isError
          ? "border-rose-500/25 bg-rose-500/8"
          : "border-amber-500/25 bg-amber-500/8",
      )}
    >
      <div className="flex items-center gap-1.5">
        <AlertTriangleIcon
          className={cn(
            "size-3 shrink-0",
            isError ? "text-rose-500" : "text-amber-500",
          )}
        />
        <span
          className={cn(
            "font-medium uppercase",
            isError
              ? "text-rose-600 dark:text-rose-400"
              : "text-amber-600 dark:text-amber-400",
          )}
        >
          {item.source}
        </span>
        <span className="text-muted-foreground">
          {new Date(item.timestamp).toLocaleTimeString()}
        </span>
      </div>
      <div className="mt-1 break-words font-mono text-foreground/80">
        {item.message}
      </div>
      {item.stack && (
        <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-all text-muted-foreground">
          {item.stack}
        </pre>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-[10px]">
      <span className="text-muted-foreground shrink-0 w-20">{label}</span>
      <span className="font-mono text-foreground/80 break-all">{value}</span>
    </div>
  );
}

function StatusRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="text-muted-foreground shrink-0 w-20">{label}</span>
      {ok ? (
        <CheckCircle2Icon className="size-3 text-emerald-500" />
      ) : (
        <AlertTriangleIcon className="size-3 text-amber-500" />
      )}
      <span className={ok ? "text-emerald-600" : "text-amber-600"}>
        {ok ? "Yes" : "No"}
      </span>
    </div>
  );
}
