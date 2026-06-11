/**
 * Builder / Coder mode selector for Code mode.
 *
 * - Toggles between Builder (greenfield) and Coder (brownfield) modes.
 * - Auto-detects the recommended mode based on workspace contents.
 * - Shows mode-specific context (Builder -> templates, Coder -> project info).
 */

import {
  BuildingIcon,
  CodeIcon,
  HammerIcon,
  LoaderIcon,
  SparklesIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AgentModeName = "builder" | "coder" | "architect";

interface DetectionSignals {
  workspace_path?: string | null;
  exists?: boolean | null;
  file_count?: number | null;
  manifests?: string[] | null;
  structure_dirs?: string[] | null;
  git_commits?: number | null;
  has_readme?: boolean | null;
  lock_files?: string[] | null;
  raw_score?: number | null;
}

interface DetectResponse {
  recommended_mode: AgentModeName;
  confidence: number;
  reason: string;
  signals: DetectionSignals;
}

interface TemplateInfo {
  name: string;
  display_name: string;
  description: string;
  language: string;
  framework: string;
  tags: string[];
}

interface ModeInfo {
  name: AgentModeName;
  display_name: string;
  description: string;
  icon: string;
  templates?: TemplateInfo[] | null;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchDetection(workspacePath: string): Promise<DetectResponse> {
  const url = `${getBackendBaseURL()}/api/agent-modes/detect?workspace_path=${encodeURIComponent(workspacePath)}`;
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Detection failed: ${res.status}`);
  return res.json();
}

async function fetchModes(): Promise<ModeInfo[]> {
  const url = `${getBackendBaseURL()}/api/agent-modes`;
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Modes fetch failed: ${res.status}`);
  const data = (await res.json()) as { modes: ModeInfo[] };
  return data.modes;
}

async function setModeOnServer(
  mode: AgentModeName,
  sessionId: string,
): Promise<void> {
  const url = `${getBackendBaseURL()}/api/agent-modes/current`;
  await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ mode, session_id: sessionId }),
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ModeSelectorProps {
  workDir: string;
  sessionId: string;
  mode: AgentModeName;
  onModeChange: (mode: AgentModeName) => void;
  className?: string;
}

