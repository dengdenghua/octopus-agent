import {
  ArrowLeftIcon,
  AppWindowIcon,
  BotIcon,
  ChevronRightIcon,
  DatabaseIcon,
  DnaIcon,
  FileImageIcon,
  FileTextIcon,
  FilmIcon,
  FolderIcon,
  FolderPlusIcon,
  GlobeIcon,
  HardDriveIcon,
  ListTodoIcon,
  MessageSquarePlusIcon,
  MoreHorizontalIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  PencilIcon,
  PlusIcon,
  RssIcon,
  Trash2Icon,
  CompassIcon,
  StoreIcon,
  UserRoundPenIcon,
  type LucideIcon,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type SVGProps,
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { swallow } from "@/core/utils/log";
import { useEvent, eventBus, emitProjectsChanged } from "@/core/events";

import {
  SettingsDialog,
  normalizeSettingsSection,
  type SettingsSection,
} from "./settings/settings-dialog";
import { AgentFooter } from "./sidebar-footer";
import { FileTree } from "./file-tree";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { isIMEComposing } from "@/lib/ime";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getAPIClient } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";
import { pickLocalDirectory } from "@/core/workspace/pick-local-directory";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { useI18n } from "@/core/i18n/hooks";
import {
  useDeleteThread,
  useRenameThread,
  useThreads,
} from "@/core/threads/hooks";
import {
  buildConversationThreadSummaries,
  buildProjectThreadSummaries,
  buildThreadRunStatusByHref,
  isGeneratedTeamProjectName,
  isProjectThreadMode,
  mergeThreadRunStatus,
  normalizeThreadRunStatus,
  projectNameForThread,
  summarizeThreadForSidebar,
  syncThreadAgentSelection,
  threadHref,
  activeTeamTaskRoomId,
  activeWorkspaceThreadIdFromPathname,
  withThreadSidebarMode,
  type ThreadRunStatus,
  type ThreadSummary,
} from "@/core/threads/sidebar";
import type { AgentThread } from "@/core/threads/types";
import {
  agentRunStatusLightClass,
  agentRunStatusLightPulseClass,
} from "@/components/workspace/agent-run-status";
import { useTasks } from "@/core/tasks/hooks";
import { useTeamTasks } from "@/core/team-tasks";
import { useActiveAgentId } from "@/core/agents/active";
import { formatCompactRelativeTimestamp } from "@/core/utils/datetime";
import { basename, isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";
import { WorkspaceSurfaceHeader } from "@/components/workspace/workspace-surface-header";
import { WorkspaceSwitcher } from "@/components/workspace/workspace-switcher";

// Surface modes in the left sidebar. Chat and Company are handled by a
// dedicated two-panel switch so they feel like peer work surfaces instead
// of ordinary navigation rows.
// NOTE: label bags are now built inside the component through useI18n
// so translations respect the selected locale. Module-level constants
// capture just the route + icon.
type NavRoute = {
  to: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  labelKey?: string;
  label?: string;
};
const PRIMARY_WORKSPACE_ROUTE = "/workspace/realtime/new";
/** 助理固定对话线程 id —— 像微信一样共用一个持久会话，不随每次进入新建。
 *  侧边栏据此识别助理对话，避免生成指向自身的"当前任务会话"条目。 */
const OCTOPUS_THREAD_ID = "octopus-assistant";
// Safety net for live run-status lights that never got an explicit clear
// (abnormal turn termination, crashed producer). Generous: a long turn
// legitimately streams for many minutes between status events.
const LIVE_RUN_STATUS_TTL_MS = 30 * 60 * 1000;
const LIVE_RUN_STATUS_PRUNE_INTERVAL_MS = 60 * 1000;

const CHAT_CAPABILITY_ROUTES: NavRoute[] = [
  {
    to: "/workspace/agents?surface=chat",
    labelKey: "navHR",
    icon: StoreIcon,
  },
  {
    to: "/workspace/intelligence?surface=chat",
    labelKey: "navIntelligence",
    icon: RssIcon,
  },
  {
    // 助手（octopus）是全局上层入口，放在「订阅」下方，避免与主任务入口混淆。
    to: "/workspace/realtime/octopus-assistant?agent=octopus",
    labelKey: "navAssistant",
    icon: UserRoundPenIcon,
  },
  {
    to: "/workspace/evolution?surface=chat",
    labelKey: "navEvolution",
    icon: DnaIcon,
  },
];

const COMMUNITY_ROUTES: NavRoute[] = [
  {
    to: "/workspace/community",
    labelKey: "navCommunity",
    icon: CompassIcon,
  },
];

const STORAGE_LIBRARY_ROUTES: NavRoute[] = [
  {
    to: "/workspace/knowledge?surface=chat",
    labelKey: "navKnowledgeGraph",
    icon: DatabaseIcon,
  },
  {
    to: "/workspace/storage?surface=company&library=apps",
    labelKey: "libraryApps",
    icon: AppWindowIcon,
  },
  {
    to: "/workspace/storage?surface=company&library=docs",
    labelKey: "libraryDocs",
    icon: FileTextIcon,
  },
  {
    to: "/workspace/storage?surface=company&library=images",
    labelKey: "libraryImages",
    icon: FileImageIcon,
  },
  {
    to: "/workspace/storage?surface=company&library=videos",
    labelKey: "libraryVideos",
    icon: FilmIcon,
  },
  {
    to: "/workspace/storage?surface=company&library=computer",
    labelKey: "libraryComputer",
    icon: HardDriveIcon,
  },
];

type SidebarFileExplorerTarget = {
  project: string;
  title: string;
  threadId: string | null;
  workDir: string | null;
  href?: string;
};

const PROJECTS_KEY = "octopus.projects";
const RECENT_WORKDIRS_KEY = "octopus:recentWorkdirs";
const PROJECT_GROUPING_KEY = "octopus.sidebar.project-grouping-enabled";
const ONGOING_THREADS_LIMIT = 5;
const PROJECT_THREAD_PREVIEW_LIMIT = 6;

type OngoingThreadSummary = ThreadSummary & {
  runStatus: ThreadRunStatus;
};

function readUserProjects(): string[] {
  try {
    const raw = window.localStorage.getItem(PROJECTS_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw);
    return Array.isArray(data)
      ? (data as string[]).filter(
          (name) =>
            typeof name === "string" &&
            !!name.trim() &&
            !isGeneratedTeamProjectName(name),
        )
      : [];
  } catch (e) {
    swallow(e);
    return [];
  }
}

function writeUserProjects(names: string[]) {
  try {
    window.localStorage.setItem(
      PROJECTS_KEY,
      JSON.stringify(names.filter((name) => !isGeneratedTeamProjectName(name))),
    );
  } catch (e) {
    swallow(e, "storage");
  }
}

function rememberProjectWorkDir(path: string) {
  if (typeof window === "undefined" || !isAbsolutePath(path)) return;
  try {
    const raw = window.localStorage.getItem(RECENT_WORKDIRS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    const current = Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : [];
    const normalize = (value: string) =>
      value.trim().replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
    const next = [
      path,
      ...current.filter((item) => normalize(item) !== normalize(path)),
    ].slice(0, 6);
    window.localStorage.setItem(RECENT_WORKDIRS_KEY, JSON.stringify(next));
  } catch (e) {
    swallow(e, "storage");
  }
}

function emitWorkDirSelected(path: string) {
  if (typeof window === "undefined" || !isAbsolutePath(path)) return;
  rememberProjectWorkDir(path);
  window.dispatchEvent(
    new CustomEvent("octopus:workdir-selected", {
      detail: { path, source: "projects" },
    }),
  );
}

function readProjectGroupingEnabled(): boolean {
  try {
    const raw = window.localStorage.getItem(PROJECT_GROUPING_KEY);
    return raw === null ? true : raw === "1";
  } catch (e) {
    swallow(e);
    return true;
  }
}

/** 瞬时补位会话（运行中但未进历史列表 / 深链进入）拿不到线程元数据：
 *  team 路由可按前缀识别；其余沿用域层默认--无元数据按 chat 归入对话列表。 */
function transientThreadModeFromHref(href: string): string {
  if (/^\/workspace\/team\//.test(href)) return "team";
  return "chat";
}

function buildOngoingThreadSummaries({
  threads,
  runStatusByHref,
  limit = ONGOING_THREADS_LIMIT,
}: {
  threads: ThreadSummary[];
  runStatusByHref: Map<string, ThreadRunStatus>;
  limit?: number;
}): OngoingThreadSummary[] {
  const seen = new Set<string>();
  const statusPriority: Record<ThreadRunStatus, number> = {
    error: 4,
    waiting: 3,
    running: 2,
    pending: 1,
  };
  return threads
    .flatMap((thread) => {
      if (seen.has(thread.href)) return [];
      seen.add(thread.href);
      const runStatus = runStatusByHref.get(thread.href);
      return runStatus ? [{ ...thread, runStatus }] : [];
    })
    .sort((a, b) => {
      const byStatus =
        statusPriority[b.runStatus] - statusPriority[a.runStatus];
      if (byStatus !== 0) return byStatus;
      const aTime = a.updatedAt || "";
      const bTime = b.updatedAt || "";
      // 瞬时进行中会话没有时间戳：视为最新，排在同状态条目最前，
      // 避免正在跑的会话因空时间戳沉底。
      if (!aTime || !bTime) {
        if (!aTime && !bTime) return a.id.localeCompare(b.id);
        return aTime ? 1 : -1;
      }
      return bTime.localeCompare(aTime);
    })
    .slice(0, limit);
}

function excludeActiveThread<T extends ThreadSummary>(
  threads: T[],
  pathname: string,
): T[] {
  const activeId = activeWorkspaceThreadIdFromPathname(pathname);
  if (!activeId) return threads;
  return threads.filter((thread) => thread.id !== activeId);
}

function prioritizeActiveThread<T extends ThreadSummary>(
  threads: T[],
  pathname: string,
): T[] {
  const activeId = activeWorkspaceThreadIdFromPathname(pathname);
  if (!activeId) return threads;
  const activeIndex = threads.findIndex((thread) => thread.id === activeId);
  if (activeIndex <= 0) return threads;
  return [
    threads[activeIndex]!,
    ...threads.filter((_, index) => index !== activeIndex),
  ];
}

function projectThreadsForPreview<T>(
  threads: T[],
  showAll: boolean,
  limit = PROJECT_THREAD_PREVIEW_LIMIT,
): T[] {
  return showAll ? threads : threads.slice(0, limit);
}

export function syncedSidebarPathname(
  pathname: string,
  pendingThreadPath: string | null,
): string {
  return pendingThreadPath ?? pathname;
}

export function WorkspaceSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const { pathname, search } = useLocation();
  const { t } = useI18n();
  const { isMobile, openMobile, setOpenMobile } = useSidebar();
  const queryClient = useQueryClient();
  const apiClient = useMemo(() => getAPIClient(), []);
  // Starting from `/new` swaps in a server thread id before the live page can
  // safely remount. Use its transient route for sidebar selection until the
  // page finishes the Router transition.
  const [pendingThreadPath, setPendingThreadPath] = useState<string | null>(
    null,
  );
  useEvent("thread:route-sync", ({ href }) => setPendingThreadPath(href), []);
  useEffect(() => {
    if (!pendingThreadPath) return;
    if (
      pathname === pendingThreadPath ||
      (pathname !== "/workspace/realtime/new" && pathname !== pendingThreadPath)
    ) {
      setPendingThreadPath(null);
    }
  }, [pathname, pendingThreadPath]);
  const sidebarPathname = syncedSidebarPathname(pathname, pendingThreadPath);

  // Resolve a NavRoute's labelKey against the sidebar namespace. The cast
  // keeps TS narrowing happy without silently swallowing typos in route keys.
  const resolveLabel = useCallback(
    (key: string) =>
      (t.sidebar as unknown as Record<string, string>)[key] ?? key,
    [t],
  );
  const resolveRoutes = useCallback(
    (routes: NavRoute[]) =>
      routes.map((r) => ({
        ...r,
        label: r.label ?? (r.labelKey ? resolveLabel(r.labelKey) : r.to),
      })),
    [resolveLabel],
  );
  const chatCapabilityItems = useMemo(
    () => resolveRoutes(CHAT_CAPABILITY_ROUTES),
    [resolveRoutes],
  );
  const communityItems = useMemo(
    () => resolveRoutes(COMMUNITY_ROUTES),
    [resolveRoutes],
  );
  const nasLibraryItems = useMemo(
    () => resolveRoutes(STORAGE_LIBRARY_ROUTES),
    [resolveRoutes],
  );

  // Settings dialog state
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDefaultSection, setSettingsDefaultSection] =
    useState<SettingsSection>("appearance");
  const pendingSettingsOpenRef = useRef<number | null>(null);
  const pendingSettingsFocusRef = useRef<number | null>(null);
  const restoreSettingsFocusRef = useRef(false);

  const openSettingsSection = useCallback(
    (tab?: string) => {
      const next: SettingsSection = normalizeSettingsSection(tab);

      const openDialog = () => {
        pendingSettingsOpenRef.current = null;
        setSettingsDefaultSection(next);
        setSettingsOpen(true);
      };

      if (isMobile && openMobile) {
        restoreSettingsFocusRef.current = true;
        setOpenMobile(false);
        if (pendingSettingsOpenRef.current !== null) {
          window.clearTimeout(pendingSettingsOpenRef.current);
        }
        // Radix needs one event turn to release the Sheet's focus guards.
        // Opening the settings Dialog in the same turn leaves two modal roots
        // mounted and can immediately dismiss or trap focus behind the dialog.
        pendingSettingsOpenRef.current = window.setTimeout(openDialog, 0);
        return;
      }

      openDialog();
    },
    [isMobile, openMobile, setOpenMobile],
  );

  useEffect(
    () => () => {
      if (pendingSettingsOpenRef.current !== null) {
        window.clearTimeout(pendingSettingsOpenRef.current);
      }
      if (pendingSettingsFocusRef.current !== null) {
        window.clearTimeout(pendingSettingsFocusRef.current);
      }
    },
    [],
  );

  const handleSettingsOpenChange = useCallback((nextOpen: boolean) => {
    setSettingsOpen(nextOpen);
    if (nextOpen || !restoreSettingsFocusRef.current) return;

    restoreSettingsFocusRef.current = false;
    pendingSettingsFocusRef.current = window.setTimeout(() => {
      pendingSettingsFocusRef.current = null;
      const trigger = document.querySelector<HTMLElement>(
        '[data-sidebar="trigger"]',
      );
      if (trigger && trigger.getClientRects().length > 0) trigger.focus();
    }, 0);
  }, []);

  // Listen for open-settings event via EventBus
  useEvent(
    "ui:open-settings",
    (payload) => {
      openSettingsSection(payload.tab);
    },
    [],
  );

  useEffect(() => {
    const handler = (event: Event) => {
      const tab =
        event instanceof CustomEvent && typeof event.detail?.tab === "string"
          ? event.detail.tab
          : undefined;
      openSettingsSection(tab);
    };
    window.addEventListener("octopus:open-settings", handler);
    return () => window.removeEventListener("octopus:open-settings", handler);
  }, [openSettingsSection]);

  useEffect(() => {
    const handler = () => handleSettingsOpenChange(false);
    window.addEventListener("octopus:close-settings", handler);
    return () => window.removeEventListener("octopus:close-settings", handler);
  }, [handleSettingsOpenChange]);

  // Conversation history stays scoped to the currently-active agent
  // so the left-bottom persona switch only affects the current chat lane.
  // Solo project conversations follow the same role boundary below. Shared
  // team sessions are queried separately and remain visible to the team.
  const activeAgentId = useActiveAgentId();
  const { data: rawConversationThreads } = useThreads(
    {
      limit: 30,
      sortBy: "updated_at",
      sortOrder: "desc",
      select: ["thread_id", "updated_at", "values", "metadata"],
    },
    undefined,
    activeAgentId,
  );
  const { data: rawProjectThreads } = useThreads(
    {
      limit: 30,
      sortBy: "updated_at",
      sortOrder: "desc",
      select: ["thread_id", "updated_at", "values", "metadata"],
    },
    "code",
    activeAgentId,
  );
  const { data: rawTeamThreads } = useThreads(
    {
      limit: 30,
      sortBy: "updated_at",
      sortOrder: "desc",
      select: ["thread_id", "updated_at", "values", "metadata"],
    },
    "team",
    null,
  );

  const mergedConversationRaw = (() => {
    const m = new Map<string, AgentThread>();
    for (const t of rawConversationThreads ?? []) m.set(t.thread_id, t);
    for (const t of rawTeamThreads ?? []) {
      m.set(t.thread_id, withThreadSidebarMode(t, "team"));
    }
    return Array.from(m.values()).sort((a, b) =>
      (b.updated_at || "").localeCompare(a.updated_at || ""),
    );
  })();

  const mergedProjectRaw = (() => {
    const m = new Map<string, AgentThread>();
    for (const t of rawProjectThreads ?? []) {
      m.set(t.thread_id, withThreadSidebarMode(t, "code"));
    }
    for (const t of rawTeamThreads ?? []) {
      m.set(t.thread_id, withThreadSidebarMode(t, "team"));
    }
    return Array.from(m.values()).sort((a, b) =>
      (b.updated_at || "").localeCompare(a.updated_at || ""),
    );
  })();

  const conversationThreads: ThreadSummary[] = buildConversationThreadSummaries(
    mergedConversationRaw,
  );

  const projectThreads: ThreadSummary[] =
    buildProjectThreadSummaries(mergedProjectRaw);

  // User-defined projects (localStorage) — so an empty project still
  // shows in the sidebar before any threads are tagged with it.
  const [userProjects, setUserProjects] = useState<string[]>(() =>
    readUserProjects(),
  );
  useEffect(() => {
    const refresh = () => setUserProjects(readUserProjects());
    window.addEventListener("storage", refresh);
    window.addEventListener("octopus:projects-changed", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("octopus:projects-changed", refresh);
    };
  }, []);
  const [projectGroupingEnabled, setProjectGroupingEnabled] = useState<boolean>(
    () => readProjectGroupingEnabled(),
  );
  useEffect(() => {
    try {
      window.localStorage.setItem(
        PROJECT_GROUPING_KEY,
        projectGroupingEnabled ? "1" : "0",
      );
    } catch (e) {
      swallow(e);
    }
  }, [projectGroupingEnabled]);
  const toggleProjectGrouping = useCallback(() => {
    setProjectGroupingEnabled((enabled) => !enabled);
  }, []);

  const saveProjectName = useCallback((name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const next = Array.from(new Set([trimmed, ...readUserProjects()]));
    writeUserProjects(next);
    setUserProjects(next);
    emitProjectsChanged();
  }, []);

  // The same system chooser is used by the desktop shell and local web app.
  // In web mode the local backend opens the OS dialog and returns the absolute
  // path, which keeps the project label, workspace binding, and permissions in
  // sync instead of creating a name-only project.
  const pickProjectFolder = useCallback(async () => {
    try {
      const selected = await pickLocalDirectory();
      if (!selected) return;
      saveProjectName(basename(selected) || selected);
      emitWorkDirSelected(selected);
    } catch (error) {
      swallow(error);
      toast.error(t.sidebar.projectPickerFailed);
    }
  }, [saveProjectName, t.sidebar.projectPickerFailed]);

  // Group code/team threads by project. Team history defaults to its bound
  // workspace folder, so multi-agent work sits with the project instead of
  // falling back to loose chat recents.
  const activeThreadId = activeWorkspaceThreadIdFromPathname(sidebarPathname);

  const activeThread = useMemo(() => {
    if (!activeThreadId) return null;
    return (
      mergedConversationRaw.find((t) => t.thread_id === activeThreadId) ||
      mergedProjectRaw.find((t) => t.thread_id === activeThreadId) ||
      null
    );
  }, [activeThreadId, mergedConversationRaw, mergedProjectRaw]);

  const activeTaskWorkspacePath = useMemo(() => {
    if (activeThread) {
      const value =
        activeThread.metadata?.["workspace_path"] ??
        activeThread.values?.["workspace_path"];
      if (typeof value === "string" && isAbsolutePath(value)) return value;
    }
    const routeValue = new URLSearchParams(search).get("workspace_path") ?? "";
    return isAbsolutePath(routeValue) ? routeValue : null;
  }, [activeThread, search]);

  // Tracks the active remote-workspace id (if the thread is bound to one).
  // Threads bound to a remote workspace carry ``workspace_id`` in their
  // metadata; threads bound to a plain local path keep ``workspace_path``
  // and have no ``workspace_id``.
  const activeWorkspaceId = useMemo(() => {
    if (!activeThread) return null;
    const value =
      activeThread.metadata?.["workspace_id"] ??
      activeThread.values?.["workspace_id"];
    return typeof value === "string" && value ? value : null;
  }, [activeThread]);

  // Switching workspace persists the new ``workspace_id`` (and clears
  // ``workspace_path``) on the active thread so the rest of the app —
  // file tree, FS endpoints, members panel — re-targets to the new
  // workspace. When no thread is active we no-op; the caller can still
  // see the switch in the trigger label via the ``activeWorkspaceId``
  // prop, but persistence will happen on the next thread state update.
  const handleSwitchWorkspace = useCallback(
    async (workspace: { id: string }) => {
      if (!activeThreadId) return;
      try {
        await apiClient.threads.updateState(activeThreadId, {
          metadata: {
            workspace_id: workspace.id,
            workspace_path: "",
          },
        });
        queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      } catch (error) {
        console.error("Failed to switch workspace", error);
      }
    },
    [activeThreadId, apiClient, queryClient],
  );

  const activeTaskRoomId = activeTeamTaskRoomId(sidebarPathname, activeThread);

  const activeWorkDir = useMemo(() => {
    if (activeThread) {
      const path =
        activeThread.metadata?.["workspace_path"] ??
        activeThread.values?.["workspace_path"];
      if (typeof path === "string" && path) return path;
    }
    // Fallback: use the most-recent workdir from localStorage so the
    // file explorer is visible even on the "new task" page.
    try {
      const raw = window.localStorage.getItem(RECENT_WORKDIRS_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed) && parsed.length > 0) {
        const first = parsed[0];
        if (typeof first === "string" && first) return first;
      }
    } catch {
      /* ignore */
    }
    return null;
  }, [activeThread]);

  const [fileExplorerTarget, setFileExplorerTarget] =
    useState<SidebarFileExplorerTarget | null>(null);
  const openThreadFiles = useCallback(
    (thread: ThreadSummary, project: string) => {
      const workDir = thread.workspacePath ?? activeWorkDir;
      setFileExplorerTarget({
        project,
        title: thread.title,
        threadId: thread.id,
        workDir: workDir ?? null,
        href: thread.href,
      });
      if (workDir) emitWorkDirSelected(workDir);
    },
    [activeWorkDir],
  );

  const activeTeamTasksQuery = useTeamTasks(activeTaskRoomId);
  const activeTeamTasks = useMemo(
    () => activeTeamTasksQuery.data ?? [],
    [activeTeamTasksQuery.data],
  );
  const backgroundTasksQuery = useTasks("all");
  const threadHrefById = useMemo(() => {
    return new Map(
      mergedProjectRaw.map((thread) => [thread.thread_id, threadHref(thread)]),
    );
  }, [mergedProjectRaw]);
  // Live run status with a last-touch timestamp. Bare statuses never
  // expire: a turn that terminated without a clearing event (crashed tab,
  // abnormal stream end) left its light stuck on "running" forever. The
  // TTL below is the safety net - page unmount still clears immediately.
  const [liveThreadRunStatusByHref, setLiveThreadRunStatusByHref] = useState<
    Map<string, { status: ThreadRunStatus; at: number }>
  >(() => new Map());
  useEvent(
    "thread:run-status",
    ({ href, state, threadId }) => {
      const status = normalizeThreadRunStatus(state);
      const targetHref = href || threadHrefById.get(threadId);
      if (!targetHref) return;
      setLiveThreadRunStatusByHref((prev) => {
        if (!status && !prev.has(targetHref)) return prev;
        const next = new Map(prev);
        if (status) {
          next.set(targetHref, { status, at: Date.now() });
        } else {
          next.delete(targetHref);
        }
        return next;
      });
    },
    [threadHrefById],
  );
  useEffect(() => {
    const timer = window.setInterval(() => {
      setLiveThreadRunStatusByHref((prev) => {
        if (prev.size === 0) return prev;
        const now = Date.now();
        const next = new Map(prev);
        let changed = false;
        for (const [href, entry] of prev) {
          if (now - entry.at > LIVE_RUN_STATUS_TTL_MS) {
            next.delete(href);
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, LIVE_RUN_STATUS_PRUNE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);
  const runStatusByHref = useMemo(
    () =>
      buildThreadRunStatusByHref({
        activeTeamTasks,
        backgroundTasks: backgroundTasksQuery.data,
        liveThreadRunStatusByHref: new Map(
          Array.from(liveThreadRunStatusByHref, ([href, entry]) => [
            href,
            entry.status,
          ]),
        ),
        threadHrefById,
      }),
    [
      activeTeamTasks,
      backgroundTasksQuery.data,
      liveThreadRunStatusByHref,
      threadHrefById,
    ],
  );

  const byProject: Record<string, ThreadSummary[]> = {};
  const threadIdsByProject: Record<string, string[]> = {};
  const ungroupedProjectThreads: ThreadSummary[] = [];
  for (const name of userProjects) byProject[name] = [];
  const rawThreadMap = new Map(mergedProjectRaw.map((r) => [r.thread_id, r]));
  for (const thread of projectThreads) {
    const raw = rawThreadMap.get(thread.id);
    const meta = (raw?.metadata ?? {}) as Record<string, unknown>;
    const project = projectNameForThread(
      thread,
      meta,
      t.codeMode.personalSpace,
    );
    if (!project) {
      ungroupedProjectThreads.push(thread);
      continue;
    }
    (threadIdsByProject[project] ??= []).push(thread.id);
    (byProject[project] ??= []).push(thread);
  }
  const projectOrder = Object.keys(byProject).filter(
    (p) => (byProject[p]?.length ?? 0) > 0 || userProjects.includes(p),
  );
  // Every visible project group can be removed. Deleting a group means
  // unclassifying its conversations; local folders and thread history stay.
  const deletableProjects = new Set(projectOrder);
  const [deletingProject, setDeletingProject] = useState<string | null>(null);

  const deleteProject = async (project: string) => {
    const threadIds = threadIdsByProject[project] ?? [];
    const next = readUserProjects().filter((p) => p !== project);

    if (threadIds.length === 0) {
      writeUserProjects(next);
      setUserProjects(next);
      window.dispatchEvent(new Event("octopus:projects-changed"));
      return;
    }

    setDeletingProject(project);
    try {
      await Promise.all(
        threadIds.map((threadId) =>
          apiClient.threads.updateState(threadId, {
            metadata: { project: "", workspace_path: "" },
          }),
        ),
      );
      writeUserProjects(next);
      setUserProjects(next);
      emitProjectsChanged();
      queryClient.setQueriesData(
        { queryKey: ["threads", "search"], exact: false },
        (oldData: AgentThread[] | undefined) => {
          if (!oldData) return oldData;
          const ids = new Set(threadIds);
          return oldData.map((thread) =>
            ids.has(thread.thread_id)
              ? {
                  ...thread,
                  metadata: {
                    ...(thread.metadata ?? {}),
                    project: "",
                    workspace_path: "",
                  },
                }
              : thread,
          );
        },
      );
    } catch (error) {
      swallow(error);
      toast.error(t.sidebar.deleteProjectFailed);
    } finally {
      setDeletingProject(null);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    }
  };
  const sidebarConversationThreads = conversationThreads;
  const allHistoryThreads = [
    ...sidebarConversationThreads,
    ...ungroupedProjectThreads,
  ].sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""));
  const transientOngoingThreads = useMemo<ThreadSummary[]>(() => {
    const knownHrefs = new Set(
      [...projectThreads, ...conversationThreads].map((thread) => thread.href),
    );
    // Only the ACTIVE route may synthesize a "当前任务会话" row - its
    // agent/workspace attribution comes from the current route, so a row
    // for any other href would be mislabeled, and stale statuses for
    // sessions you already left would linger as ghost rows in 进行中.
    const activeThreadHref = sidebarPathname?.startsWith("/workspace/realtime/")
      ? sidebarPathname
      : null;
    return Array.from(runStatusByHref.keys()).flatMap((href) => {
      if (knownHrefs.has(href)) return [];
      if (!activeThreadHref || href !== activeThreadHref) return [];
      const id = activeWorkspaceThreadIdFromPathname(href);
      if (!id) return [];
      if (id === OCTOPUS_THREAD_ID) return [];
      return [
        {
          id,
          title: t.sidebar.currentTaskSession,
          updatedAt: "",
          mode: transientThreadModeFromHref(href),
          href,
          workspacePath: activeTaskWorkspacePath ?? undefined,
          agents: activeAgentId ? [activeAgentId] : [],
        },
      ];
    });
  }, [
    activeAgentId,
    activeTaskWorkspacePath,
    conversationThreads,
    projectThreads,
    runStatusByHref,
    sidebarPathname,
    t.sidebar.currentTaskSession,
  ]);
  const ongoingThreads = useMemo(
    () =>
      buildOngoingThreadSummaries({
        threads: [
          ...projectThreads,
          ...conversationThreads,
          ...transientOngoingThreads,
        ],
        runStatusByHref,
      }),
    [
      conversationThreads,
      projectThreads,
      runStatusByHref,
      transientOngoingThreads,
    ],
  );
  // Keep a fallback summary for an older/deep-linked task that was not present
  // in the bounded history queries. It is inserted into the normal Chat list
  // below instead of becoming a separate pinned conversation above navigation.
  const activeThreadSummary = useMemo<ThreadSummary | null>(() => {
    const activeId = activeWorkspaceThreadIdFromPathname(sidebarPathname);
    if (!activeId) return null;
    // 助理是固定对话，本身就是一个持久会话，不当作"当前任务"重复置顶。
    if (activeId === OCTOPUS_THREAD_ID) return null;
    return (
      [
        ...ongoingThreads,
        ...projectThreads,
        ...conversationThreads,
        ...allHistoryThreads,
      ].find((thread) => thread.id === activeId) ?? {
        id: activeId,
        title: t.sidebar.currentTaskSession,
        updatedAt: "",
        mode: transientThreadModeFromHref(sidebarPathname),
        href: sidebarPathname,
        workspacePath: activeTaskWorkspacePath ?? undefined,
        agents: activeAgentId ? [activeAgentId] : [],
      }
    );
  }, [
    activeAgentId,
    activeTaskWorkspacePath,
    allHistoryThreads,
    conversationThreads,
    ongoingThreads,
    projectThreads,
    sidebarPathname,
    t.sidebar.currentTaskSession,
  ]);
  const backgroundOngoingThreads = useMemo(
    () => excludeActiveThread(ongoingThreads, sidebarPathname),
    [ongoingThreads, sidebarPathname],
  );
  const sidebarHistoryThreads = useMemo(() => {
    if (!activeThreadSummary) return allHistoryThreads;
    const activeIsProjectThread = projectThreads.some(
      (thread) => thread.id === activeThreadSummary.id,
    );
    const activeIsInHistory = allHistoryThreads.some(
      (thread) => thread.id === activeThreadSummary.id,
    );
    if (activeIsProjectThread || activeIsInHistory) return allHistoryThreads;
    return [activeThreadSummary, ...allHistoryThreads];
  }, [activeThreadSummary, allHistoryThreads, projectThreads]);

  return (
    <>
      <Sidebar
        variant="sidebar"
        collapsible="icon"
        className={cn("border-r bg-sidebar")}
        {...props}
      >
        {/* Implementation note. */}
        <SidebarHeader className="h-11 shrink-0 border-b border-white/40 bg-transparent p-0 pl-[10px] pr-2 py-0 group-data-[collapsible=icon]:h-10 group-data-[collapsible=icon]:px-0 dark:border-white/10">
          <div className="grid h-full w-full grid-cols-[auto_minmax(0,1fr)] items-center group-data-[collapsible=icon]:flex group-data-[collapsible=icon]:justify-center">
            <WorkspaceSurfaceHeader
              // The workspace preview belongs to the Octopus task surface.
              // Only the standalone /browser route represents the AI Browser.
              active="agent"
              className="group-data-[collapsible=icon]:hidden"
            />
            <div className="flex shrink-0 items-center justify-self-end">
              <CollapseToggle compact />
            </div>
          </div>
        </SidebarHeader>

        {/* Tight body: px-1.5 py-1.5 instead of default p-2/px-2 so groups
          sit closer to the header and we win a few rows of vertical
          space back. */}
        <SidebarContent className="gap-1.5 px-2.5 py-2 group-data-[collapsible=icon]:px-1 group-data-[collapsible=icon]:py-1.5">
          {/* Workspace switcher — sits at the very top so users can flip
              between local folders and registered remote mounts without
              diving into a settings page. Hidden when the sidebar is
              collapsed to icon-only mode (the trigger label would clip). */}
          <SidebarGroup className="p-0 px-1 pb-0.5 group-data-[collapsible=icon]:hidden">
            <WorkspaceSwitcher
              activeWorkspaceId={activeWorkspaceId}
              onSwitch={handleSwitchWorkspace}
            />
          </SidebarGroup>
          <SidebarGroup className="p-0 px-1 pb-0.5 group-data-[collapsible=icon]:px-0">
            <SurfaceCreateButton
              agentId={activeAgentId}
              workspacePath={activeTaskWorkspacePath}
            />
          </SidebarGroup>
          <OngoingThreadsSection
            threads={backgroundOngoingThreads}
            pathname={sidebarPathname}
          />
          {/* Unified sidebar — no more surface branching. All navigation
            items are always visible regardless of the current route. */}
          <NavSection items={chatCapabilityItems} pathname={pathname} />
          <NavSection items={communityItems} pathname={pathname} />
          <LocalDatabaseSection
            title={resolveLabel("navDatabase")}
            items={nasLibraryItems}
            pathname={pathname}
            search={search}
          />
          {fileExplorerTarget ? (
            <ProjectFileExplorerView
              target={fileExplorerTarget}
              fallbackWorkDir={activeWorkDir}
              onBack={() => setFileExplorerTarget(null)}
            />
          ) : (
            <>
              <ProjectsSection
                groups={projectOrder}
                byProject={byProject}
                pathname={sidebarPathname}
                deletableProjects={deletableProjects}
                deletingProject={deletingProject}
                groupingEnabled={projectGroupingEnabled}
                runStatusByHref={runStatusByHref}
                onDeleteProject={deleteProject}
                onToggleGrouping={toggleProjectGrouping}
                onOpenFiles={openThreadFiles}
                onNewProject={() => void pickProjectFolder()}
              />
              <ChatsSection
                threads={sidebarHistoryThreads}
                pathname={sidebarPathname}
                label={t.sidebar.sectionChats}
                agentId={activeAgentId}
                workspacePath={activeTaskWorkspacePath}
                runStatusByHref={runStatusByHref}
              />
            </>
          )}
        </SidebarContent>

        <SidebarFooter className="border-t border-border-subtle p-1.5">
          <AgentFooter />
        </SidebarFooter>
      </Sidebar>
      {/* Keep the settings host outside the responsive Sidebar sheet.
          Radix unmounts a closed mobile SheetContent, which previously also
          unmounted this dialog and made every narrow-screen settings event a
          no-op. */}
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={handleSettingsOpenChange}
        defaultSection={settingsDefaultSection}
      />
    </>
  );
}

type NavItem = NavRoute & { label: string };

function NavSection({
  items,
  pathname,
  label,
}: {
  items: NavItem[];
  pathname: string;
  label?: string;
}) {
  return (
    <SidebarGroup className="p-0 px-1 group-data-[collapsible=icon]:px-0">
      {label && (
        <div className="px-2 pb-1 pt-2 text-xs font-medium text-muted-foreground/72 group-data-[collapsible=icon]:sr-only">
          {label}
        </div>
      )}
      <SidebarMenu className="gap-0.5">
        {items.map((item) => (
          <NavRow key={item.to} item={item} pathname={pathname} />
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}

function LocalDatabaseSection({
  title,
  items,
  pathname,
  search,
}: {
  title: string;
  items: NavItem[];
  pathname: string;
  search: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const active = isStorageRouteActive(pathname);

  return (
    <SidebarGroup className="p-0 px-1 group-data-[collapsible=icon]:px-0">
      <SidebarMenu className="gap-0.5">
        <SidebarMenuItem className="justify-center">
          <SidebarMenuButton
            isActive={active}
            tooltip={title}
            aria-current={active ? "page" : undefined}
            aria-expanded={open}
            aria-label={
              open
                ? t.sidebar.ariaCollapseLocalDatabase
                : t.sidebar.ariaExpandLocalDatabase
            }
            onClick={() => setOpen((value) => !value)}
            className={cn(
              "group/nav relative h-9 w-full opacity-76 transition-[opacity,background-color,border-color] text-sm",
              "border border-transparent hover:border-border-subtle hover:bg-muted/32 hover:opacity-100",
              "data-[active=true]:opacity-100",
              "data-[active=true]:border-sidebar-primary/18 data-[active=true]:bg-[color:color-mix(in_oklch,var(--sidebar-accent)_82%,transparent)]",
              "data-[active=true]:shadow-[var(--shadow-xs)]",
              "data-[active=true]:before:absolute data-[active=true]:before:left-0 data-[active=true]:before:top-1.5 data-[active=true]:before:bottom-1.5 data-[active=true]:before:w-[2px] data-[active=true]:before:rounded-r data-[active=true]:before:bg-sidebar-primary/85",
              "group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0",
            )}
          >
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-lg transition-colors",
                active
                  ? "bg-sidebar-primary/12 text-sidebar-primary"
                  : "text-muted-foreground group-hover/nav:text-foreground",
              )}
            >
              <DatabaseIcon className="size-[16px]" />
            </span>
            <span className="min-w-0 flex-1 truncate text-left group-data-[collapsible=icon]:hidden">
              {title}
            </span>
            <span className="flex size-5 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors group-hover/nav:bg-muted/60 group-hover/nav:text-foreground group-data-[collapsible=icon]:hidden">
              <ChevronRightIcon
                className={cn(
                  "size-3.5 transition-transform",
                  open && "rotate-90",
                )}
              />
            </span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {open && (
          <div className="space-y-0.5 pl-4 group-data-[collapsible=icon]:hidden">
            {items.map((item) => (
              <StorageLibraryRow
                key={item.to}
                item={item}
                pathname={pathname}
                search={search}
              />
            ))}
          </div>
        )}
      </SidebarMenu>
    </SidebarGroup>
  );
}

function StorageLibraryRow({
  item,
  pathname,
  search,
}: {
  item: NavItem;
  pathname: string;
  search: string;
}) {
  const active = isStorageLibraryRouteActive(pathname, search, item.to);
  const Icon = item.icon;
  return (
    <SidebarMenuItem className="justify-center">
      <SidebarMenuButton
        asChild
        isActive={active}
        tooltip={item.label}
        className={cn(
          "group/nav relative h-8 w-full opacity-72 transition-[opacity,background-color,border-color] text-xs",
          "border border-transparent hover:border-border-subtle hover:bg-muted/32 hover:opacity-100",
          "data-[active=true]:opacity-100 data-[active=true]:bg-[color:color-mix(in_oklch,var(--sidebar-accent)_58%,transparent)]",
        )}
      >
        <Link
          to={item.to}
          aria-current={active ? "page" : undefined}
          className="flex items-center gap-2"
        >
          <span
            className={cn(
              "flex size-5 shrink-0 items-center justify-center rounded-lg transition-colors",
              active
                ? "text-sidebar-primary"
                : "text-muted-foreground group-hover/nav:text-foreground",
            )}
          >
            <Icon className="size-[14px]" />
          </span>
          <span className="truncate">{item.label}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function routePath(to: string): string {
  return to.split(/[?#]/)[0] || to;
}

function routeSearch(to: string): string {
  const index = to.indexOf("?");
  return index === -1 ? "" : to.slice(index);
}

function routeSearchFromLocation(pathname: string, search: string): string {
  if (search) return search;
  const index = pathname.indexOf("?");
  return index === -1 ? "" : pathname.slice(index);
}

function libraryFromLocation(pathname: string, search: string): string {
  const searchValue = routeSearchFromLocation(pathname, search);
  return new URLSearchParams(searchValue).get("library") || "overview";
}

function isStorageRouteActive(pathname: string) {
  const path = routePath(pathname);
  return (
    path === "/workspace/storage" ||
    path.startsWith("/workspace/storage/") ||
    path === "/workspace/nas" ||
    path.startsWith("/workspace/nas/") ||
    path === "/workspace/database" ||
    path.startsWith("/workspace/database/") ||
    path === "/workspace/knowledge" ||
    path.startsWith("/workspace/knowledge/")
  );
}

function isStorageLibraryRouteActive(
  pathname: string,
  search: string,
  to: string,
) {
  const targetPath = routePath(to);
  // Knowledge graph has its own route, not a ?library= param.
  if (targetPath === "/workspace/knowledge") {
    const path = routePath(pathname);
    return (
      path === "/workspace/knowledge" ||
      path.startsWith("/workspace/knowledge/")
    );
  }
  if (!isStorageRouteActive(pathname)) return false;
  const targetLibrary = new URLSearchParams(routeSearch(to)).get("library");
  if (!targetLibrary) return false;
  return libraryFromLocation(pathname, search) === targetLibrary;
}

function isNavRouteActive(pathname: string, to: string) {
  const path = routePath(to);
  if (path === PRIMARY_WORKSPACE_ROUTE) {
    return isChatSurfaceRoute(pathname);
  }
  return pathname === path || pathname.startsWith(`${path}/`);
}

function isChatSurfaceRoute(pathname: string) {
  return (
    pathname === "/workspace/realtime" || pathname === "/workspace/realtime/new"
  );
}

function isCompanySurfaceRoute(pathname: string) {
  return (
    pathname === "/workspace/agents" ||
    pathname.startsWith("/workspace/agents/") ||
    pathname === "/workspace/intelligence" ||
    pathname.startsWith("/workspace/intelligence/") ||
    pathname === "/workspace/storage" ||
    pathname.startsWith("/workspace/storage/") ||
    pathname === "/workspace/nas" ||
    pathname.startsWith("/workspace/nas/") ||
    pathname === "/workspace/database" ||
    pathname.startsWith("/workspace/database/") ||
    pathname === "/workspace/evolution" ||
    pathname.startsWith("/workspace/evolution/") ||
    pathname === "/workspace/knowledge" ||
    pathname.startsWith("/workspace/knowledge/")
  );
}

function isCompanySurfaceActive(pathname: string, search = "") {
  if (isAgentSurfaceActive(pathname, search)) return false;
  const surfaceParam = new URLSearchParams(search).get("surface");
  return (
    surfaceParam === "company" ||
    (surfaceParam !== "chat" && isCompanySurfaceRoute(pathname))
  );
}

function isAgentSurfaceActive(pathname: string, search = "") {
  const params = new URLSearchParams(search);
  return (
    (pathname === "/workspace/agents" &&
      (params.get("surface") === "chat" ||
        params.get("hud") === "1" ||
        params.get("return") === "hud")) ||
    (pathname.startsWith("/workspace/agents/") &&
      (params.get("surface") === "chat" ||
        params.get("hud") === "1" ||
        params.get("return") === "hud"))
  );
}

function ProjectFileExplorerView({
  target,
  fallbackWorkDir,
  onBack,
}: {
  target: SidebarFileExplorerTarget;
  fallbackWorkDir: string | null;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const [eventWorkDir, setEventWorkDir] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { path?: string } | undefined;
      if (detail?.path && typeof detail.path === "string") {
        setEventWorkDir(detail.path);
      }
    };
    window.addEventListener("octopus:workdir-selected", handler);
    return () =>
      window.removeEventListener("octopus:workdir-selected", handler);
  }, []);

  const resolvedWorkDir =
    target.workDir ??
    fallbackWorkDir ??
    eventWorkDir ??
    (() => {
      try {
        const raw = window.localStorage.getItem(RECENT_WORKDIRS_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        if (Array.isArray(parsed) && parsed.length > 0) {
          const first = parsed[0];
          if (typeof first === "string" && first) return first;
        }
      } catch {
        /* ignore */
      }
      return null;
    })();

  const hasWorkDir = Boolean(resolvedWorkDir);

  return (
    <div className="mt-2 min-h-0 group-data-[collapsible=icon]:hidden">
      <SidebarGroup className="p-0 px-2 pb-1">
        <div className="flex h-9 items-center gap-2 px-1 text-sm">
          <button
            type="button"
            onClick={onBack}
            title={t.sidebar.backToProjectList}
            aria-label={t.sidebar.backToProjectList}
            className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg text-left text-foreground/85 transition-colors hover:text-foreground"
          >
            <ArrowLeftIcon className="size-4 shrink-0" />
            <span className="truncate">{t.sidebar.backToProjectList}</span>
          </button>
          <button
            type="button"
            className="flex size-8 items-center justify-center rounded-lg text-muted-foreground/75 transition-colors hover:bg-muted/55 hover:text-foreground"
            title={t.codeMode.explorer}
            aria-label={t.codeMode.explorer}
          >
            <ListTodoIcon className="size-3.5" />
          </button>
        </div>
        <div className="mt-1 flex h-8 items-center gap-2 rounded-lg px-1 text-sm text-muted-foreground">
          <FolderIcon className="size-4 shrink-0 opacity-75" />
          <span className="min-w-0 flex-1 truncate">
            {resolvedWorkDir ? basename(resolvedWorkDir) : target.project}
          </span>
        </div>
        <div className="mt-0.5 overflow-hidden rounded-lg">
          {hasWorkDir && resolvedWorkDir ? (
            <FileTree
              workDir={resolvedWorkDir}
              threadId={target.threadId}
              className="max-h-[calc(100vh-18rem)]"
              onFileClick={(path) => {
                window.dispatchEvent(
                  new CustomEvent("octopus:open-file", {
                    detail: {
                      path,
                      workDir: resolvedWorkDir,
                      threadId: target.threadId,
                      sourceLabel: target.title,
                    },
                  }),
                );
              }}
            />
          ) : (
            <div className="flex flex-col items-center gap-2 p-4 text-center text-xs text-muted-foreground">
              <FolderIcon className="size-8 opacity-40" />
              <p>{t.agentWorkbenchPages.noWorkDirDescription}</p>
            </div>
          )}
        </div>
      </SidebarGroup>
    </div>
  );
}

export const __testing = {
  buildThreadRunStatusByHref,
  isProjectThreadMode,
  isNavRouteActive,
  isCompanySurfaceActive,
  isAgentSurfaceActive,
  buildConversationThreadSummaries,
  buildProjectThreadSummaries,
  mergeThreadRunStatus,
  projectNameForThread,
  summarizeThreadForSidebar,
  withThreadSidebarMode,
  buildProjectSectionActions,
  buildChatsSectionActions,
  buildOngoingThreadSummaries,
  transientThreadModeFromHref,
  excludeActiveThread,
  prioritizeActiveThread,
  projectThreadsForPreview,
  syncedSidebarPathname,
  activeTeamTaskRoomId,
};

type WorkspaceSurfaceMode = "agent" | "browser";

export function WorkspaceSurfaceSwitch({
  active,
}: {
  active: WorkspaceSurfaceMode;
}) {
  const { t } = useI18n();
  const items = [
    {
      to: PRIMARY_WORKSPACE_ROUTE,
      label: t.desktop.header.brand,
      icon: BotIcon,
      value: "agent" as const,
      kind: "brand" as const,
    },
    {
      to: "/browser",
      label: t.sidebar.navBrowserSurface,
      icon: GlobeIcon,
      value: "browser" as const,
      kind: "icon" as const,
    },
  ];
  const activeIndex = items.findIndex((item) => item.value === active);
  const radiusVar = "var(--appearance-radius-control)";

  return (
    <div
      className={cn(
        "relative grid h-8 items-center gap-0 p-0.5",
        "w-[96px] grid-cols-[minmax(0,1fr)_28px]",
        "border border-border-default bg-muted/40",
        "group-data-[collapsible=icon]:hidden",
      )}
      style={{ borderRadius: radiusVar }}
      role="tablist"
      aria-label="Workspace surface"
    >
      <span
        className={cn(
          "absolute top-0.5 bottom-0.5 z-0",
          "bg-background shadow-[var(--shadow-xs)] ring-1 ring-border-default",
          "transition-[left,width]",
          activeIndex === 0
            ? "left-[2px] w-[calc(100%-32px)]"
            : "left-[calc(100%-26px)] w-[24px]",
        )}
        style={{ borderRadius: `calc(${radiusVar} - 4px)` }}
        aria-hidden="true"
      />
      {items.map((item, index) => {
        const Icon = item.icon;
        const isActive = index === activeIndex;
        return (
          <Link
            key={item.to}
            to={item.to}
            aria-current={isActive ? "page" : undefined}
            aria-label={item.label}
            title={item.label}
            role="tab"
            aria-selected={isActive}
            className={cn(
              "relative z-10 flex h-7 items-center justify-center",
              "text-xs font-medium",
              "transition-colors",
              isActive
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground",
              item.kind === "brand" ? "px-0.5" : "px-0",
              "group-data-[collapsible=icon]:grid group-data-[collapsible=icon]:size-7 group-data-[collapsible=icon]:place-items-center group-data-[collapsible=icon]:px-0",
              isActive
                ? "group-data-[collapsible=icon]:flex"
                : "group-data-[collapsible=icon]:hidden",
            )}
            style={{ borderRadius: `calc(${radiusVar} - 4px)` }}
          >
            <Icon
              className={cn(
                "size-3.5 shrink-0",
                item.kind === "brand" &&
                  "hidden group-data-[collapsible=icon]:block",
              )}
            />
            {item.kind === "brand" && (
              <span className="min-w-0 truncate group-data-[collapsible=icon]:sr-only">
                {item.label}
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}

function SurfaceCreateButton({
  agentId,
  workspacePath,
}: {
  agentId?: string | null;
  workspacePath?: string | null;
}) {
  const { t } = useI18n();

  return (
    <button
      type="button"
      title={t.sidebar.actionNewTask}
      aria-label={t.sidebar.actionNewTask}
      onClick={() =>
        eventBus.emit("task:new", {
          agentId: agentId || undefined,
          workspacePath: workspacePath || undefined,
        })
      }
      className="flex h-8 w-full shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border-default bg-background/60 px-3 text-xs font-medium text-muted-foreground transition-[background-color,border-color,color] hover:border-border hover:bg-background hover:text-foreground group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:translate-x-[3px] group-data-[collapsible=icon]:px-0"
    >
      <PlusIcon className="size-4" />
      <span className="group-data-[collapsible=icon]:sr-only">
        {t.sidebar.actionNewTask}
      </span>
    </button>
  );
}

function NavRow({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = isNavRouteActive(pathname, item.to);
  const Icon = item.icon;
  return (
    <SidebarMenuItem className="justify-center">
      <SidebarMenuButton
        asChild
        isActive={active}
        tooltip={item.label}
        className={cn(
          "group/nav relative h-9 w-full opacity-76 transition-[opacity,background-color,border-color] text-sm",
          "border border-transparent hover:border-border-subtle hover:bg-muted/32 hover:opacity-100",
          "data-[active=true]:opacity-100",
          "data-[active=true]:border-sidebar-primary/18 data-[active=true]:bg-[color:color-mix(in_oklch,var(--sidebar-accent)_82%,transparent)]",
          "data-[active=true]:shadow-[var(--shadow-xs)]",
          "data-[active=true]:before:absolute data-[active=true]:before:left-0 data-[active=true]:before:top-1.5 data-[active=true]:before:bottom-1.5 data-[active=true]:before:w-[2px] data-[active=true]:before:rounded-r data-[active=true]:before:bg-sidebar-primary/85",
        )}
      >
        <Link
          to={item.to}
          aria-current={active ? "page" : undefined}
          className="flex items-center gap-2 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:gap-0"
        >
          <span
            className={cn(
              "flex size-6 shrink-0 items-center justify-center rounded-lg transition-colors",
              active
                ? "bg-sidebar-primary/12 text-sidebar-primary"
                : "text-muted-foreground group-hover/nav:text-foreground",
            )}
          >
            <Icon className="size-[16px]" />
          </span>
          <span className="group-data-[collapsible=icon]:hidden">
            {item.label}
          </span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

/** WeChat-style avatar block for a thread row.
 *
 *   - 1 agent  → single round avatar
 *   - 2-4      → 2×2 grid
 *   - 5-9      → 3×3 grid
 *   - 0        → fallback initial (the FolderIcon's space — a soft gray dot
 *                with no avatar URL · solo team threads with no roster yet)
 *
 *  Each cell is the agent avatar fetched from
 *  ``/api/agents/{name}/avatar``. The img onError flips to a colored
 *  initial fallback so a missing avatar doesn't show a broken-image
 *  glyph. The whole block is rounded-lg to mimic WeChat's group icon. */
function ThreadAvatar({
  agents,
  className,
}: {
  agents: string[];
  className?: string;
}) {
  const list = agents.slice(0, 9);
  const isGroup = list.length >= 2;
  // Decide the grid columns. WeChat uses 2-col for 2-4 members,
  // 3-col for 5-9. Single avatar gets a plain round image.
  const cols = list.length <= 1 ? 1 : list.length <= 4 ? 2 : 3;
  if (list.length === 0) {
    return (
      <span
        className={cn(
          "inline-block rounded-full bg-muted/60 flex-shrink-0",
          className,
        )}
      />
    );
  }
  if (!isGroup) {
    return (
      <AvatarCell
        agentId={list[0]!}
        className={cn("rounded-full overflow-hidden", className)}
      />
    );
  }
  return (
    <span
      className={cn(
        "grid bg-muted/30 rounded-lg overflow-hidden flex-shrink-0",
        className,
      )}
      style={{
        gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        // Tiny gap between cells like WeChat
        gap: "1px",
      }}
    >
      {list.map((id, i) => (
        <AvatarCell
          key={`${id}-${i}`}
          agentId={id}
          className="block w-full h-full"
        />
      ))}
    </span>
  );
}

function ThreadRunStatusLight({
  active,
  className,
  idle = "hidden",
  status,
}: {
  active?: boolean;
  className?: string;
  idle?: "hidden" | "queue";
  status?: ThreadRunStatus;
}) {
  const { t } = useI18n();
  if (!status) {
    if (idle === "hidden") return null;
    return (
      <span
        aria-hidden="true"
        className={cn(
          "relative inline-flex size-2 shrink-0 items-center justify-center rounded-full",
          active
            ? "border border-muted-foreground/40 bg-muted-foreground/60"
            : "border border-muted-foreground/60 bg-muted-foreground/20",
          className,
        )}
        data-thread-queue-indicator="idle"
      />
    );
  }
  const label =
    status === "running"
      ? t.sidebar.taskStatusRunning
      : status === "error"
        ? t.sidebar.taskStatusFailed
        : status === "waiting"
          ? t.agentWorkbench.waitingToContinue
          : t.sidebar.taskStatusPending;
  const colorClass = agentRunStatusLightClass(status);
  const pulseClass = agentRunStatusLightPulseClass(status);

  return (
    <span
      aria-label={label}
      role="img"
      title={label}
      className={cn(
        "relative inline-flex size-2 shrink-0 items-center justify-center rounded-full",
        className,
      )}
    >
      {pulseClass && (
        <span
          className={cn(
            "absolute inline-flex size-3 rounded-full opacity-25",
            colorClass,
            pulseClass,
          )}
        />
      )}
      <span
        className={cn(
          "relative inline-flex size-2 rounded-full shadow-[var(--shadow-xs)]",
          colorClass,
        )}
      />
    </span>
  );
}

/** One image cell · falls back to a colored initial circle if the
 *  backend has no avatar for the agent (404 on
 *  ``/api/agents/<id>/avatar``). The initial fallback uses a hash-based
 *  color so different agents don't all blend into the same grey. */
function AvatarCell({
  agentId,
  className,
}: {
  agentId: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span
        className={cn(
          "flex items-center justify-center bg-muted text-micro font-semibold uppercase text-muted-foreground",
          className,
        )}
        title={agentId}
      >
        {(agentId[0] || "?").toUpperCase()}
      </span>
    );
  }
  return (
    <img
      src={withAgentAvatarVersion(
        `${getBackendBaseURL()}/api/agents/${encodeURIComponent(agentId)}/avatar`,
      )}
      alt={agentId}
      title={agentId}
      onError={() => setFailed(true)}
      className={cn("object-cover", className)}
    />
  );
}

function ProjectGroupIcon({ project: _project }: { project: string }) {
  return <FolderIcon className="size-[18px] shrink-0 opacity-70" />;
}

function threadRunStatusLabel(
  status: ThreadRunStatus,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (status === "running") return t.sidebar.taskStatusRunning;
  if (status === "error") return t.sidebar.taskStatusFailed;
  if (status === "waiting") return t.agentWorkbench.waitingToContinue;
  return t.sidebar.taskStatusPending;
}

function OngoingThreadsSection({
  pathname,
  threads,
}: {
  pathname: string;
  threads: OngoingThreadSummary[];
}) {
  const { t } = useI18n();
  if (threads.length === 0) return null;

  return (
    <SidebarGroup className="p-0 px-1 pb-0.5 group-data-[collapsible=icon]:hidden">
      <div className="mb-1 flex items-center gap-1.5 px-2 text-mini font-medium text-muted-foreground/72">
        <ListTodoIcon className="size-3.5" />
        <span>{t.sidebar.sectionOngoing}</span>
        <span className="ml-auto font-mono text-micro text-muted-foreground/55">
          {threads.length}
        </span>
      </div>
      <SidebarMenu className="gap-0.5">
        {threads.map((thread) => {
          const active =
            activeWorkspaceThreadIdFromPathname(pathname) === thread.id;
          const statusLabel = threadRunStatusLabel(thread.runStatus, t);
          return (
            <SidebarMenuItem key={thread.href} className="group/ongoing">
              <SidebarMenuButton
                isActive={active}
                asChild
                tooltip={`${statusLabel} · ${thread.title}`}
                className={cn(
                  "h-auto min-h-9 rounded-lg border border-transparent px-2 py-1.5",
                  "bg-[color:color-mix(in_oklch,var(--sidebar-accent)_38%,transparent)] text-foreground/86",
                  "hover:border-border-subtle hover:bg-[color:color-mix(in_oklch,var(--sidebar-accent)_60%,transparent)] hover:text-foreground",
                  active &&
                    "border-sidebar-primary/18 bg-[color:color-mix(in_oklch,var(--sidebar-accent)_78%,transparent)] text-foreground",
                )}
              >
                <Link
                  to={thread.href}
                  state={{
                    threadOwnerAgentId:
                      thread.agents.length === 1 ? thread.agents[0] : undefined,
                    workspacePath: thread.workspacePath,
                  }}
                  onMouseDown={() => syncThreadAgentSelection(thread.agents)}
                  aria-current={active ? "page" : undefined}
                  title={`${statusLabel} · ${thread.title}`}
                >
                  <span aria-hidden="true" className="relative shrink-0">
                    <ThreadAvatar
                      agents={thread.agents}
                      className="size-5 shrink-0"
                    />
                    <ThreadRunStatusLight
                      status={thread.runStatus}
                      className="absolute -bottom-0.5 -right-0.5 ring-2 ring-sidebar"
                    />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs leading-tight">
                      {thread.title}
                    </span>
                    <span className="mt-0.5 flex min-w-0 items-center gap-1 text-micro leading-none text-muted-foreground/72">
                      <span className="truncate">{statusLabel}</span>
                      <span aria-hidden="true">·</span>
                      <span className="shrink-0 font-mono">
                        {formatCompactRelativeTimestamp(thread.updatedAt)}
                      </span>
                    </span>
                  </span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}

function ProjectGroup({
  project,
  threads,
  pathname,
  deletable,
  deleting,
  runStatusByHref,
  onDeleteProject,
  onOpenFiles,
}: {
  project: string;
  threads: ThreadSummary[];
  pathname: string;
  deletable: boolean;
  deleting: boolean;
  runStatusByHref: Map<string, ThreadRunStatus>;
  onDeleteProject: (project: string) => void | Promise<void>;
  onOpenFiles: (thread: ThreadSummary, project: string) => void;
}) {
  const { t } = useI18n();
  const containsActiveThread = threads.some(
    (thread) => activeWorkspaceThreadIdFromPathname(pathname) === thread.id,
  );
  const orderedThreads = prioritizeActiveThread(threads, pathname);
  // Project folders are an archive, not the primary task surface. Start them
  // folded unless they contain the active task; this keeps the sidebar useful
  // during a live conversation instead of filling it with old sessions.
  const [open, setOpen] = useState(() => containsActiveThread);
  const [showAllThreads, setShowAllThreads] = useState(false);
  useEffect(() => {
    if (containsActiveThread) setOpen(true);
  }, [containsActiveThread]);
  useEffect(() => {
    if (!open) setShowAllThreads(false);
  }, [open]);
  const hiddenThreadCount = Math.max(
    0,
    orderedThreads.length - PROJECT_THREAD_PREVIEW_LIMIT,
  );
  const visibleThreads = projectThreadsForPreview(
    orderedThreads,
    showAllThreads,
  );
  const deleteThread = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();
  const navigate = useNavigate();
  const { confirm, confirmDialog } = useConfirmDialog();
  const [threadToRename, setThreadToRename] = useState<ThreadSummary | null>(
    null,
  );
  const [renameValue, setRenameValue] = useState("");
  const handleRenameSubmit = useCallback(() => {
    if (threadToRename && renameValue.trim()) {
      renameThread({ threadId: threadToRename.id, title: renameValue.trim() });
      setThreadToRename(null);
      setRenameValue("");
    }
  }, [renameThread, threadToRename, renameValue]);
  const handleDeleteThread = async (thread: ThreadSummary) => {
    const ok = await confirm({
      title: t.sidebar.deleteThreadTooltip,
      description: t.sidebar.confirmDeleteThread(thread.title),
    });
    if (!ok) return;
    deleteThread.mutate({ threadId: thread.id });
    if (pathname === thread.href) {
      void navigate(PRIMARY_WORKSPACE_ROUTE);
    }
  };
  const handleDeleteProject = async (project: string) => {
    const ok = await confirm({
      title: t.sidebar.confirmDeleteProjectTitle,
      description: t.sidebar.confirmDeleteProject(project),
    });
    if (!ok) return;
    void onDeleteProject(project);
  };
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <SidebarGroup className="p-0 px-2 py-1">
        <div className="group/project relative">
          <CollapsibleTrigger
            className={cn(
              "flex h-9 w-full items-center gap-2 rounded-lg px-1 text-sm",
              deletable ? "pr-8" : "pr-1",
              "text-foreground/85 hover:text-foreground hover:bg-muted/40 transition-colors",
              "outline-none focus-visible:ring-1 focus-visible:ring-ring/45 focus-visible:ring-inset",
            )}
          >
            <ProjectGroupIcon project={project} />
            <span className="truncate">{project}</span>
            <span
              className={cn(
                "ml-auto text-xs text-muted-foreground/60 shrink-0 transition-opacity",
                deletable && "group-hover/project:opacity-0",
              )}
            >
              {threads.length}
            </span>
          </CollapsibleTrigger>
          {deletable && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  title={t.common.more}
                  aria-label={`${t.common.more}：${project}`}
                  disabled={deleting}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                  }}
                  className={cn(
                    "absolute right-0.5 top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground/70 opacity-100 transition-[opacity,background-color,color] duration-fast sm:text-muted-foreground/60 sm:opacity-0",
                    "sm:group-hover/project:opacity-100 sm:group-focus-within/project:opacity-100 hover:bg-muted/55 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 data-[state=open]:opacity-100",
                    deleting && "cursor-wait opacity-100",
                  )}
                >
                  {deleting ? (
                    <span className="size-3 animate-spin rounded-full border border-current border-t-transparent" />
                  ) : (
                    <MoreHorizontalIcon className="size-3.5" />
                  )}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" side="right">
                {threads[0] ? (
                  <DropdownMenuItem
                    onSelect={() => onOpenFiles(threads[0]!, project)}
                  >
                    <FolderIcon className="text-muted-foreground" />
                    <span>{t.sidebar.openThreadFilesTooltip}</span>
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem onSelect={() => setOpen((value) => !value)}>
                  <ChevronRightIcon
                    className={cn(
                      "text-muted-foreground transition-transform",
                      open && "rotate-90",
                    )}
                  />
                  <span>
                    {open
                      ? t.sidebar.collapseSection(t.sidebar.sectionProjects)
                      : t.sidebar.expandSection(t.sidebar.sectionProjects)}
                  </span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={deleting}
                  onSelect={() => void handleDeleteProject(project)}
                  variant="destructive"
                >
                  <Trash2Icon />
                  <span>{t.sidebar.deleteProjectTooltip}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
        <CollapsibleContent className="overflow-hidden">
          {/* Keep task content indented, but let the active/hover bar span
              the full project lane like TRAE's code sidebar. */}
          <ul className="mt-1 space-y-0.5">
            {visibleThreads.map((thread) => {
              const active =
                activeWorkspaceThreadIdFromPathname(pathname) === thread.id;
              const runStatus = runStatusByHref.get(thread.href);
              return (
                <li key={thread.id} className="group/thread relative">
                  <Link
                    to={thread.href}
                    state={{
                      threadOwnerAgentId:
                        thread.agents.length === 1
                          ? thread.agents[0]
                          : undefined,
                      workspacePath: thread.workspacePath,
                    }}
                    onMouseDown={() => syncThreadAgentSelection(thread.agents)}
                    aria-current={active ? "page" : undefined}
                    title={thread.title}
                    className={cn(
                      "flex min-h-9 w-full min-w-0 items-center gap-2 rounded-lg py-1.5 pl-3 pr-3 text-[13px] text-foreground/78 transition-[padding,background-color,color] duration-fast group-hover/thread:pr-[4.25rem] group-focus-within/thread:pr-[4.25rem]",
                      "hover:bg-muted/40 hover:text-foreground",
                      "outline-none focus-visible:ring-1 focus-visible:ring-ring/45 focus-visible:ring-inset",
                      active &&
                        "text-foreground bg-[color:color-mix(in_oklch,var(--sidebar-accent)_62%,transparent)] shadow-[inset_2px_0_0_color-mix(in_oklch,var(--primary)_60%,transparent)]",
                    )}
                  >
                    <span className="relative flex size-5 shrink-0 items-center justify-center">
                      {active ? (
                        <>
                          <span aria-hidden="true">
                            <ThreadAvatar
                              agents={thread.agents}
                              className="size-5 shrink-0"
                            />
                          </span>
                          <ThreadRunStatusLight
                            status={runStatus}
                            className="absolute -bottom-0.5 -right-0.5 ring-2 ring-sidebar"
                          />
                        </>
                      ) : (
                        <ThreadRunStatusLight idle="queue" status={runStatus} />
                      )}
                    </span>
                    <span className="line-clamp-2 min-w-0 flex-1 break-words leading-tight">
                      {thread.title}
                    </span>
                    <span
                      className={cn(
                        "overflow-hidden whitespace-nowrap text-mini text-muted-foreground transition-[width,opacity,color] duration-fast group-hover/thread:text-muted-foreground/90",
                        active
                          ? "w-0 opacity-0"
                          : "w-10 opacity-100 group-hover/thread:w-0 group-hover/thread:opacity-0 group-focus-within/thread:w-0 group-focus-within/thread:opacity-0",
                      )}
                    >
                      {formatCompactRelativeTimestamp(thread.updatedAt)}
                    </span>
                  </Link>
                  <button
                    type="button"
                    title={t.sidebar.openThreadFilesTooltip}
                    aria-label={t.sidebar.openThreadFilesTooltip}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onOpenFiles(thread, project);
                    }}
                    className={cn(
                      "absolute right-0.5 top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground/65 opacity-0 transition-[opacity,background-color,color] duration-fast",
                      "group-hover/thread:opacity-100 hover:bg-muted/55 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50",
                    )}
                  >
                    <ListTodoIcon className="size-3.5" />
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        title={t.common.more}
                        aria-label={t.common.more}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                        className="absolute right-8 top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground/60 opacity-0 transition-opacity hover:bg-muted/40 hover:text-foreground group-hover/thread:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 data-[state=open]:opacity-100"
                      >
                        <MoreHorizontalIcon className="size-3.5" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" side="right">
                      <DropdownMenuItem
                        onSelect={() => {
                          setThreadToRename(thread);
                          setRenameValue(thread.title);
                        }}
                      >
                        <PencilIcon className="text-muted-foreground" />
                        <span>{t.common.rename}</span>
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        disabled={deleteThread.isPending}
                        onSelect={() => void handleDeleteThread(thread)}
                      >
                        <Trash2Icon />
                        <span>{t.sidebar.deleteThreadTooltip}</span>
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </li>
              );
            })}
          </ul>
          {hiddenThreadCount > 0 && (
            <button
              type="button"
              aria-expanded={showAllThreads}
              onClick={() => setShowAllThreads((visible) => !visible)}
              className="mt-1 flex min-h-8 w-full items-center gap-2 rounded-lg px-3 text-xs text-muted-foreground/75 transition-colors hover:bg-muted/35 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <ChevronRightIcon
                className={cn(
                  "size-3 shrink-0 transition-transform",
                  showAllThreads && "rotate-90",
                )}
              />
              <span className="truncate">
                {showAllThreads
                  ? t.sidebar.showFewerProjectThreads
                  : t.sidebar.showMoreProjectThreads(hiddenThreadCount)}
              </span>
            </button>
          )}
        </CollapsibleContent>
      </SidebarGroup>
      <Dialog
        open={threadToRename !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setThreadToRename(null);
            setRenameValue("");
          }
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="w-[min(360px,calc(100vw-2rem))] gap-3 rounded-lg p-4 sm:max-w-[360px]"
        >
          <DialogHeader className="gap-1 text-left">
            <DialogTitle className="text-base">{t.common.rename}</DialogTitle>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isIMEComposing(e)) {
                e.preventDefault();
                handleRenameSubmit();
              }
            }}
            autoFocus
            className="h-8 text-sm"
          />
          <DialogFooter className="mt-1 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setThreadToRename(null);
                setRenameValue("");
              }}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!renameValue.trim()}
              onClick={handleRenameSubmit}
            >
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </Collapsible>
  );
}

interface SectionAction {
  icon: LucideIcon;
  label: string;
  ariaLabel?: string;
  active?: boolean;
  onClick?: () => void;
  href?: string;
  menuItems?: SectionAction[];
}

function buildProjectSectionActions({
  groupingEnabled,
  newProjectLabel,
  onNewProject,
}: {
  groupingEnabled: boolean;
  newProjectLabel: string;
  onNewProject: () => void;
}): SectionAction[] {
  if (!groupingEnabled) return [];
  return [
    {
      icon: FolderPlusIcon,
      label: newProjectLabel,
      onClick: onNewProject,
    },
  ];
}

function buildChatsSectionActions({
  sectionLabel,
  actionLabel,
  onNewChat,
}: {
  sectionLabel: string;
  actionLabel: string;
  onNewChat: () => void;
}): SectionAction[] {
  return [
    {
      icon: MessageSquarePlusIcon,
      label: actionLabel,
      ariaLabel: `${sectionLabel} · ${actionLabel}`,
      onClick: onNewChat,
    },
  ];
}

/* Implementation note. */
function SectionHeader({
  label,
  actions,
  open,
  onToggleOpen,
}: {
  label: string;
  actions?: SectionAction[];
  /** If provided, the header becomes a collapse trigger (chevron ▶/▼). */
  open?: boolean;
  onToggleOpen?: () => void;
}) {
  const { t } = useI18n();
  const hasToggle =
    typeof open === "boolean" && typeof onToggleOpen === "function";
  return (
    <div className="group/section flex h-9 items-center justify-between gap-2 px-1">
      {hasToggle ? (
        <button
          type="button"
          onClick={onToggleOpen}
          title={
            open
              ? t.sidebar.collapseSection(label)
              : t.sidebar.expandSection(label)
          }
          aria-label={
            open
              ? t.sidebar.collapseSection(label)
              : t.sidebar.expandSection(label)
          }
          aria-expanded={open}
          className={cn(
            "flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-lg px-1 text-left text-sm font-medium transition-[background-color,color] outline-none focus-visible:ring-1 focus-visible:ring-ring/45",
            open
              ? "text-foreground/80"
              : "text-muted-foreground hover:bg-muted/35 hover:text-foreground",
          )}
        >
          {/* Implementation note. */}
          <ChevronRightIcon
            className={cn(
              "size-3 shrink-0 transition-transform duration-fast",
              open && "rotate-90",
            )}
          />
          <span className="truncate">{label}</span>
        </button>
      ) : (
        <span className="text-sm font-medium text-muted-foreground">
          {label}
        </span>
      )}
      {actions && actions.length > 0 && (
        <div className="flex items-center gap-0.5">
          {actions.map((a) => {
            const Icon = a.icon;
            const cls = cn(
              "flex size-8 items-center justify-center rounded-lg text-muted-foreground/70 transition-colors hover:bg-muted/45 hover:text-foreground",
              a.active && "text-foreground",
            );
            if (a.menuItems) {
              return (
                <DropdownMenu key={a.label}>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      title={a.label}
                      aria-label={a.ariaLabel ?? a.label}
                      onClick={(event) => event.stopPropagation()}
                      className={cls}
                    >
                      <Icon className="size-3.5" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="min-w-44">
                    {a.menuItems.map((item) => {
                      const ItemIcon = item.icon;
                      return (
                        <DropdownMenuItem
                          key={item.label}
                          onSelect={() => item.onClick?.()}
                        >
                          <ItemIcon className="mr-2 size-3.5" />
                          {item.label}
                        </DropdownMenuItem>
                      );
                    })}
                  </DropdownMenuContent>
                </DropdownMenu>
              );
            }
            if (a.href) {
              return (
                <Link
                  key={a.label}
                  to={a.href}
                  title={a.label}
                  aria-label={a.ariaLabel ?? a.label}
                  className={cls}
                >
                  <Icon className="size-3.5" />
                </Link>
              );
            }
            return (
              <button
                key={a.label}
                type="button"
                title={a.label}
                aria-label={a.ariaLabel ?? a.label}
                onClick={(e) => {
                  e.stopPropagation();
                  a.onClick?.();
                }}
                className={cls}
              >
                <Icon className="size-3.5" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ProjectsSection({
  groups,
  byProject,
  pathname,
  deletableProjects,
  deletingProject,
  groupingEnabled,
  runStatusByHref,
  onDeleteProject,
  onToggleGrouping,
  onOpenFiles,
  onNewProject,
}: {
  groups: string[];
  byProject: Record<string, ThreadSummary[]>;
  pathname: string;
  deletableProjects: Set<string>;
  deletingProject: string | null;
  groupingEnabled: boolean;
  runStatusByHref: Map<string, ThreadRunStatus>;
  onDeleteProject: (project: string) => void | Promise<void>;
  onToggleGrouping: () => void;
  onOpenFiles: (thread: ThreadSummary, project: string) => void;
  onNewProject: () => void;
}) {
  const { t } = useI18n();
  // Persist the open/closed state in localStorage so it stays
  // consistent across routes (chat ↔ code ↔ team) and across page
  // reloads. Without this, useState resets on remount and users
  // Implementation note.
  // expected the section to behave the same everywhere.
  const [open, setOpen] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try {
      const v = window.localStorage.getItem("octopus.sidebar.projects-open");
      return v === null ? true : v === "1";
    } catch (e) {
      swallow(e, "storage");
      return true;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "octopus.sidebar.projects-open",
        open ? "1" : "0",
      );
    } catch (e) {
      swallow(e, "storage");
    }
  }, [open]);
  return (
    <div className="mt-2 group-data-[collapsible=icon]:hidden">
      <SidebarGroup className="p-0 px-2 pb-0">
        <SectionHeader
          label={t.sidebar.sectionProjects}
          open={groupingEnabled && open}
          onToggleOpen={() => {
            if (!groupingEnabled) {
              onToggleGrouping();
              return;
            }
            setOpen((v) => !v);
          }}
          actions={buildProjectSectionActions({
            groupingEnabled,
            newProjectLabel: t.sidebar.actionNewProject,
            onNewProject,
          })}
        />
        {groupingEnabled && open && (
          <div className="mt-0.5">
            {groups.map((project) => (
              <ProjectGroup
                key={project}
                project={project}
                threads={byProject[project]!}
                pathname={pathname}
                deletable={deletableProjects.has(project)}
                deleting={deletingProject === project}
                runStatusByHref={runStatusByHref}
                onDeleteProject={onDeleteProject}
                onOpenFiles={onOpenFiles}
              />
            ))}
          </div>
        )}
      </SidebarGroup>
    </div>
  );
}

function ChatsSection({
  threads,
  pathname,
  label,
  emptyLabel,
  newActionLabel,
  agentId,
  workspacePath,
  runStatusByHref,
}: {
  threads: ThreadSummary[];
  pathname: string;
  label?: string;
  emptyLabel?: string;
  newActionLabel?: string;
  agentId?: string | null;
  workspacePath?: string | null;
  runStatusByHref?: Map<string, ThreadRunStatus>;
}) {
  const { t: tr } = useI18n();
  // Match the ProjectsSection pattern · persist open/close so the
  // chats list doesn't appear surprisingly empty after a route hop
  // collapsed it.
  const [open, setOpen] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try {
      const v = window.localStorage.getItem("octopus.sidebar.chats-open");
      return v === null ? true : v === "1";
    } catch (e) {
      swallow(e, "storage");
      return true;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "octopus.sidebar.chats-open",
        open ? "1" : "0",
      );
    } catch (e) {
      swallow(e);
    }
  }, [open]);
  useEffect(() => {
    if (activeWorkspaceThreadIdFromPathname(pathname)) setOpen(true);
  }, [pathname]);
  const deleteThread = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();
  const navigate = useNavigate();
  const { confirm, confirmDialog } = useConfirmDialog();
  // Emit a task-new event each click. Reusing a fixed /new link can be a
  // no-op when the pathname is already selected, so the workspace shell owns
  // fresh thread creation.
  const [threadToRename, setThreadToRename] = useState<ThreadSummary | null>(
    null,
  );
  const [renameValue, setRenameValue] = useState("");
  const handleRenameSubmit = useCallback(() => {
    if (threadToRename && renameValue.trim()) {
      renameThread({ threadId: threadToRename.id, title: renameValue.trim() });
      setThreadToRename(null);
      setRenameValue("");
    }
  }, [renameThread, threadToRename, renameValue]);
  const handleDeleteThread = useCallback(
    async (thread: ThreadSummary) => {
      const ok = await confirm({
        title: tr.sidebar.deleteThreadTooltip,
        description: tr.sidebar.confirmDeleteThread(thread.title),
      });
      if (!ok) return;
      deleteThread.mutate({ threadId: thread.id });
      if (pathname === thread.href) {
        void navigate(PRIMARY_WORKSPACE_ROUTE);
      }
    },
    [confirm, deleteThread, navigate, pathname, tr],
  );
  const startNewChat = useCallback(() => {
    eventBus.emit("task:new", {
      agentId: agentId || undefined,
      workspacePath: workspacePath || undefined,
    });
  }, [agentId, workspacePath]);
  const sectionLabel = label ?? tr.sidebar.sectionChats;
  const actionLabel = newActionLabel ?? tr.sidebar.actionNewTask;
  // Keep the global history scannable. Project folders already retain the
  // deeper archive, so the primary conversation section should surface only
  // the most useful recent set instead of becoming a second waterfall.
  const visibleLimit = 10;
  const displayedThreads = useMemo(() => {
    const activeId = activeWorkspaceThreadIdFromPathname(pathname);
    const current = activeId
      ? threads.find((thread) => thread.id === activeId)
      : undefined;
    const recent = threads.slice(0, visibleLimit);
    if (!current || recent.some((thread) => thread.id === current.id)) {
      return recent;
    }
    return [
      current,
      ...recent.filter((thread) => thread.id !== current.id),
    ].slice(0, visibleLimit);
  }, [pathname, threads]);
  return (
    <div className="mt-2 group-data-[collapsible=icon]:hidden">
      <SidebarGroup className="p-0 px-2 pb-1">
        <SectionHeader
          label={sectionLabel}
          open={open}
          onToggleOpen={() => setOpen((v) => !v)}
          actions={buildChatsSectionActions({
            sectionLabel,
            actionLabel,
            onNewChat: startNewChat,
          })}
        />
        {open &&
          (threads.length === 0 ? null : (
            <ul className="mt-0.5 space-y-px">
              {displayedThreads.map((t) => {
                const active =
                  activeWorkspaceThreadIdFromPathname(pathname) === t.id;
                const runStatus = runStatusByHref?.get(t.href);
                return (
                  <li key={t.id} className="group/thread relative">
                    <Link
                      to={t.href}
                      state={{
                        threadOwnerAgentId:
                          t.agents.length === 1 ? t.agents[0] : undefined,
                        workspacePath: t.workspacePath,
                      }}
                      onMouseDown={() => syncThreadAgentSelection(t.agents)}
                      aria-current={active ? "page" : undefined}
                      title={t.title}
                      className={cn(
                        "flex min-h-8 w-full min-w-0 items-center gap-2 rounded-lg py-1 pl-2 pr-2 text-[13px] text-foreground/78 transition-[padding,background-color,color] duration-fast group-hover/thread:pr-8 group-focus-within/thread:pr-8",
                        "hover:bg-muted/40 hover:text-foreground",
                        "outline-none focus-visible:ring-1 focus-visible:ring-ring/45 focus-visible:ring-inset",
                        active &&
                          "text-foreground bg-[color:color-mix(in_oklch,var(--sidebar-accent)_42%,transparent)]",
                      )}
                    >
                      <ThreadRunStatusLight
                        active={active}
                        idle="queue"
                        status={runStatus}
                        className="ml-0.5"
                      />
                      <span className="min-w-0 flex-1 truncate leading-tight">
                        {t.title}
                      </span>
                      <span className="w-10 shrink-0 overflow-hidden whitespace-nowrap text-right text-mini text-muted-foreground transition-[width,opacity,color] group-hover/thread:w-0 group-hover/thread:text-muted-foreground/90 group-hover/thread:opacity-0 group-focus-within/thread:w-0 group-focus-within/thread:opacity-0">
                        {formatCompactRelativeTimestamp(t.updatedAt)}
                      </span>
                    </Link>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          title={tr.common.more}
                          aria-label={tr.common.more}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                          }}
                          className="absolute right-0.5 top-1/2 -translate-y-1/2 flex size-8 items-center justify-center rounded-lg text-muted-foreground/60 opacity-0 transition-opacity group-hover/thread:opacity-100 hover:bg-muted/40 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 data-[state=open]:opacity-100"
                        >
                          <MoreHorizontalIcon className="size-3.5" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" side="right">
                        <DropdownMenuItem
                          onSelect={() => {
                            setThreadToRename(t);
                            setRenameValue(t.title);
                          }}
                        >
                          <PencilIcon className="text-muted-foreground" />
                          <span>{tr.common.rename}</span>
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          disabled={deleteThread.isPending}
                          onSelect={() => void handleDeleteThread(t)}
                        >
                          <Trash2Icon />
                          <span>{tr.sidebar.deleteThreadTooltip}</span>
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </li>
                );
              })}
            </ul>
          ))}
      </SidebarGroup>
      <Dialog
        open={threadToRename !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setThreadToRename(null);
            setRenameValue("");
          }
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="w-[min(360px,calc(100vw-2rem))] gap-3 rounded-lg p-4 sm:max-w-[360px]"
        >
          <DialogHeader className="gap-1 text-left">
            <DialogTitle className="text-base">{tr.common.rename}</DialogTitle>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isIMEComposing(e)) {
                e.preventDefault();
                handleRenameSubmit();
              }
            }}
            autoFocus
            className="h-8 text-sm"
          />
          <DialogFooter className="mt-1 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setThreadToRename(null);
                setRenameValue("");
              }}
            >
              {tr.common.cancel}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!renameValue.trim()}
              onClick={handleRenameSubmit}
            >
              {tr.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </div>
  );
}
export function CollapseToggle({ compact = false }: { compact?: boolean }) {
  const { open, toggleSidebar, state } = useSidebar();
  const { t } = useI18n();
  const Icon = open ? PanelLeftCloseIcon : PanelLeftOpenIcon;
  const isCollapsed = state === "collapsed";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={toggleSidebar}
          title={open ? t.sidebar.collapseSidebar : t.sidebar.expandSidebar}
          aria-label={
            open ? t.sidebar.collapseSidebar : t.sidebar.expandSidebar
          }
          aria-expanded={open}
          className={cn(
            "flex shrink-0 items-center justify-center justify-self-center border border-transparent bg-transparent text-muted-foreground shadow-none transition-[background-color,border-color,color] hover:border-border-default hover:bg-muted/55 hover:text-foreground",
            compact
              ? "size-8 rounded-[var(--appearance-radius-control)]"
              : "size-10 rounded-[var(--appearance-radius-lg)]",
          )}
        >
          <Icon className={compact ? "size-3.5" : "size-4"} />
        </button>
      </TooltipTrigger>
      <TooltipContent side={isCollapsed ? "right" : "bottom"} align="center">
        {open ? t.sidebar.collapseSidebar : t.sidebar.expandSidebar}
      </TooltipContent>
    </Tooltip>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-1 rounded-lg border border-dashed border-border-default px-2.5 py-1.5 text-xs leading-tight text-muted-foreground/75">
      {children}
    </div>
  );
}
