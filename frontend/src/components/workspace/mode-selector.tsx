/**
 * Task-oriented mode selector for Agent project/code mode.
 *
 * Project detection decides whether the workspace is new or existing.
 * User-facing modes decide the work strategy: develop, audit, UX/UI.
 * (architect was merged into develop — design/migration is handled there.)
 */

import {
  ChevronDownIcon,
  CodeIcon,
  LoaderIcon,
  LockIcon,
  PaletteIcon,
  ShieldCheckIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

export type AgentModeName = "develop" | "audit" | "uxui";
export type DetectedProjectKind = "builder" | "coder" | "architect";
/**
 * Audit-only intensity. "standard" → audit.review (single-pass); "max" →
 * audit.ultracode (deep multi-agent review). The toggle only shows for audit.
 */
export type AuditIntensity = "standard" | "max";

export interface VerificationCommand {
  kind: string;
  command: string;
  source: string;
}

export interface DetectionSignals {
  workspace_path?: string | null;
  exists?: boolean | null;
  file_count?: number | null;
  manifests?: string[] | null;
  structure_dirs?: string[] | null;
  git_commits?: number | null;
  has_readme?: boolean | null;
  lock_files?: string[] | null;
  commands?: VerificationCommand[] | null;
  raw_score?: number | null;
}

export interface DetectResponse {
  recommended_mode: DetectedProjectKind;
  confidence: number;
  reason: string;
  signals: DetectionSignals;
}

interface ModeInfo {
  name: string;
  display_name: string;
  description: string;
  icon: string;
}

type PanelRect = {
  left: number;
  width: number;
  maxHeight: number;
  top?: number;
  bottom?: number;
};

type ModeOption = {
  name: AgentModeName;
  icon: typeof CodeIcon;
  tone: string;
  activeTone: string;
  ring: string;
  label: string;
  desc: string;
  effect: string;
  tooltip: string;
};

const PANEL_WIDTH = 340;
const PANEL_GAP = 6;
const PANEL_MARGIN = 12;
const PANEL_MIN_HEIGHT = 180;

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

interface ModeSelectorProps {
  workDir: string;
  sessionId: string;
  mode: AgentModeName;
  auditIntensity?: AuditIntensity;
  codeModeUnlocked?: boolean;
  /** When read-only (codeModeUnlocked=false), this hint is the lock badge's
   * tooltip on the mode chip — replacing the old standalone access chip. */
  readOnlyHint?: string;
  chromeless?: boolean;
  permissionLabel?: string;
  onModeChange: (mode: AgentModeName) => void;
  onAuditIntensityChange?: (intensity: AuditIntensity) => void;
  onDetectionChange?: (detection: DetectResponse | null) => void;
  className?: string;
}

export function ModeSelector({
  workDir,
  sessionId,
  mode,
  auditIntensity = "standard",
  codeModeUnlocked = false,
  readOnlyHint,
  chromeless = false,
  permissionLabel,
  onModeChange,
  onAuditIntensityChange,
  onDetectionChange,
  className,
}: ModeSelectorProps) {
  const { t } = useI18n();
  const [detection, setDetection] = useState<DetectResponse | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const panelRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);
  const baseId = useId();
  const triggerId = `${baseId}-trigger`;
  const listboxId = `${baseId}-listbox`;
  const prevWorkDir = useRef<string | null>(null);
  const manualOverrideRef = useRef(false);
  const [manualOverride, setManualOverride] = useState(false);
  const [panelRect, setPanelRect] = useState<PanelRect | null>(null);

  const modeOptions = getModeOptions(t);
  const activeOption = modeOptions.find((option) => option.name === mode) ?? {
    name: "develop",
    icon: CodeIcon,
    tone: "bg-sky-500/15 text-sky-700 hover:bg-sky-500/25 dark:bg-sky-900/30 dark:text-sky-400",
    activeTone:
      "bg-sky-500/15 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300 ring-1 ring-sky-500/20",
    ring: "ring-sky-500/20",
    label: t.modes.develop,
    desc: t.modes.developDesc,
    effect: t.modes.developEffect,
    tooltip: t.modes.developTooltip,
  };

  useEffect(() => {
    if (!workDir) return;
    const workspaceChanged = prevWorkDir.current !== workDir;
    if (workspaceChanged) {
      prevWorkDir.current = workDir;
      manualOverrideRef.current = false;
      setManualOverride(false);
    }

    let cancelled = false;
    const doDetect = async () => {
      setDetecting(true);
      try {
        const result = await fetchDetection(workDir);
        if (cancelled) return;
        setDetection(result);
        onDetectionChange?.(result);

        if (!manualOverrideRef.current) {
          onModeChange(modeFromProjectKind(result.recommended_mode));
        }
      } catch (e) {
        swallow(e);
        if (!cancelled) onDetectionChange?.(null);
      } finally {
        if (!cancelled) setDetecting(false);
      }
    };

    void doDetect();
    return () => {
      cancelled = true;
    };
  }, [onDetectionChange, onModeChange, workDir]);

  useEffect(() => {
    let cancelled = false;
    fetchModes()
      .then((m) => {
        if (!cancelled) setModes(m);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!expanded) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        panelRef.current &&
        !panelRef.current.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        // Focus lives inside the popup (keyboard path); closing would
        // strand it on <body>. Hand it back to the trigger — a focusable
        // click target still takes focus afterwards via its own default.
        if (menuRef.current?.contains(document.activeElement)) {
          triggerRef.current?.focus();
        }
        setExpanded(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [expanded]);

  const updatePanelPosition = useCallback(() => {
    const trigger = panelRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const width = Math.min(PANEL_WIDTH, viewportWidth - PANEL_MARGIN * 2);
    const left = Math.min(
      Math.max(PANEL_MARGIN, rect.right - width),
      viewportWidth - PANEL_MARGIN - width,
    );
    const spaceBelow = viewportHeight - rect.bottom - PANEL_MARGIN;
    const spaceAbove = rect.top - PANEL_MARGIN;
    const openUp = spaceAbove > spaceBelow;
    const maxHeight = Math.max(
      PANEL_MIN_HEIGHT,
      openUp ? spaceAbove - PANEL_GAP : spaceBelow - PANEL_GAP,
    );
    setPanelRect({
      left,
      width,
      maxHeight,
      ...(openUp
        ? { bottom: viewportHeight - rect.top + PANEL_GAP }
        : { top: rect.bottom + PANEL_GAP }),
    });
  }, []);

  useEffect(() => {
    if (!expanded) {
      setPanelRect(null);
      return;
    }
    updatePanelPosition();
    window.addEventListener("resize", updatePanelPosition);
    window.addEventListener("scroll", updatePanelPosition, true);
    return () => {
      window.removeEventListener("resize", updatePanelPosition);
      window.removeEventListener("scroll", updatePanelPosition, true);
    };
  }, [expanded, updatePanelPosition]);

  const handleToggle = useCallback(
    (newMode: AgentModeName) => {
      manualOverrideRef.current = true;
      setManualOverride(true);
      onModeChange(newMode);
      void setModeOnServer(newMode, sessionId);
      setExpanded(false);
      triggerRef.current?.focus();
    },
    [onModeChange, sessionId],
  );

  const closeAndRefocusTrigger = useCallback(() => {
    setExpanded(false);
    triggerRef.current?.focus();
  }, []);

  // The popup is portaled to the end of <body>, so DOM tab order never reaches
  // it from the trigger. Move focus onto the selected option as soon as the
  // listbox mounts; closing paths hand focus back to the trigger.
  const setListboxNode = useCallback((node: HTMLDivElement | null) => {
    listboxRef.current = node;
    if (!node) return;
    const selected = node.querySelector<HTMLButtonElement>(
      '[role="option"][aria-selected="true"]',
    );
    (
      selected ?? node.querySelector<HTMLButtonElement>('[role="option"]')
    )?.focus();
  }, []);

  const handlePopupKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        closeAndRefocusTrigger();
        return;
      }
      if (e.key === "Tab") {
        // The popup is portaled to <body>, so native tab order would fall
        // out of the app. Walk the popup's own focusables — the options
        // AND anything outside the listbox (the audit-intensity toggle is
        // the only place auditIntensity can be changed, so it must stay
        // keyboard-reachable) — and close only when tabbing past an end.
        const focusables = Array.from(
          menuRef.current?.querySelectorAll<HTMLButtonElement>(
            "button:not([disabled])",
          ) ?? [],
        );
        const current = focusables.indexOf(
          document.activeElement as HTMLButtonElement,
        );
        const next = current + (e.shiftKey ? -1 : 1);
        e.preventDefault();
        e.stopPropagation();
        if (current >= 0 && next >= 0 && next < focusables.length) {
          focusables[next]?.focus();
          return;
        }
        closeAndRefocusTrigger();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
      const options = Array.from(
        listboxRef.current?.querySelectorAll<HTMLButtonElement>(
          '[role="option"]',
        ) ?? [],
      );
      if (options.length === 0) return;
      e.preventDefault();
      const current = options.indexOf(
        document.activeElement as HTMLButtonElement,
      );
      let next: number;
      if (e.key === "Home") next = 0;
      else if (e.key === "End") next = options.length - 1;
      else if (e.key === "ArrowDown")
        next = current < 0 ? 0 : Math.min(current + 1, options.length - 1);
      else next = current < 0 ? options.length - 1 : Math.max(current - 1, 0);
      options[next]?.focus();
    },
    [closeAndRefocusTrigger],
  );

  const autoMode = detection
    ? modeFromProjectKind(detection.recommended_mode)
    : null;
  const isManualOverride =
    manualOverride || Boolean(autoMode && autoMode !== mode);
  const ActiveIcon = detecting ? LoaderIcon : activeOption.icon;
  const activeLabel = activeOption.label;
  const modeInfo = modes.find((item) => item.name === mode);
  const workspaceLabel = compactWorkspaceLabel(workDir);

  return (
    <div ref={panelRef} className={cn("relative", className)}>
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-expanded={expanded}
        aria-haspopup="listbox"
        aria-controls={expanded ? listboxId : undefined}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (!expanded && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            setExpanded(true);
          } else if (expanded && e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            setExpanded(false);
          }
        }}
        className={cn(
          "group flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground shadow-none transition-all duration-200",
          chromeless
            ? "h-8 rounded-lg px-1.5 hover:bg-muted/55 hover:text-foreground"
            : "h-8 rounded-lg border border-transparent bg-transparent px-2 hover:border-border-default hover:bg-muted/55 hover:text-foreground",
        )}
        title={activeOption.tooltip}
      >
        <ActiveIcon className={cn("size-3", detecting && "animate-spin")} />
        <span
          className={cn(
            "truncate",
            chromeless ? "max-w-[42px]" : "max-w-[72px]",
          )}
        >
          {activeLabel}
        </span>
        {!chromeless && detection && isManualOverride && (
          <span className="text-[9px] opacity-50">
            {t.modes.manualOverrideShort}
          </span>
        )}
        {codeModeUnlocked ? (
          <span
            className="size-1.5 rounded-full bg-emerald-500/90 shadow-[0_0_6px_rgba(16,185,129,0.28)] transition-all duration-200"
            aria-hidden="true"
          />
        ) : (
          <span
            className="inline-flex shrink-0 text-amber-600 dark:text-amber-400"
            title={readOnlyHint}
            aria-label={readOnlyHint}
          >
            <LockIcon className="size-3" />
          </span>
        )}
        <ChevronDownIcon className="size-3 opacity-35 transition-opacity group-hover:opacity-60" />
      </button>

      {expanded && panelRect && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[100] overflow-hidden rounded-lg border bg-background shadow-xl ring-1 ring-border-subtle"
              style={{
                left: `${panelRect.left}px`,
                width: `${panelRect.width}px`,
                maxHeight: `${panelRect.maxHeight}px`,
                top:
                  panelRect.top !== undefined
                    ? `${panelRect.top}px`
                    : undefined,
                bottom:
                  panelRect.bottom !== undefined
                    ? `${panelRect.bottom}px`
                    : undefined,
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={handlePopupKeyDown}
            >
              <div className="max-h-[inherit] overflow-y-auto">
                <div
                  ref={setListboxNode}
                  id={listboxId}
                  role="listbox"
                  aria-labelledby={triggerId}
                  className="space-y-1 p-2"
                >
                  {modeOptions.map((option) => {
                    const Icon = option.icon;
                    return (
                      <button
                        key={option.name}
                        type="button"
                        role="option"
                        aria-selected={mode === option.name}
                        onClick={() => handleToggle(option.name)}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-lg py-2 text-xs transition-all duration-200",
                          "px-3",
                          mode === option.name
                            ? option.activeTone
                            : "text-muted-foreground hover:bg-muted",
                        )}
                        title={option.effect}
                      >
                        <Icon className="size-4 shrink-0" />
                        <div className="flex min-w-0 items-center gap-2 text-left">
                          <span className="font-semibold">{option.label}</span>
                          <span className="truncate text-[10px] opacity-70">
                            {option.desc}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {mode === "audit" && (
                  <div className="border-t px-3 py-2">
                    <div className="flex items-center gap-1 rounded-lg bg-muted/50 p-0.5">
                      {(["standard", "max"] as const).map((level) => {
                        const active = auditIntensity === level;
                        const label =
                          level === "max" ? t.modes.ultra : t.modes.standard;
                        return (
                          <button
                            key={level}
                            type="button"
                            onClick={() => onAuditIntensityChange?.(level)}
                            className={cn(
                              "flex-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
                              active
                                ? "bg-background text-foreground shadow-[var(--shadow-xs)] ring-1 ring-border-subtle"
                                : "text-muted-foreground hover:text-foreground",
                            )}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                    <p className="mt-1.5 text-[10px] leading-tight text-muted-foreground">
                      {auditIntensity === "max"
                        ? t.modes.ultraTooltip
                        : t.modes.auditEffect}
                    </p>
                  </div>
                )}

                {modeInfo && (
                  <div className="border-t px-3 py-2 text-[10px] text-muted-foreground leading-tight">
                    {modeInfo.description}
                  </div>
                )}
                {workspaceLabel && (
                  <div className="flex min-w-0 items-center gap-2 border-t px-3 py-2 text-[10px] text-muted-foreground">
                    <span
                      className="min-w-0 truncate font-mono text-foreground/75"
                      title={workDir}
                    >
                      {workspaceLabel}
                    </span>
                    {permissionLabel && (
                      <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {permissionLabel}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function compactWorkspaceLabel(path: string): string {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  if (!normalized) return "";
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}

function modeFromProjectKind(_kind: DetectedProjectKind): AgentModeName {
  // architect mode was merged into develop; all detected kinds map to develop.
  return "develop";
}

function getModeOptions(t: ReturnType<typeof useI18n>["t"]): ModeOption[] {
  return [
    {
      name: "develop",
      icon: CodeIcon,
      tone: "bg-sky-500/15 text-sky-700 hover:bg-sky-500/25 dark:bg-sky-900/30 dark:text-sky-400",
      activeTone:
        "bg-sky-500/15 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300 ring-1 ring-sky-500/20",
      ring: "ring-sky-500/20",
      label: t.modes.develop,
      desc: t.modes.developDesc,
      effect: t.modes.developEffect,
      tooltip: t.modes.developTooltip,
    },
    {
      name: "audit",
      icon: ShieldCheckIcon,
      tone: "bg-rose-500/15 text-rose-700 hover:bg-rose-500/25 dark:bg-rose-900/30 dark:text-rose-400",
      activeTone:
        "bg-rose-500/15 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300 ring-1 ring-rose-500/20",
      ring: "ring-rose-500/20",
      label: t.modes.audit,
      desc: t.modes.auditDesc,
      effect: t.modes.auditEffect,
      tooltip: t.modes.auditTooltip,
    },
    {
      name: "uxui",
      icon: PaletteIcon,
      tone: "bg-fuchsia-500/15 text-fuchsia-700 hover:bg-fuchsia-500/25 dark:bg-fuchsia-900/30 dark:text-fuchsia-400",
      activeTone:
        "bg-fuchsia-500/15 text-fuchsia-800 dark:bg-fuchsia-900/40 dark:text-fuchsia-300 ring-1 ring-fuchsia-500/20",
      ring: "ring-fuchsia-500/20",
      label: t.modes.uxui,
      desc: t.modes.uxuiDesc,
      effect: t.modes.uxuiEffect,
      tooltip: t.modes.uxuiTooltip,
    },
  ];
}
