/**
 * Unified work-mode selector for both personal and project workspaces.
 *
 * Only two choices are user-facing: general-purpose work and design. Review,
 * research, implementation, and debugging are inferred from the request
 * inside general mode instead of requiring another manual mode switch.
 */

import {
  ChevronDownIcon,
  CodeIcon,
  LoaderIcon,
  LockIcon,
  PaletteIcon,
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
import { toast } from "sonner";

import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

export type AgentModeName = "develop" | "audit" | "uxui";
export type DetectedProjectKind = "builder" | "coder" | "architect";
/**
 * Audit-only intensity. "standard" → audit.review (single-pass); "max" →
 * audit.deep (exhaustive mode — the model is directed to fan out and
 * self-check, but chooses its own orchestration). The toggle only shows
 * for audit.
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
const PERSONAL_MODE_STORAGE_KEY = "__personal__";

function canonicalUserMode(mode: AgentModeName): AgentModeName {
  // `audit` is retained in the type only to read old task/local-storage data.
  // Code review now belongs to the general-purpose mode.
  return mode === "audit" ? "develop" : mode;
}

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

// The mode list is static server config and detection depends only on the
// workspace path - both survive route switches. Module-level caches keep
// remounts (every thread switch remounts ModeSelector) from re-fetching.
let modesPromise: Promise<ModeInfo[]> | null = null;
function loadModes(): Promise<ModeInfo[]> {
  if (!modesPromise) {
    modesPromise = fetchModes();
    modesPromise.catch(() => {
      modesPromise = null;
    });
  }
  return modesPromise;
}

const detectionCache = new Map<string, Promise<DetectResponse>>();
function loadDetection(workspacePath: string): Promise<DetectResponse> {
  let cached = detectionCache.get(workspacePath);
  if (!cached) {
    cached = fetchDetection(workspacePath);
    cached.catch(() => detectionCache.delete(workspacePath));
    detectionCache.set(workspacePath, cached);
  }
  return cached;
}

export async function persistModeSelection(
  mode: AgentModeName,
  sessionId: string,
  workspacePath: string,
): Promise<void> {
  const canonicalMode = canonicalUserMode(mode);
  const url = `${getBackendBaseURL()}/api/agent-modes/current`;
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ mode: canonicalMode, session_id: sessionId }),
  });
  if (!response.ok) {
    throw new Error(`Mode update failed: ${response.status}`);
  }
  writeStoredModeOverride(workspacePath, canonicalMode);
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
  labelOverrides?: Partial<Record<AgentModeName, string>>;
  permissionLabel?: string;
  onModeChange: (mode: AgentModeName) => void;
  /** Runs only after a user-initiated selection has been persisted. Hydration
   * and auto-detection never call it, so route changes can safely live here. */
  onUserModeChange?: (mode: AgentModeName) => void;
  onAuditIntensityChange?: (intensity: AuditIntensity) => void;
  onDetectionChange?: (detection: DetectResponse | null) => void;
  /** Notify the parent when the user manually overrides the auto-detected
   * mode (true), or when the override is cleared because the workspace
   * changed or auto-detection reapplied (false). Lets intent-based
   * auto-switching respect manual control. */
  onManualOverrideChange?: (isManual: boolean) => void;
  className?: string;
}

