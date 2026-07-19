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
  lockToCurrentThread?: boolean;
  onOpenWorkDirInNewTask?: (dir: string) => void;
  className?: string;
  variant?: "default" | "muted";
  chromeless?: boolean;
}

type FsTreeEntry = components["schemas"]["FsTreeEntry"];
const RECENT_WORKDIRS_KEY = "octopus:recentWorkdirs";
const MAX_RECENT_WORKDIRS = 6;
const MENU_WIDTH = 360;
const MENU_MARGIN = 12;

// Native folder picker via the Electron preload bridge.
async function openNativeFolderPicker(
  currentDir: string,
): Promise<string | null> {
  const api = window.octopus;
  if (api?.dialog?.open) {
    try {
      const result = await api.dialog.open({
        properties: ["openDirectory", "createDirectory"],
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

// Kept self-contained (not in the shared i18n bundle) so this touch-up stays
// decoupled from concurrently-edited locale files.
const WEB_PICKER_HINT: Record<"zh" | "en" | "ja" | "ko", string> = {
  zh: "网页版无法直接选择本地文件夹。选最近用过的工作区,或在下方粘贴完整路径;需要文件夹选择器请用桌面版。",
  en: "The web app can't pick a local folder directly. Choose a recent workspace, or paste a full path below — use the desktop app for a folder picker.",
  ja: "ウェブ版はローカルフォルダを直接選択できません。最近のワークスペースを選ぶか、下に絶対パスを貼り付けてください（フォルダ選択はデスクトップ版）。",
  ko: "웹 버전은 로컬 폴더를 직접 선택할 수 없습니다. 최근 작업 공간을 선택하거나 아래에 전체 경로를 붙여넣으세요(폴더 선택기는 데스크톱 앱).",
};

const LOCKED_WORKDIR_TEXT: Record<
  "zh" | "en" | "ja" | "ko",
  { triggerTitle: string; hint: string; openFolder: string }
> = {
  zh: {
    triggerTitle: "当前任务已绑定工作区",
    hint: "当前对话已绑定这个工作区。选择其他工作区会打开一个新任务，避免上下文和权限混在一起。",
    openFolder: "在新任务打开其他工作区",
  },
  en: {
    triggerTitle: "Current task is bound to this workspace",
    hint: "This conversation is bound to its workspace. Choosing another workspace opens a new task so context and permissions stay separate.",
    openFolder: "Open another workspace in a new task",
  },
  ja: {
    triggerTitle: "このタスクは現在のワークスペースに固定されています",
    hint: "この会話は現在のワークスペースに固定されています。別のワークスペースは新しいタスクで開き、文脈と権限を分けます。",
    openFolder: "別のワークスペースを新しいタスクで開く",
  },
  ko: {
    triggerTitle: "현재 작업은 이 작업 공간에 고정되어 있습니다",
    hint: "이 대화는 현재 작업 공간에 고정되어 있습니다. 다른 작업 공간은 새 작업으로 열어 컨텍스트와 권한을 분리합니다.",
    openFolder: "다른 작업 공간을 새 작업으로 열기",
  },
};

function webPickerHint(locale: string): string {
  const lang = (locale || "en").slice(0, 2).toLowerCase();
  if (lang === "zh") return WEB_PICKER_HINT.zh;
  if (lang === "ja") return WEB_PICKER_HINT.ja;
  if (lang === "ko") return WEB_PICKER_HINT.ko;
  return WEB_PICKER_HINT.en;
}

function lockedWorkdirText(locale: string) {
  const lang = (locale || "en").slice(0, 2).toLowerCase();
  if (lang === "zh") return LOCKED_WORKDIR_TEXT.zh;
  if (lang === "ja") return LOCKED_WORKDIR_TEXT.ja;
  if (lang === "ko") return LOCKED_WORKDIR_TEXT.ko;
  return LOCKED_WORKDIR_TEXT.en;
}

export function WorkDirSelector({
  workDir,
  onWorkDirChange,
  lockToCurrentThread = false,
  onOpenWorkDirInNewTask,
  className,
  variant = "default",
  chromeless = false,
}: WorkDirSelectorProps) {
  const isMutedVariant = variant === "muted";
  const { t, locale } = useI18n();
  // Native folder picker is only reachable through the Electron preload bridge.
  // In a plain browser there is none — `showDirectoryPicker` can only hand back a
  // folder *name*, never an absolute path the local backend can use — so the
  // web flow leans on recent workspaces + manual paste instead of a dead picker.
  const hasNativePicker =
    typeof window !== "undefined" && Boolean(window.octopus?.dialog?.open);
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
  // True when the user just hit the "pick folder" CTA but no Electron bridge
  // is present (i.e. running in a plain browser). We surface the manual input
  // and a one-line hint instead of silently doing nothing. Resets once the
  // user enters a path or closes the menu.
  const [noBridgeHint, setNoBridgeHint] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const manualInputRef = useRef<HTMLInputElement>(null);
  const pendingBrowserPickedNameRef = useRef("");
  const folderName = useMemo(
    () => (workDir ? basename(workDir) : ""),
    [workDir],
  );
  const lockedCopy = lockedWorkdirText(locale);
  const isEmpty = !workDir;
  const isWorkDirLocked = lockToCurrentThread;
  const emptyTriggerLabel = isMutedVariant
    ? t.codeMode.personalSpace
    : t.codeMode.chooseWorkspaceFolder;
  const triggerLabel =
    !isEmpty && isMutedVariant
      ? folderName
      : isEmpty
        ? emptyTriggerLabel
        : folderName;
  const folderPickerLabel = isWorkDirLocked
    ? lockedCopy.openFolder
    : isMutedVariant
      ? t.codeMode.chooseWorkspaceFolder
      : t.codeMode.openFolderCta;
  const triggerTitle = isEmpty
    ? emptyTriggerLabel
    : isWorkDirLocked
      ? `${lockedCopy.triggerTitle}: ${workDir}`
      : `${t.codeMode.chooseWorkspaceFolder}: ${workDir}`;
  const _menuToggleTitle = isMutedVariant
    ? t.codeMode.chooseWorkspaceFolder
    : t.codeMode.recentWorkspaces;
  const emptyTriggerClass = isMutedVariant
    ? "text-muted-foreground"
    : "text-muted-foreground";
  const activeTriggerClass = isMutedVariant
    ? "text-foreground"
    : "text-foreground";

  const applyWorkDir = useCallback(
    (dir: string) => {
      const next = dir.trim();
      if (!next || !isAbsolutePath(next)) return;
      if (isWorkDirLocked) {
        if (normalizePathKey(next) !== normalizePathKey(workDir)) {
          onOpenWorkDirInNewTask?.(next);
        }
        setShowMenu(false);
        setNoBridgeHint(false);
        return;
      }
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
      setNoBridgeHint(false);
    },
    [isWorkDirLocked, onOpenWorkDirInNewTask, onWorkDirChange, workDir],
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
    const pendingName = pendingBrowserPickedNameRef.current;
    pendingBrowserPickedNameRef.current = "";
    setManualPath(pendingName || workDir);
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
    if (!hasNativePicker) {
      // Web mode: don't pop the OS folder picker — it can't return a usable path
      // and only confuses ("picked a folder, now paste it anyway"). Open the menu
      // straight to recents + manual paste instead.
      setShowMenu(true);
      setNoBridgeHint(true);
      if (!isMutedVariant) setBrowserOpen(true);
      requestAnimationFrame(() => {
        manualInputRef.current?.focus();
      });
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
      if (!isMutedVariant) setBrowserOpen(true);
    } finally {
      setIsPicking(false);
    }
  }, [applyWorkDir, hasNativePicker, isMutedVariant, isPicking, workDir]);

  const handleMenuToggle = useCallback(() => {
    if (isPicking) return;
    setShowMenu((v) => !v);
  }, [isPicking]);

  const handleManualSubmit = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      applyWorkDir(manualPath);
    },
    [applyWorkDir, manualPath],
  );

  const [menuRect, setMenuRect] = useState<{
    top?: number;
    bottom?: number;
    left: number;
    width: number;
    maxHeight: number;
  } | null>(null);

  const updateMenuPosition = useCallback(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const targetWidth = isMutedVariant ? 136 : MENU_WIDTH;
    const minWidth = isMutedVariant ? 128 : 280;
    const _estimatedHeight = isMutedVariant ? 56 : 260;
    const minHeight = isMutedVariant ? 48 : 240;
    const width = Math.min(
      targetWidth,
      Math.max(minWidth, window.innerWidth - MENU_MARGIN * 2),
    );
    const preferredLeft = isMutedVariant ? rect.left : rect.right - width;
    const left = Math.min(
      Math.max(MENU_MARGIN, preferredLeft),
      window.innerWidth - MENU_MARGIN - width,
    );
    const spaceBelow = window.innerHeight - rect.bottom - MENU_MARGIN;
    const spaceAbove = rect.top - MENU_MARGIN;
    const openUp = spaceAbove > spaceBelow;
    const maxHeight = Math.max(
      minHeight,
      openUp ? spaceAbove - 6 : spaceBelow - 6,
    );
    setMenuRect({
      left,
      width,
      maxHeight,
      ...(openUp
        ? { bottom: window.innerHeight - rect.top + 6 }
        : { top: rect.bottom + 6 }),
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

  // The "open folder" CTA only renders when a native picker exists (Electron),
  // so this is the native path; web mode never reaches it.
  const handleOpenFolderCta = useCallback(async () => {
    setIsPicking(true);
    try {
      const selected = await openNativeFolderPicker(workDir);
      if (selected) {
        applyWorkDir(selected);
        return;
      }
      setBrowserOpen(true);
      requestAnimationFrame(() => manualInputRef.current?.focus());
    } finally {
      setIsPicking(false);
    }
  }, [applyWorkDir, workDir]);

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
        "flex max-h-full flex-col overflow-hidden border border-border-default bg-popover/95 backdrop-blur",
        isMutedVariant
          ? "rounded-lg shadow-[var(--shadow-md)]"
          : "rounded-xl shadow-2xl",
      )}
    >
      {/* Primary entry point for adding a workspace. Only meaningful with a
          native picker (Electron); web mode leans on recents + manual paste. */}
      <div className={cn("shrink-0", isMutedVariant ? "p-1.5" : "p-2.5")}>
        {hasNativePicker && folderPickerCta}
        {isWorkDirLocked && (
          <div className="mt-1.5 rounded-md border border-primary/15 bg-primary/5 px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">
            {lockedCopy.hint}
          </div>
        )}
        {workDir && !isWorkDirLocked && (
          <button
            type="button"
            onClick={clearWorkDir}
            className={cn(
              "mt-1.5 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
              !isMutedVariant && "border border-border-default",
            )}
          >
            <FolderIcon className="size-3.5 shrink-0" />
            <span className="min-w-0 flex-1 truncate">
              {t.codeMode.personalSpace}
            </span>
          </button>
        )}

        {noBridgeHint && (
          <div className="mt-2 rounded-md border border-border-default bg-muted/40 px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">
            {webPickerHint(locale)}
          </div>
        )}
        {(!isMutedVariant || noBridgeHint) && (
          <form
            className="mt-2 flex items-center gap-1.5 rounded-lg border border-border-default bg-background/70 p-1 shadow-inner"
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

      {/* Recent workspaces — colored letter-tile + path subtitle + ✓ for the
          active one. Shown in the muted (web) menu too so there's a one-click
          way to rebind without a native picker. */}
      {(!isMutedVariant || recentWorkdirs.length > 0) && (
        <div
          className={cn(
            "border-t border-border-default",
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
            <div className="rounded-lg border border-dashed border-border-default bg-muted/20 px-2 py-3 text-center text-[11px] text-muted-foreground">
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
          className="group border-t border-border-default px-2.5 py-2"
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
      className={cn("relative flex items-center gap-1.5", className)}
    >
      <button
        className={cn(
          "group flex items-center gap-1.5 text-[11px] font-medium shadow-none transition-all duration-200",
          chromeless
            ? "h-8 rounded-lg px-1.5 text-muted-foreground hover:bg-muted/55 hover:text-foreground"
            : "h-8 rounded-lg border border-transparent bg-transparent px-2 text-muted-foreground hover:border-border-default hover:bg-muted/55 hover:text-foreground",
          isEmpty ? emptyTriggerClass : activeTriggerClass,
          isPicking && "cursor-wait opacity-50",
        )}
        onClick={workDir ? handleMenuToggle : handlePrimaryAction}
        disabled={isPicking}
        title={triggerTitle}
        type="button"
      >
        <FolderOpenIcon className="size-3 shrink-0 opacity-70" />
        <span
          className={cn(
            isMutedVariant
              ? "max-w-[120px] truncate"
              : "max-w-[160px] truncate",
            isEmpty ? "font-medium" : "tracking-normal",
          )}
        >
          {triggerLabel}
        </span>
        <ChevronDownIcon className="size-3 shrink-0 opacity-35 transition-opacity group-hover:opacity-60" />
      </button>

      {menuRect && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[100]"
              style={{
                top:
                  menuRect.top !== undefined ? `${menuRect.top}px` : undefined,
                bottom:
                  menuRect.bottom !== undefined
                    ? `${menuRect.bottom}px`
                    : undefined,
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
