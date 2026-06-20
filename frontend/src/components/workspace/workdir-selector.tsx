import {
  CheckIcon,
  ChevronDownIcon,
  FolderIcon,
  FolderOpenIcon,
  Loader2Icon,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { swallow } from "@/core/utils/log";
import { authHeaders } from "@/core/auth/api";
import type { components } from "@/core/api/openapi-types";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { basename, isAbsolutePath, joinPath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";

interface WorkDirSelectorProps {
  workDir: string;
  onWorkDirChange?: (dir: string) => void;
  className?: string;
  variant?: "default" | "muted";
}

type FsTreeEntry = components["schemas"]["FsTreeEntry"];
const RECENT_WORKDIRS_KEY = "octopus:recentWorkdirs";
const MAX_RECENT_WORKDIRS = 6;
const MENU_WIDTH = 360;
const MENU_MARGIN = 12;

// Native folder picker via Electron preload(`window.octopus.dialog`)·
// Implementation note.
// Implementation note.
async function openNativeFolderPicker(
  currentDir: string,
): Promise<string | null> {
  const api = window.octopus;
  if (api?.dialog?.open) {
    try {
      const result = await api.dialog.open({
        properties: ["openDirectory"],
        defaultPath: currentDir,
      });
      if (!result.canceled && result.filePaths.length > 0) {
        return result.filePaths[0] || null;
      }
    } catch (error) {
      console.error("Electron folder picker failed:", error);
    }
  }

  return null;
}

function readRecentWorkdirs(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_WORKDIRS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? dedupePaths(
          parsed.filter(
            (item): item is string =>
              typeof item === "string" && item.trim().length > 0,
          ),
        )
      : [];
  } catch (e) {
    swallow(e);
    return [];
  }
}

function writeRecentWorkdirs(paths: string[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(
    RECENT_WORKDIRS_KEY,
    JSON.stringify(dedupePaths(paths).slice(0, MAX_RECENT_WORKDIRS)),
  );
}

function normalizePathKey(path: string): string {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return (normalized || path.trim()).toLowerCase();
}

function dedupePaths(paths: string[]): string[] {
  const seen = new Set<string>();
  return paths.filter((path) => {
    const key = normalizePathKey(path);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function dedupeDirEntries(entries: FsTreeEntry[]): FsTreeEntry[] {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    const key = normalizePathKey(entry.path || entry.name);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function parentDir(path: string): string | null {
  const normalized = path.replace(/[\\/]+$/, "");
  const parts = normalized.split(/[\\/]/);
  if (parts.length <= 1) return null;
  if (parts.length === 2 && /^[A-Za-z]:$/.test(parts[0] || "")) {
    return `${parts[0]}/`;
  }
  parts.pop();
  return parts.join("/");
}

// Stable hash → palette index. Same folder name always lands on the
// same color across reloads, so the avatar tiles act as a visual id.
const AVATAR_PALETTE: Array<{ bg: string; fg: string }> = [
  { bg: "bg-rose-500/15", fg: "text-rose-600 dark:text-rose-400" },
  { bg: "bg-amber-500/15", fg: "text-amber-600 dark:text-amber-400" },
  { bg: "bg-emerald-500/15", fg: "text-emerald-600 dark:text-emerald-400" },
  { bg: "bg-sky-500/15", fg: "text-sky-600 dark:text-sky-400" },
  { bg: "bg-violet-500/15", fg: "text-violet-600 dark:text-violet-400" },
  { bg: "bg-pink-500/15", fg: "text-pink-600 dark:text-pink-400" },
];

function avatarTile(path: string): { bg: string; fg: string; letter: string } {
  const name = basename(path) || path;
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) >>> 0;
  }
  const palette = AVATAR_PALETTE[h % AVATAR_PALETTE.length]!;
  return { ...palette, letter: (name[0] || "?").toUpperCase() };
}

function browseEntryPath(base: string, entryPath: string): string {
  return base ? joinPath(base, entryPath) : entryPath;
}

function entryDisplayName(entry: FsTreeEntry): string {
  const fromPath = basename(entry.path.replace(/[\\/]+$/, ""));
  return fromPath || entry.name || entry.path;
}

export function WorkDirSelector({
  workDir,
  onWorkDirChange,
  className,
  variant = "default",
}: WorkDirSelectorProps) {
  const isMutedVariant = variant === "muted";
  const { t } = useI18n();
  const [isPicking, setIsPicking] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  // ``browsePath`` drives the in-menu folder browser. When the user
  // hasn't chosen anything yet we seed it from the most recently used
  // directory so the picker isn't pointing at an empty string (which
  // the backend's /api/fs/tree rejects).
  const [browsePath, setBrowsePath] = useState(() => {
    if (workDir) return workDir;
    if (typeof window === "undefined") return "";
    try {
      const recent = readRecentWorkdirs();
      if (recent.length > 0) return recent[0]!;
    } catch (e) {
      swallow(e);
    }
    return "";
  });
  const [browseEntries, setBrowseEntries] = useState<FsTreeEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [recentWorkdirs, setRecentWorkdirs] = useState<string[]>(() =>
    readRecentWorkdirs(),
  );
  const [manualPath, setManualPath] = useState(workDir);
  const [isBrowserOpen, setBrowserOpen] = useState(
    () => !isMutedVariant && !workDir,
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const manualInputRef = useRef<HTMLInputElement>(null);
  const folderName = useMemo(
    () => (workDir ? basename(workDir) : ""),
    [workDir],
  );
  const isEmpty = !workDir;
  const emptyTriggerLabel = isMutedVariant
    ? t.codeMode.personalSpace
    : t.codeMode.chooseWorkspaceFolder;
  const folderPickerLabel = isMutedVariant
    ? t.codeMode.selectFolder
    : t.codeMode.openFolderCta;
  const triggerTitle = isEmpty
    ? emptyTriggerLabel
    : `${t.codeMode.chooseWorkspaceFolder}: ${workDir}`;
  const menuToggleTitle = isMutedVariant
    ? t.codeMode.selectFolder
    : t.codeMode.recentWorkspaces;
  const emptyTriggerClass = isMutedVariant
    ? "bg-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground"
    : "bg-transparent text-amber-700 hover:bg-amber-500/10 dark:text-amber-300 dark:hover:bg-amber-500/15";

  const applyWorkDir = useCallback(
    (dir: string) => {
      const next = dir.trim();
      if (!next || !isAbsolutePath(next)) return;
      onWorkDirChange?.(next);
      setBrowsePath(next);
      setRecentWorkdirs((prev) => {
        const merged = dedupePaths([next, ...prev]).slice(
          0,
          MAX_RECENT_WORKDIRS,
        );
        writeRecentWorkdirs(merged);
        return merged;
      });
      setShowMenu(false);
    },
    [onWorkDirChange],
  );

  const clearWorkDir = useCallback(() => {
    onWorkDirChange?.("");
    setManualPath("");
    setShowMenu(false);
  }, [onWorkDirChange]);

  const loadDirectories = useCallback(async (path: string) => {
    if (!path) {
      setBrowseLoading(true);
      try {
        const res = await fetch(`${getBackendBaseURL()}/api/fs/roots`, {
          headers: authHeaders(),
        });
        const data = await res.json();
        const entries = Array.isArray(data?.entries)
          ? data.entries
          : Array.isArray(data)
            ? data
            : [];
        setBrowseEntries(
          dedupeDirEntries(
            entries.filter((entry: FsTreeEntry) => entry.type === "dir"),
          ),
        );
      } catch (e) {
        swallow(e);
        setBrowseEntries([]);
      } finally {
        setBrowseLoading(false);
      }
      return;
    }
    setBrowseLoading(true);
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/fs/tree?path=${encodeURIComponent(path)}&depth=1`,
        { headers: authHeaders() },
      );
      const data = await res.json();
      const entries = Array.isArray(data?.entries)
        ? data.entries
        : Array.isArray(data)
          ? data
          : [];
      setBrowseEntries(
        dedupeDirEntries(
          entries.filter((entry: FsTreeEntry) => entry.type === "dir"),
        ),
      );
    } catch (e) {
      swallow(e);
      setBrowseEntries([]);
    } finally {
      setBrowseLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!workDir) return;
    setManualPath(workDir);
    setBrowsePath(workDir);
    setRecentWorkdirs((prev) => {
      const merged = dedupePaths([workDir, ...prev]).slice(
        0,
        MAX_RECENT_WORKDIRS,
      );
      writeRecentWorkdirs(merged);
      return merged;
    });
  }, [workDir]);

  useEffect(() => {
    if (!showMenu) return;
    if (isMutedVariant) return;
    void loadDirectories(browsePath);
  }, [isMutedVariant, showMenu, browsePath, loadDirectories]);

  useEffect(() => {
    if (!showMenu) return;
    setManualPath(workDir);
    if (!workDir && !isMutedVariant) setBrowserOpen(true);
  }, [isMutedVariant, showMenu, workDir]);

  useEffect(() => {
    if (!showMenu) return;
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !containerRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        setShowMenu(false);
      }
    };
    window.addEventListener("mousedown", handleClickOutside);
    return () => window.removeEventListener("mousedown", handleClickOutside);
  }, [showMenu]);

  const handlePrimaryAction = useCallback(async () => {
    if (isPicking) return;
    if (isMutedVariant) {
      setShowMenu(true);
      return;
    }
    if (!window.octopus?.dialog?.open) {
      setShowMenu(true);
      setBrowserOpen(true);
      requestAnimationFrame(() => manualInputRef.current?.focus());
      return;
    }
    setIsPicking(true);
    try {
      const selected = await openNativeFolderPicker(workDir);
      if (selected) {
        applyWorkDir(selected);
        return;
      }
      setShowMenu(true);
      setBrowserOpen(true);
    } finally {
      setIsPicking(false);
    }
  }, [applyWorkDir, isMutedVariant, isPicking, workDir]);

  const handleManualSubmit = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      applyWorkDir(manualPath);
    },
    [applyWorkDir, manualPath],
  );

  const [menuRect, setMenuRect] = useState<{
    top: number;
    left: number;
    width: number;
    maxHeight: number;
  } | null>(null);

  const updateMenuPosition = useCallback(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const targetWidth = isMutedVariant ? 176 : MENU_WIDTH;
    const minWidth = isMutedVariant ? 160 : 280;
    const estimatedHeight = isMutedVariant ? 56 : 260;
    const minHeight = isMutedVariant ? 48 : 240;
    const width = Math.min(
      targetWidth,
      Math.max(minWidth, window.innerWidth - MENU_MARGIN * 2),
    );
    const left = Math.min(
      Math.max(MENU_MARGIN, rect.right - width),
      window.innerWidth - MENU_MARGIN - width,
    );
    const top = Math.min(
      rect.bottom + 6,
      Math.max(MENU_MARGIN, window.innerHeight - MENU_MARGIN - estimatedHeight),
    );
    setMenuRect({
      top,
      left,
      width,
      maxHeight: Math.max(minHeight, window.innerHeight - top - MENU_MARGIN),
    });
  }, [isMutedVariant]);

  useEffect(() => {
    if (!showMenu) {
      setMenuRect(null);
      return;
    }
    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
    };
  }, [showMenu, updateMenuPosition]);

  const handleEnterDirectory = useCallback(
    (entryPath: string) => {
      setBrowsePath(browseEntryPath(browsePath, entryPath));
    },
    [browsePath],
  );

  const upDir = parentDir(browsePath);

  // Browser CTAs map to native Electron actions when available; in pure
  // web mode they degrade to existing in-page flows (manual edit prompt
  // for "open folder", info popups for the unimplemented ones).
  const handleOpenFolderCta = useCallback(async () => {
    if (!window.octopus?.dialog?.open) {
      if (isMutedVariant) {
        setShowMenu(false);
        return;
      }
      setBrowserOpen(true);
      requestAnimationFrame(() => manualInputRef.current?.focus());
      return;
    }
    setIsPicking(true);
    try {
      const selected = await openNativeFolderPicker(workDir);
      if (selected) {
        applyWorkDir(selected);
        return;
      }
      if (!isMutedVariant) {
        setBrowserOpen(true);
        requestAnimationFrame(() => manualInputRef.current?.focus());
      }
    } finally {
      setIsPicking(false);
    }
  }, [applyWorkDir, isMutedVariant, workDir]);

  // CTA tile for the implemented workspace picker entry point.
  const cta = (opts: {
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      onClick={opts.onClick}
      disabled={opts.disabled}
      className={cn(
        "flex w-full items-center gap-2 transition-all",
        isMutedVariant
          ? "rounded-md px-2 py-1.5 text-[12px] font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground"
          : "rounded-lg border border-primary/20 bg-primary/10 px-3 py-2 text-sm font-medium text-primary",
        opts.disabled
          ? "cursor-not-allowed opacity-50"
          : !isMutedVariant && "hover:border-primary/30 hover:bg-primary/15",
      )}
    >
      <span
        className={cn(
          "grid shrink-0 place-items-center rounded-md",
          isMutedVariant ? "size-5" : "size-7 bg-background/80",
        )}
      >
        {opts.icon}
      </span>
      <span className="min-w-0 flex-1 text-left">{opts.label}</span>
    </button>
  );

  const folderPickerCta = cta({
    icon: isPicking ? (
      <Loader2Icon
        className={cn("animate-spin", isMutedVariant ? "size-3.5" : "size-4")}
      />
    ) : (
      <FolderOpenIcon className={isMutedVariant ? "size-3.5" : "size-4"} />
    ),
    label: folderPickerLabel,
    onClick: handleOpenFolderCta,
    disabled: isPicking,
  });

  const menuContent = (
    <div
      className={cn(
        "flex max-h-full flex-col overflow-hidden border border-border/60 bg-popover/95 backdrop-blur",
        isMutedVariant ? "rounded-lg shadow-lg" : "rounded-xl shadow-2xl",
      )}
    >
      {/* Primary entry point for adding a workspace. */}
      <div className={cn("shrink-0", isMutedVariant ? "p-1.5" : "p-2.5")}>
        {folderPickerCta}
        {workDir && (
          <button
            type="button"
            onClick={clearWorkDir}
            className={cn(
              "mt-1.5 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
              !isMutedVariant && "border border-border/50",
            )}
          >
            <FolderIcon className="size-3.5 shrink-0" />
            <span className="min-w-0 flex-1 truncate">
              {t.codeMode.personalSpace}
            </span>
          </button>
        )}

        {!isMutedVariant && (
          <form
            className="mt-2 flex items-center gap-1.5 rounded-lg border border-border/50 bg-background/70 p-1 shadow-inner"
            onSubmit={handleManualSubmit}
          >
            <input
              ref={manualInputRef}
              aria-label={t.codeMode.selectWorkspace}
              value={manualPath}
              onChange={(event) => setManualPath(event.target.value)}
              placeholder={t.codeMode.selectWorkspace}
              className="min-w-0 flex-1 bg-transparent px-2 py-1.5 font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground/60"
            />
            <button
              type="submit"
              disabled={!isAbsolutePath(manualPath)}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors",
                isAbsolutePath(manualPath)
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "cursor-not-allowed bg-muted text-muted-foreground/45",
              )}
            >
              {t.common.confirm}
            </button>
          </form>
        )}
      </div>

      {/* Recent workspaces — colored letter-tile + path subtitle + ✓
          for the currently active workspace */}
      {!isMutedVariant && (
        <div
          className={cn(
            "border-t border-border/50",
            isMutedVariant ? "px-1.5 py-1.5" : "px-2.5 py-2",
          )}
        >
          <div className="pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t.codeMode.recentWorkspaces}
          </div>
          {recentWorkdirs.length > 0 ? (
            <div
              className={cn(
                "space-y-0.5 overflow-y-auto pr-1",
                isMutedVariant ? "max-h-32" : "max-h-44",
              )}
            >
              {recentWorkdirs.map((dir) => {
                const tile = avatarTile(dir);
                const active = dir === workDir;
                return (
                  <button
                    key={dir}
                    type="button"
                    onClick={() => applyWorkDir(dir)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-1.5 py-1.5 text-left transition-colors",
                      active
                        ? "bg-primary/10 text-primary"
                        : "hover:bg-muted/55",
                    )}
                    title={dir}
                  >
                    <span
                      className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-md font-mono text-[12px] font-semibold",
                        tile.bg,
                        tile.fg,
                      )}
                    >
                      {tile.letter}
                    </span>
                    <span className="min-w-0 flex-1">
                      <div className="truncate text-[12px] font-medium text-foreground">
                        {basename(dir) || dir}
                      </div>
                      <div className="truncate font-mono text-[10px] text-muted-foreground/80">
                        {dir}
                      </div>
                    </span>
                    {active && (
                      <CheckIcon className="size-3.5 shrink-0 text-primary" />
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border/60 bg-muted/20 px-2 py-3 text-center text-[11px] text-muted-foreground">
              {t.codeMode.noRecentWorkspaces}
            </div>
          )}
        </div>
      )}

      {/* Advanced: in-page directory browser. Web-mode users without an
          Electron picker still need a way to navigate; native users will
          rarely open this. Collapsed by default so it doesn't dominate. */}
      {!isMutedVariant && (
        <details
          className="group border-t border-border/50 px-2.5 py-2"
          open={isBrowserOpen}
          onToggle={(event) => setBrowserOpen(event.currentTarget.open)}
        >
          <summary className="cursor-pointer list-none rounded-md px-1 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground">
            <span className="inline-flex items-center gap-1">
              <ChevronDownIcon className="size-3 transition-transform group-open:rotate-180" />
              {t.codeMode.browseCurrentFolder}
            </span>
          </summary>
          <div className="mt-1">
            <div
              className="px-1 pb-1 text-[10px] font-mono text-muted-foreground/80 truncate"
              title={browsePath}
            >
              {browsePath || "—"}
            </div>
            {upDir && (
              <button
                type="button"
                onClick={() => setBrowsePath(upDir)}
                className="block w-full rounded-md px-2 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
              >
                .. / {t.codeMode.parentFolder}
              </button>
            )}
            {browseLoading ? (
              <div className="flex items-center gap-2 px-2 py-2 text-[11px] text-muted-foreground">
                <Loader2Icon className="size-3 animate-spin" />
                {t.codeMode.loadingFolders}
              </div>
            ) : browseEntries.length > 0 ? (
              <div
                className={cn(
                  "mt-1 space-y-0.5 overflow-auto",
                  isMutedVariant ? "max-h-28" : "max-h-56",
                )}
              >
                {browseEntries.map((entry) => {
                  const nextPath = browseEntryPath(browsePath, entry.path);
                  const displayName = entryDisplayName(entry);
                  return (
                    <div
                      key={`${browsePath}:${entry.path}`}
                      className="flex items-center gap-1"
                    >
                      <button
                        type="button"
                        onClick={() => handleEnterDirectory(entry.path)}
                        className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                        title={nextPath}
                      >
                        <FolderIcon className="size-3 shrink-0" />
                        <span className="truncate">{displayName}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => applyWorkDir(nextPath)}
                        className="rounded-md px-2 py-1 text-[10px] text-primary transition-colors hover:bg-primary/10"
                        title={t.codeMode.chooseWorkspaceFolder}
                      >
                        ✓
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="px-2 py-2 text-[11px] text-muted-foreground">
                {t.codeMode.noSubfolders}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );

  return (
    <div
      ref={containerRef}
      className={cn("relative flex items-center gap-1", className)}
    >
      <button
        className={cn(
          "flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-[10px] transition-all",
          isEmpty
            ? emptyTriggerClass
            : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
          isPicking && "cursor-wait opacity-50",
        )}
        onClick={handlePrimaryAction}
        disabled={isPicking}
        title={triggerTitle}
        type="button"
      >
        <FolderOpenIcon className="size-3" />
        <span
          className={cn(
            "max-w-[160px] truncate",
            isEmpty && isMutedVariant ? "font-medium" : "font-mono",
          )}
        >
          {isEmpty ? emptyTriggerLabel : folderName}
        </span>
      </button>

      <button
        className="flex items-center justify-center rounded-md p-0.5 text-[10px] text-muted-foreground/60 transition-colors hover:bg-muted/50 hover:text-muted-foreground"
        onClick={() => setShowMenu((v) => !v)}
        title={menuToggleTitle}
        type="button"
      >
        <ChevronDownIcon
          className={cn(
            "size-3 transition-transform",
            showMenu && "rotate-180",
          )}
        />
      </button>

      {menuRect && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[100]"
              style={{
                top: `${menuRect.top}px`,
                left: `${menuRect.left}px`,
                width: `${menuRect.width}px`,
                maxHeight: `${menuRect.maxHeight}px`,
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              {menuContent}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