export function ModeSelector({
  workDir,
  sessionId,
  mode,
  onModeChange,
  className,
}: ModeSelectorProps) {
  const { t } = useI18n();
  const [detection, setDetection] = useState<DetectResponse | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const panelRef = useRef<HTMLDivElement>(null);
  const prevWorkDir = useRef(workDir);

  // Auto-detect on mount and when workDir changes
  useEffect(() => {
    if (!workDir) return;

    let cancelled = false;
    const doDetect = async () => {
      setDetecting(true);
      try {
        const result = await fetchDetection(workDir);
        if (cancelled) return;
        setDetection(result);

        // Only auto-switch on initial load or workspace change
        if (prevWorkDir.current !== workDir) {
          prevWorkDir.current = workDir;
          onModeChange(result.recommended_mode);
        }
      } catch (e) {
        swallow(e);
        // Silently fall back — keep current mode
      } finally {
        if (!cancelled) setDetecting(false);
      }
    };

    doDetect();
    return () => { cancelled = true; };
  }, [workDir]);

  // Fetch available modes (templates etc.)
  useEffect(() => {
    let cancelled = false;
    fetchModes()
      .then((m) => {
        if (!cancelled) setModes(m);
      })
      .catch(() => { /* ignore */ });
    return () => { cancelled = true; };
  }, []);

  // Close panel on outside click
  useEffect(() => {
    if (!expanded) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [expanded]);

  const handleToggle = useCallback(
    (newMode: AgentModeName) => {
      onModeChange(newMode);
      void setModeOnServer(newMode, sessionId);
      setExpanded(false);
    },
    [onModeChange, sessionId],
  );

  const isBuilder = mode === "builder";
  const isArchitect = mode === "architect";
  const modeInfo = modes.find((m) => m.name === mode);
  const builderTemplates = modes.find((m) => m.name === "builder")?.templates ?? [];

  const modeColorClass = isArchitect
    ? "bg-amber-500/15 text-amber-700 hover:bg-amber-500/25 dark:bg-amber-900/30 dark:text-amber-400"
    : isBuilder
      ? "bg-violet-500/15 text-violet-700 hover:bg-violet-500/25 dark:bg-violet-900/30 dark:text-violet-400"
      : "bg-sky-500/15 text-sky-700 hover:bg-sky-500/25 dark:bg-sky-900/30 dark:text-sky-400";

  return (
    <div ref={panelRef} className={cn("relative", className)}>
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all duration-200 ring-1",
          modeColorClass,
          isArchitect ? "ring-amber-500/20" : isBuilder ? "ring-violet-500/20" : "ring-sky-500/20",
        )}
        title={
          isBuilder
            ? t.modes.builderTooltip
            : t.modes.coderTooltip
        }
      >
        {detecting ? (
          <LoaderIcon className="size-3 animate-spin" />
        ) : isBuilder ? (
          <HammerIcon className="size-3" />
        ) : isArchitect ? (
          <BuildingIcon className="size-3" />
        ) : (
          <CodeIcon className="size-3" />
        )}
        {isArchitect ? (t.modes.architect ?? "Architect") : isBuilder ? t.modes.builder : t.modes.coder}
        {detection && (
          <span className="text-[9px] opacity-50">
            {detection.recommended_mode === mode ? "" : "(override)"}
          </span>
        )}
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="absolute top-full right-0 z-50 mt-1.5 w-80 overflow-hidden rounded-xl border bg-background shadow-xl ring-1 ring-border/30">
          <div className="flex gap-1 border-b p-2">
            <button
              onClick={() => handleToggle("builder")}
              className={cn(
                "flex flex-1 items-center gap-2 rounded-lg px-3 py-2 text-xs transition-all duration-200",
                mode === "builder"
                  ? "bg-violet-500/15 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300 ring-1 ring-violet-500/20"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              <HammerIcon className="size-4 shrink-0" />
              <div className="text-left">
                <div className="font-semibold">{t.modes.builder}</div>
                <div className="text-[10px] opacity-70">{t.modes.builderDesc}</div>
              </div>
            </button>

            <button
              onClick={() => handleToggle("coder")}
              className={cn(
                "flex flex-1 items-center gap-2 rounded-lg px-3 py-2 text-xs transition-all duration-200",
                mode === "coder"
                  ? "bg-sky-500/15 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300 ring-1 ring-sky-500/20"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              <CodeIcon className="size-4 shrink-0" />
              <div className="text-left">
                <div className="font-semibold">{t.modes.coder}</div>
                <div className="text-[10px] opacity-70">{t.modes.coderDesc}</div>
              </div>
            </button>

            <button
              onClick={() => handleToggle("architect")}
              className={cn(
                "flex flex-1 items-center gap-2 rounded-lg px-3 py-2 text-xs transition-all duration-200",
                mode === "architect"
                  ? "bg-amber-500/15 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 ring-1 ring-amber-500/20"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              <BuildingIcon className="size-4 shrink-0" />
              <div className="text-left">
                <div className="font-semibold">{t.modes.architect ?? "Architect"}</div>
                <div className="text-[10px] opacity-70">{t.modes.architectDesc ?? "Safe system integration"}</div>
              </div>
            </button>
          </div>

          {/* Detection info */}
          {detection && (
            <div className="border-b px-3 py-2">
              <div className="flex items-center gap-1.5 text-[10px]">
                <SparklesIcon className="size-3 text-amber-500" />
                <span className="font-medium text-muted-foreground">{t.modes.autoDetected}:</span>
                <span className={cn(
                  "font-semibold",
                  detection.recommended_mode === "builder" ? "text-violet-600" : "text-sky-600",
                )}>
                  {detection.recommended_mode === "builder" ? t.modes.builder : t.modes.coder}
                </span>
                <span className="text-muted-foreground">
                  ({Math.round(detection.confidence * 100)}%)
                </span>
              </div>
              <p className="mt-0.5 text-[10px] text-muted-foreground leading-tight">
                {detection.reason}
              </p>
              {/* Signal details */}
              <div className="mt-1 flex flex-wrap gap-1">
                {detection.signals.file_count != null && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
                    {detection.signals.file_count} files
                  </span>
                )}
                {detection.signals.git_commits != null && detection.signals.git_commits > 0 && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
                    {detection.signals.git_commits} commits
                  </span>
                )}
                {detection.signals.manifests?.map((m) => (
                  <span key={m} className="rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
                    {m}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Builder-specific: template list */}
          {mode === "builder" && builderTemplates.length > 0 && (
            <div className="max-h-48 overflow-y-auto px-3 py-2">
              <div className="mb-1 text-[10px] font-medium text-muted-foreground">
                {t.modes.projectTemplates}
              </div>
              <div className="space-y-1">
                {builderTemplates.map((tpl) => (
                  <div
                    key={tpl.name}
                    className="rounded-lg bg-muted/50 px-2 py-1.5 text-[11px]"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{tpl.display_name}</span>
                      <span className="text-[9px] text-muted-foreground">
                        {tpl.language}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">
                      {tpl.description}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Coder-specific: workspace signals */}
          {mode === "coder" && detection?.signals && (
            <div className="px-3 py-2">
              <div className="mb-1 text-[10px] font-medium text-muted-foreground">
                {t.modes.projectSignals}
              </div>
              <div className="space-y-0.5 text-[10px] text-muted-foreground">
                {detection.signals.manifests && detection.signals.manifests.length > 0 && (
                  <div>Tech stack: {detection.signals.manifests.join(", ")}</div>
                )}
                {detection.signals.structure_dirs && detection.signals.structure_dirs.length > 0 && (
                  <div>Directories: {detection.signals.structure_dirs.join(", ")}</div>
                )}
                {detection.signals.lock_files && detection.signals.lock_files.length > 0 && (
                  <div>Lock files: {detection.signals.lock_files.join(", ")}</div>
                )}
                {detection.signals.has_readme && <div>README found</div>}
              </div>
            </div>
          )}

          {/* Mode description */}
          {modeInfo && (
            <div className="border-t px-3 py-2 text-[10px] text-muted-foreground leading-tight">
              {modeInfo.description}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