export function ModeSelector({
  workDir,
  sessionId,
  mode,
  codeModeUnlocked = false,
  readOnlyHint,
  chromeless = false,
  labelOverrides,
  permissionLabel,
  onModeChange,
  onUserModeChange,
  onDetectionChange,
  onManualOverrideChange,
  className,
}: ModeSelectorProps) {
  const { t } = useI18n();
  const [detection, setDetection] = useState<DetectResponse | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [switching, setSwitching] = useState(false);
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
  const storageKey = workDir.trim() || PERSONAL_MODE_STORAGE_KEY;

  const modeOptions = getModeOptions(t);
  // ``audit`` is a retained storage/backend alias. Canonicalize at the
  // rendering boundary so an old thread never paints a transient third label
  // before hydration migrates it to General.
  const visibleMode = canonicalUserMode(mode);
  const activeOption =
    modeOptions.find((option) => option.name === visibleMode) ?? {
      name: "develop",
      icon: CodeIcon,
      tone:
        "bg-info/15 text-info hover:bg-info/25 dark:bg-info/30 dark:text-info",
      activeTone:
        "bg-info/15 text-info dark:bg-info/40 dark:text-info ring-1 ring-info/20",
      ring: "ring-info/20",
      label: t.modes.develop,
      desc: t.modes.developDesc,
      effect: t.modes.developEffect,
      tooltip: t.modes.developTooltip,
    };

  useEffect(() => {
    const workspaceChanged = prevWorkDir.current !== storageKey;
    if (workspaceChanged) {
      prevWorkDir.current = storageKey;
      manualOverrideRef.current = false;
      setManualOverride(false);
      onManualOverrideChange?.(false);
    }

    // A persisted manual override for this workspace wins over auto-detection
    // (e.g. after a refresh), so the recommended mode never pre-empts it.
    const storedMode = readStoredModeOverride(storageKey);
    if (storedMode) {
      manualOverrideRef.current = true;
      setManualOverride(true);
      onManualOverrideChange?.(true);
      onModeChange(storedMode);
    }

    let cancelled = false;
    const doDetect = async () => {
      setDetecting(true);
      try {
        const result = await loadDetection(workDir);
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

    if (workDir.trim()) void doDetect();
    return () => {
      cancelled = true;
    };
  }, [
    onDetectionChange,
    onManualOverrideChange,
    onModeChange,
    storageKey,
    workDir,
  ]);

  useEffect(() => {
    let cancelled = false;
    loadModes()
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
    async (newMode: AgentModeName) => {
      const previousMode = mode;
      const previousManualOverride = manualOverrideRef.current;
      manualOverrideRef.current = true;
      setManualOverride(true);
      onManualOverrideChange?.(true);
      onModeChange(newMode);
      setExpanded(false);
      triggerRef.current?.focus();
      setSwitching(true);
      try {
        await persistModeSelection(newMode, sessionId, storageKey);
        onUserModeChange?.(newMode);
      } catch (e) {
        swallow(e);
        manualOverrideRef.current = previousManualOverride;
        setManualOverride(previousManualOverride);
        onManualOverrideChange?.(previousManualOverride);
        onModeChange(previousMode);
        toast.error("切换模式失败，已还原");
      } finally {
        setSwitching(false);
      }
    },
    [
      mode,
      onManualOverrideChange,
      onModeChange,
      onUserModeChange,
      sessionId,
      storageKey,
    ],
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
  const busy = detecting || switching;
  const ActiveIcon = busy ? LoaderIcon : activeOption.icon;
  const activeLabel =
    labelOverrides?.[visibleMode]?.trim() || activeOption.label;
  const modeInfo = modes.find((item) => item.name === visibleMode);
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
        aria-busy={switching}
        disabled={switching}
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
          "group flex items-center gap-1.5 text-xs font-medium text-muted-foreground shadow-none transition-colors duration-base",
          chromeless
            ? "h-8 rounded-lg px-1.5 hover:bg-muted/55 hover:text-foreground"
            : "h-8 rounded-lg border border-transparent bg-transparent px-2 hover:border-border-default hover:bg-muted/55 hover:text-foreground",
        )}
        title={activeOption.tooltip}
      >
        <ActiveIcon className={cn("size-3", busy && "animate-spin")} />
        <span className="max-w-[72px] truncate">{activeLabel}</span>
        {!chromeless && detection && isManualOverride && (
          <span className="text-xs opacity-50">
            {t.modes.manualOverrideShort}
          </span>
        )}
        {codeModeUnlocked ? (
          <span
            className="size-1.5 rounded-full bg-success/90 shadow-[0_0_6px_rgba(16,185,129,0.28)] transition-all duration-base"
            aria-hidden="true"
          />
        ) : (
          <span
            className="inline-flex shrink-0 text-warning"
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
                        aria-selected={visibleMode === option.name}
                        onClick={() => handleToggle(option.name)}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-lg py-2 text-xs transition-colors duration-base",
                          "px-3",
                          visibleMode === option.name
                            ? option.activeTone
                            : "text-muted-foreground hover:bg-muted",
                        )}
                        title={option.effect}
                      >
                        <Icon className="size-4 shrink-0" />
                        <div className="flex min-w-0 items-center gap-2 text-left">
                          <span className="font-semibold">
                            {labelOverrides?.[option.name]?.trim() ||
                              option.label}
                          </span>
                          <span className="truncate text-xs opacity-70">
                            {option.desc}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {modeInfo && (
                  <div className="border-t px-3 py-2 text-xs text-muted-foreground leading-tight">
                    {modeInfo.description}
                  </div>
                )}
                {workspaceLabel && (
                  <div className="flex min-w-0 items-center gap-2 border-t px-3 py-2 text-xs text-muted-foreground">
                    <span
                      className="min-w-0 truncate font-mono text-foreground/75"
                      title={workDir}
                    >
                      {workspaceLabel}
                    </span>
                    {permissionLabel && (
                      <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
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

const MODE_OVERRIDE_STORAGE_KEY = "octopus:modeOverride";

/**
 * A persisted per-workspace override stores both the manual mode AND the
 * audit intensity (标准 / 最高) so a refresh/restart restores the full choice
 * instead of snapping the intensity back to its default. Legacy rows that
 * stored a bare mode string are still read and migrated on write.
 */
type StoredModeEntry =
  | AgentModeName
  | { mode?: AgentModeName; auditIntensity?: AuditIntensity };

function isValidMode(mode: unknown): mode is AgentModeName {
  return mode === "develop" || mode === "audit" || mode === "uxui";
}

function isValidAuditIntensity(v: unknown): v is AuditIntensity {
  return v === "standard" || v === "max";
}

function readStoredEntries(): Record<string, StoredModeEntry> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(MODE_OVERRIDE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, StoredModeEntry>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (e) {
    swallow(e);
    return {};
  }
}

/**
 * Read the persisted manual-mode override for a workspace path, if any.
 * Returns null when nothing is stored, the value is invalid, localStorage is
 * unavailable (SSR), or parsing throws.
 */
export function readStoredModeOverride(
  workspacePath: string,
): AgentModeName | null {
  const entry = readStoredEntries()[workspacePath];
  const mode = typeof entry === "string" ? entry : entry?.mode;
  return isValidMode(mode) ? canonicalUserMode(mode) : null;
}

/**
 * Read the persisted audit intensity (标准 / 最高) for a workspace path.
 * Returns null when nothing is stored or the value is invalid.
 */
export function readStoredAuditIntensity(
  workspacePath: string,
): AuditIntensity | null {
  const entry = readStoredEntries()[workspacePath];
  if (typeof entry === "string") return null;
  const intensity = entry?.auditIntensity;
  return isValidAuditIntensity(intensity) ? intensity : null;
}

/**
 * Persist a manual-mode override for a workspace path under a single
 * `{ workspacePath: mode }` map, preserving any stored audit intensity.
 * Safe to call on SSR / when localStorage is unavailable — it no-ops.
 */
export function writeStoredModeOverride(
  workspacePath: string,
  mode: AgentModeName,
): void {
  if (typeof window === "undefined") return;
  try {
    const current = readStoredEntries();
    const existing = current[workspacePath];
    const existingIntensity =
      typeof existing === "object" ? existing.auditIntensity : undefined;
    current[workspacePath] = {
      mode: canonicalUserMode(mode),
      ...(isValidAuditIntensity(existingIntensity)
        ? { auditIntensity: existingIntensity }
        : {}),
    };
    window.localStorage.setItem(
      MODE_OVERRIDE_STORAGE_KEY,
      JSON.stringify(current),
    );
  } catch (e) {
    swallow(e);
  }
}

/**
 * Persist an audit-intensity override for a workspace path, preserving any
 * stored mode. Safe to call on SSR / when localStorage is unavailable.
 */
export function writeStoredAuditIntensity(
  workspacePath: string,
  intensity: AuditIntensity,
): void {
  if (typeof window === "undefined") return;
  try {
    const current = readStoredEntries();
    const existing = current[workspacePath];
    const existingMode =
      typeof existing === "string"
        ? existing
        : typeof existing === "object"
          ? existing.mode
          : undefined;
    current[workspacePath] = {
      ...(isValidMode(existingMode) ? { mode: existingMode } : {}),
      auditIntensity: intensity,
    };
    window.localStorage.setItem(
      MODE_OVERRIDE_STORAGE_KEY,
      JSON.stringify(current),
    );
  } catch (e) {
    swallow(e);
  }
}

export function modeFromProjectKind(kind: DetectedProjectKind): AgentModeName {
  switch (kind) {
    case "architect":
    case "builder":
    case "coder":
    default:
      // Project kind changes context, not the user's two-mode choice.
      return "develop";
  }
}

function getModeOptions(t: ReturnType<typeof useI18n>["t"]): ModeOption[] {
  return [
    {
      name: "develop",
      icon: CodeIcon,
      tone: "bg-info/15 text-info hover:bg-info/25 dark:bg-info/30 dark:text-info",
      activeTone:
        "bg-info/15 text-info dark:bg-info/40 dark:text-info ring-1 ring-info/20",
      ring: "ring-info/20",
      label: t.modes.develop,
      desc: t.modes.developDesc,
      effect: t.modes.developEffect,
      tooltip: t.modes.developTooltip,
    },
    {
      name: "uxui",
      icon: PaletteIcon,
      tone: "bg-chart-3/15 text-chart-3 hover:bg-chart-3/25 dark:bg-chart-3/30 dark:text-chart-3",
      activeTone:
        "bg-chart-3/15 text-chart-3 dark:bg-chart-3/40 dark:text-chart-3 ring-1 ring-chart-3/20",
      ring: "ring-chart-3/20",
      label: t.modes.uxui,
      desc: t.modes.uxuiDesc,
      effect: t.modes.uxuiEffect,
      tooltip: t.modes.uxuiTooltip,
    },
  ];
}
