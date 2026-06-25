import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  AppWindowIcon,
  ArchiveIcon,
  BatteryFullIcon,
  BellIcon,
  BotIcon,
  CpuIcon,
  ExternalLinkIcon,
  FileTextIcon,
  FolderIcon,
  FolderInputIcon,
  GlobeIcon,
  HardDriveIcon,
  ImageIcon,
  Loader2Icon,
  MonitorIcon,
  RotateCcwIcon,
  SearchIcon,
  SettingsIcon,
  SlidersHorizontalIcon,
  SparklesIcon,
  StoreIcon,
  TerminalSquareIcon,
  Trash2Icon,
  UserCircleIcon,
  WifiIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useDebounce } from "@/hooks";
import { useI18n } from "@/core/i18n/hooks";
import type { NativeDesktopItem } from "@/types/electron";

type DesktopApp = {
  name: string;
  subtitle: string;
  route: string;
  icon: typeof SparklesIcon;
  color: string;
};

type DesktopCategory = {
  key: "all" | "folder" | "app" | "image" | "document" | "package" | "other";
  label: string;
};

const CATEGORY_ORDER: DesktopCategory["key"][] = [
  "all",
  "folder",
  "app",
  "image",
  "document",
  "package",
  "other",
];

const IMAGE_EXTENSIONS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "bmp",
  "svg",
  "ico",
]);
const DOCUMENT_EXTENSIONS = new Set([
  "txt",
  "md",
  "pdf",
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
  "csv",
]);
const PACKAGE_EXTENSIONS = new Set([
  "zip",
  "rar",
  "7z",
  "tar",
  "gz",
  "exe",
  "msi",
  "dmg",
  "pkg",
]);
const ARCHIVE_FOLDER_MAP: Record<string, string> = {
  image: "图片",
  document: "文档",
  package: "安装包",
  other: "其他",
};
const DESKTOP_ORGANIZER_ENABLED_KEY = "octopus:desktop-organizer-enabled";

function getDesktopItemCategory(
  item: NativeDesktopItem,
): DesktopCategory["key"] {
  if (item.kind === "folder") return "folder";
  if (item.kind === "app") return "app";
  if (IMAGE_EXTENSIONS.has(item.extension)) return "image";
  if (DOCUMENT_EXTENSIONS.has(item.extension)) return "document";
  if (PACKAGE_EXTENSIONS.has(item.extension)) return "package";
  return "other";
}

export default function DesktopShellPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [nativeDesktopItems, setNativeDesktopItems] = useState<
    NativeDesktopItem[]
  >([]);
  const [desktopDrawerOpen, setDesktopDrawerOpen] = useState(false);
  const [desktopCategory, setDesktopCategory] =
    useState<DesktopCategory["key"]>("all");
  const [desktopSearch, setDesktopSearch] = useState("");
  const [organizerEnabled, setOrganizerEnabled] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem(DESKTOP_ORGANIZER_ENABLED_KEY) === "true"
      : false,
  );
  const [archiving, setArchiving] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [archiveResult, setArchiveResult] = useState<{
    moved: number;
    skipped: number;
  } | null>(null);
  const [showWidget, setShowWidget] = useState(false);
  const [systemInfo, setSystemInfo] = useState<{
    cpu: { model: string; cores: number; usage: number };
    memory: { total: number; used: number; percent: number };
    uptime: number;
  } | null>(null);
  const [dragOverCategory, setDragOverCategory] = useState<string | null>(null);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    item: NativeDesktopItem;
  } | null>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const mousePassthroughRef = useRef(false);
  const today = useMemo(() => new Date(), []);
  const weekday = t.desktop.weekdays[today.getDay()] ?? "";

  const debouncedSearch = useDebounce(desktopSearch, 200);

  const desktopCategories = useMemo<DesktopCategory[]>(
    () =>
      CATEGORY_ORDER.map((key) => ({
        key,
        label: t.desktop.categories[key],
      })),
    [t.desktop.categories],
  );

  const desktopApps = useMemo<DesktopApp[]>(
    () => [
      {
        name: t.desktop.apps.workspace.name,
        subtitle: t.desktop.apps.workspace.subtitle,
        route: "/workspace/realtime/new",
        icon: MonitorIcon,
        color: "from-sky-500 to-blue-600",
      },
      {
        name: t.desktop.apps.aiBrowser.name,
        subtitle: t.desktop.apps.aiBrowser.subtitle,
        route: "/browser",
        icon: GlobeIcon,
        color: "from-indigo-500 to-cyan-500",
      },
      {
        name: t.desktop.apps.localFiles.name,
        subtitle: t.desktop.apps.localFiles.subtitle,
        route: "/workspace/knowledge",
        icon: FolderIcon,
        color: "from-amber-400 to-orange-500",
      },
      {
        name: t.desktop.apps.localApps.name,
        subtitle: t.desktop.apps.localApps.subtitle,
        route: "/workspace/store",
        icon: AppWindowIcon,
        color: "from-violet-500 to-fuchsia-500",
      },
      {
        name: t.desktop.apps.terminalLogs.name,
        subtitle: t.desktop.apps.terminalLogs.subtitle,
        route: "/workspace/observability",
        icon: TerminalSquareIcon,
        color: "from-muted-foreground to-muted-foreground/70",
      },
      {
        name: t.desktop.apps.settings.name,
        subtitle: t.desktop.apps.settings.subtitle,
        route: "/workspace",
        icon: SettingsIcon,
        color: "from-stone-500 to-neutral-700",
      },
    ],
    [t.desktop.apps],
  );

  const dockApps = useMemo(() => desktopApps.slice(0, 3), [desktopApps]);

  const localAppPlaceholders = useMemo<DesktopApp[]>(
    () => [
      {
        name: t.desktop.placeholders.browser,
        subtitle: t.desktop.placeholders.subtitle,
        route: "/workspace/store",
        icon: GlobeIcon,
        color: "from-white to-muted text-foreground",
      },
      {
        name: t.desktop.placeholders.communication,
        subtitle: t.desktop.placeholders.subtitle,
        route: "/workspace/store",
        icon: AppWindowIcon,
        color: "from-white to-muted text-foreground",
      },
      {
        name: t.desktop.placeholders.notes,
        subtitle: t.desktop.placeholders.subtitle,
        route: "/workspace/store",
        icon: FileTextIcon,
        color: "from-white to-muted text-foreground",
      },
    ],
    [t.desktop.placeholders],
  );

  const openApp = (app: DesktopApp) => navigate(app.route);

  useEffect(() => {
    if (!organizerEnabled) return;
    const off = window.octopus?.on?.("desktop:organize-now", () => {
      setDesktopCategory("all");
      setDesktopSearch("");
      setDesktopDrawerOpen(true);
    });
    return () => off?.();
  }, [organizerEnabled]);

  useEffect(() => {
    if (!organizerEnabled) return;
    document.documentElement.classList.add("desktop-overlay");
    return () => {
      document.documentElement.classList.remove("desktop-overlay");
      void window.octopus?.window?.setMousePassthrough?.(false);
    };
  }, [organizerEnabled]);

  useEffect(() => {
    if (!organizerEnabled) return;
    if (!window.octopus?.window?.setMousePassthrough) return;

    const setPassthrough = (enabled: boolean) => {
      if (mousePassthroughRef.current === enabled) return;
      mousePassthroughRef.current = enabled;
      void window.octopus?.window?.setMousePassthrough?.(enabled).catch(() => {
        mousePassthroughRef.current = !enabled;
      });
    };

    if (desktopDrawerOpen) {
      setPassthrough(false);
      return;
    }

    const onPointerMove = (event: PointerEvent) => {
      const target = event.target;
      const overInteractive =
        target instanceof Element &&
        !!target.closest("[data-desktop-interactive]");
      setPassthrough(!overInteractive);
    };

    const onPointerLeave = () => setPassthrough(true);

    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("pointerleave", onPointerLeave, true);
    setPassthrough(true);

    return () => {
      document.removeEventListener("pointermove", onPointerMove, true);
      document.removeEventListener("pointerleave", onPointerLeave, true);
      setPassthrough(false);
    };
  }, [desktopDrawerOpen, organizerEnabled]);

  useEffect(() => {
    if (!organizerEnabled) return;
    let alive = true;
    if (!window.octopus?.desktop) return;
    setLoadingItems(true);
    setItemsError(null);
    window.octopus.desktop
      .listItems()
      .then((result) => {
        if (!alive) return;
        setLoadingItems(false);
        if (!result.ok) {
          setItemsError(result.error || t.desktop.errors.listItems);
          setNativeDesktopItems([]);
          return;
        }
        setNativeDesktopItems(result.items);
      })
      .catch((e) => {
        if (!alive) return;
        setLoadingItems(false);
        setItemsError(
          e instanceof Error ? e.message : t.desktop.errors.listItems,
        );
        setNativeDesktopItems([]);
      });
    return () => {
      alive = false;
    };
  }, [organizerEnabled, t.desktop.errors.listItems]);

  useEffect(() => {
    if (!showWidget) return;
    let alive = true;
    const poll = async () => {
      if (!window.octopus?.desktop?.getSystemInfo) return;
      try {
        const result = await window.octopus.desktop.getSystemInfo();
        if (alive && result.ok) {
          setSystemInfo({
            cpu: result.cpu!,
            memory: result.memory!,
            uptime: result.uptime!,
          });
        }
      } catch {}
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [showWidget]);

  useEffect(() => {
    if (!desktopDrawerOpen) return;
    const timer = setTimeout(() => {
      closeButtonRef.current?.focus();
    }, 100);
    return () => clearTimeout(timer);
  }, [desktopDrawerOpen]);

  useEffect(() => {
    if (!desktopDrawerOpen) return;
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        setDesktopDrawerOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [desktopDrawerOpen]);

  useEffect(() => {
    const onClick = () => setContextMenu(null);
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  const filteredDesktopItems = useMemo(() => {
    const search = debouncedSearch.trim().toLowerCase();
    return nativeDesktopItems.filter((item) => {
      const matchesCategory =
        desktopCategory === "all" ||
        getDesktopItemCategory(item) === desktopCategory;
      if (!matchesCategory) return false;
      if (!search) return true;
      return `${item.name} ${item.subtitle} ${item.extension}`
        .toLowerCase()
        .includes(search);
    });
  }, [desktopCategory, debouncedSearch, nativeDesktopItems]);

  const groupedDesktopItems = useMemo(
    () =>
      desktopCategories
        .filter((category) => category.key !== "all")
        .map((category) => ({
          key: category.key,
          title: category.label,
          items: filteredDesktopItems.filter(
            (item) => getDesktopItemCategory(item) === category.key,
          ),
        }))
        .filter((group) => group.items.length > 0),
    [filteredDesktopItems, desktopCategories],
  );

  const openDesktopFile = (item: NativeDesktopItem) => {
    void window.octopus?.desktop?.openItem(item.path);
  };

  const refreshDesktopItems = () => {
    if (!window.octopus?.desktop) return;
    setLoadingItems(true);
    setItemsError(null);
    window.octopus.desktop
      .listItems()
      .then((result) => {
        setLoadingItems(false);
        if (result.ok) {
          setNativeDesktopItems(result.items);
        } else {
          setItemsError(result.error || t.desktop.errors.refresh);
        }
      })
      .catch((e) => {
        setLoadingItems(false);
        setItemsError(
          e instanceof Error ? e.message : t.desktop.errors.refresh,
        );
      });
  };

  const handleAutoArchive = async () => {
    if (!window.octopus?.desktop?.moveItemsBatch) return;
    setArchiving(true);
    setArchiveResult(null);
    try {
      const fileItems = nativeDesktopItems.filter(
        (item) =>
          item.kind === "file" && getDesktopItemCategory(item) !== "app",
      );
      if (fileItems.length === 0) {
        toast.info(t.desktop.toasts.noFilesToArchive);
        setArchiveResult({ moved: 0, skipped: 0 });
        return;
      }
      const batch = fileItems.map((item) => ({
        srcPath: item.path,
        category: getDesktopItemCategory(item),
      }));
      const result = await window.octopus.desktop.moveItemsBatch(batch);
      if (result.ok) {
        setArchiveResult({ moved: result.moved, skipped: result.skipped });
        refreshDesktopItems();
        toast.success(t.desktop.toasts.archived(result.moved));
      } else {
        toast.error(result.error || t.desktop.errors.archive);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.desktop.errors.archive);
      setArchiveResult({ moved: 0, skipped: 0 });
    } finally {
      setArchiving(false);
    }
  };

  const handleUndo = async () => {
    if (!window.octopus?.desktop?.undoMoves) return;
    setUndoing(true);
    try {
      const result = await window.octopus.desktop.undoMoves();
      if (result.ok && result.undone > 0) {
        refreshDesktopItems();
        setArchiveResult(null);
        toast.success(t.desktop.toasts.undone(result.undone));
      } else if (result.ok && result.undone === 0) {
        toast.info(t.desktop.toasts.noUndoOperations);
      } else {
        toast.error(result.error || t.desktop.errors.undo);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.desktop.errors.undo);
    } finally {
      setUndoing(false);
    }
  };

  const handleContextMenuAction = async (
    action: "open" | "archive" | "delete",
    item: NativeDesktopItem,
  ) => {
    setContextMenu(null);
    if (action === "open") {
      openDesktopFile(item);
    } else if (action === "archive") {
      if (!window.octopus?.desktop?.moveItem) return;
      const category = getDesktopItemCategory(item);
      if (category === "app" || category === "folder") {
        toast.info(t.desktop.errors.archiveOnlyFiles);
        return;
      }
      try {
        const listResult = await window.octopus.desktop.listItems();
        const desktopPath = listResult.ok ? listResult.desktopPath || "" : "";
        const folderName = ARCHIVE_FOLDER_MAP[category];
        if (!folderName || !desktopPath) return;
        const destDir = desktopPath + "\\" + folderName;
        const result = await window.octopus.desktop.moveItem(
          item.path,
          destDir,
        );
        if (result.ok) {
          refreshDesktopItems();
          toast.success(t.desktop.toasts.fileArchived(item.name, folderName));
        } else {
          toast.error(result.error || t.desktop.errors.archive);
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t.desktop.errors.archive);
      }
    } else if (action === "delete") {
      toast.info(t.desktop.errors.deleteNotImplemented);
    }
  };

  const submit = () => {
    const value = query.trim().toLowerCase();
    if (!value) return;
    const app = desktopApps.find((item) => {
      const haystack = `${item.name} ${item.subtitle}`.toLowerCase();
      return (
        haystack.includes(value) || value.includes(item.name.toLowerCase())
      );
    });
    if (app) {
      openApp(app);
      return;
    }
    navigate(`/browser?q=${encodeURIComponent(query.trim())}`);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") submit();
  };

  const enableOrganizer = () => {
    localStorage.setItem(DESKTOP_ORGANIZER_ENABLED_KEY, "true");
    setOrganizerEnabled(true);
  };

  if (!organizerEnabled) {
    return (
      <main className="flex h-screen items-center justify-center bg-background p-6 text-foreground">
        <section className="w-full max-w-xl rounded-3xl border border-border bg-card p-6 shadow-sm">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <FolderIcon className="size-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold">
                {t.desktop.disabledTitle}
              </h1>
              <p className="text-sm text-muted-foreground">
                {t.desktop.disabledDescription}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={enableOrganizer}
              className="inline-flex h-10 items-center justify-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm transition hover:bg-primary/90"
            >
              {t.desktop.enableButton}
            </button>
            <button
              type="button"
              onClick={() => navigate("/workspace/desktop-organizer")}
              className="inline-flex h-10 items-center justify-center rounded-lg border border-border bg-background px-4 text-sm font-medium transition hover:bg-muted"
            >
              {t.desktop.pluginSettingsButton}
            </button>
            <button
              type="button"
              onClick={() => navigate("/workspace/realtime/new")}
              className="inline-flex h-10 items-center justify-center rounded-lg border border-border bg-background px-4 text-sm font-medium transition hover:bg-muted"
            >
              {t.desktop.backToWorkspaceButton}
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="relative h-screen overflow-hidden bg-transparent text-white">
      <section className="relative z-10 flex h-full min-h-0 flex-col">
        <header className="hidden">
          <div className="flex min-w-0 items-center gap-2.5">
            <button
              type="button"
              onClick={() => navigate("/workspace/realtime/new")}
              className="flex shrink-0 items-center gap-2 rounded-lg px-1 py-0.5 transition hover:bg-white/32"
              title={t.desktop.header.workspaceTooltip}
            >
              <span className="grid size-6 place-items-center rounded-md bg-white/50 text-foreground shadow-sm ring-1 ring-white/35">
                <BotIcon className="size-4" />
              </span>
              <span className="font-semibold">{t.desktop.header.brand}</span>
            </button>
            <button
              type="button"
              onClick={() => navigate("/workspace")}
              className="hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 text-foreground transition hover:bg-white/34 md:flex"
              title={t.desktop.header.accountModels}
            >
              <UserCircleIcon className="size-3.5" />
              <span>{t.desktop.header.accountModels}</span>
            </button>
            <button
              type="button"
              onClick={() => setDesktopDrawerOpen(true)}
              className="hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 text-foreground transition hover:bg-white/34 sm:flex"
              title={t.desktop.header.desktopAssistant}
            >
              <FolderIcon className="size-3.5" />
              <span>
                {t.desktop.header.desktopCount(nativeDesktopItems.length)}
              </span>
            </button>
            <button
              type="button"
              onClick={() => navigate("/workspace/store")}
              className="hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 text-foreground transition hover:bg-white/34 md:flex"
              title={t.desktop.header.market}
            >
              <StoreIcon className="size-3.5" />
              <span>{t.desktop.header.market}</span>
            </button>
          </div>

          <div className="flex shrink-0 items-center gap-2 text-foreground">
            <button
              type="button"
              onClick={() => navigate("/workspace/observability")}
              className="hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 transition hover:bg-white/34 md:flex"
              title={t.desktop.header.aiReady}
            >
              <SparklesIcon className="size-3.5 text-blue-600" />
              <span>{t.desktop.header.aiReady}</span>
            </button>
            <span className="hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 sm:flex">
              <WifiIcon className="size-3.5" />
              <span>{t.desktop.header.wifi}</span>
            </span>
            <span className="hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 sm:flex">
              <BatteryFullIcon className="size-3.5" />
              <span>100%</span>
            </span>
            <button
              type="button"
              onClick={() => navigate("/workspace")}
              className="grid size-7 place-items-center rounded-md transition hover:bg-white/34"
              title={t.desktop.header.notifications}
            >
              <BellIcon className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => navigate("/workspace")}
              className="grid size-7 place-items-center rounded-md transition hover:bg-white/34"
              title={t.desktop.header.quickSettings}
            >
              <SlidersHorizontalIcon className="size-4" />
            </button>
            <span className="min-w-[108px] text-right">
              {t.desktop.header.date(
                today.getMonth() + 1,
                today.getDate(),
                weekday,
              )}
            </span>
          </div>
        </header>

        <div className="relative min-h-0 flex-1 px-8 pb-28 pt-7">
          <div className="pointer-events-none absolute right-8 top-8 rounded-[22px] bg-black/20 px-5 py-4 text-right shadow-2xl shadow-black/14 backdrop-blur-2xl">
            <div className="text-xs font-semibold text-white/78">
              {t.desktop.widget.today}
            </div>
            <div className="mt-1 text-4xl font-semibold leading-none">
              {today.getDate()}
            </div>
            <div className="mt-1 text-xs text-white/72">
              {t.desktop.widget.date(
                today.getFullYear(),
                today.getMonth() + 1,
                today.getDate(),
                weekday,
              )}
            </div>
          </div>

          <div className="mx-auto flex h-full max-w-[760px] flex-col items-center justify-center pb-12">
            <div
              data-desktop-interactive
              className="flex h-12 w-full max-w-[620px] items-center gap-3 rounded-2xl border border-white/36 bg-white/68 px-4 text-foreground shadow-2xl shadow-black/12 backdrop-blur-2xl"
            >
              <SearchIcon className="size-5 shrink-0 text-blue-600" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder={t.desktop.searchPlaceholder}
                className="min-w-0 flex-1 bg-transparent text-sm font-medium outline-none placeholder:text-muted-foreground/70"
              />
              <button
                type="button"
                onClick={submit}
                className="rounded-full bg-foreground px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-muted-foreground"
              >
                {t.desktop.open}
              </button>
            </div>
          </div>
        </div>

        <div
          className={cn(
            "absolute inset-0 z-30 transition-all duration-300 ease-out",
            desktopDrawerOpen
              ? "pointer-events-auto opacity-100"
              : "pointer-events-none opacity-0",
          )}
        >
          <div
            data-desktop-interactive
            className={cn(
              "absolute inset-0 bg-black/18 px-8 pb-28 pt-14 backdrop-blur-sm transition-opacity duration-300",
              desktopDrawerOpen ? "opacity-100" : "opacity-0",
            )}
            onClick={() => setDesktopDrawerOpen(false)}
          />
          <section
            ref={drawerRef}
            className={cn(
              "absolute inset-x-8 bottom-28 top-14 mx-auto max-w-[760px] rounded-[28px] border border-white/34 bg-white/72 p-5 text-foreground shadow-2xl shadow-black/24 backdrop-blur-2xl transition-all duration-300 ease-out",
              desktopDrawerOpen
                ? "translate-y-0 opacity-100"
                : "translate-y-4 opacity-0",
            )}
          >
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold">
                  {t.desktop.drawer.title}
                </h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {loadingItems
                    ? t.desktop.drawer.loading
                    : itemsError
                      ? t.desktop.drawer.error(itemsError)
                      : window.octopus?.desktop
                        ? t.desktop.drawer.count(nativeDesktopItems.length)
                        : t.desktop.drawer.electronMode}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                {archiveResult && !itemsError && (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                    {t.desktop.drawer.archiveBadge(archiveResult.moved)}
                  </span>
                )}
                {window.octopus?.desktop?.moveItemsBatch && !itemsError && (
                  <button
                    type="button"
                    onClick={handleAutoArchive}
                    disabled={archiving || loadingItems}
                    className="inline-flex h-7 items-center gap-1 rounded-lg bg-blue-600 px-2.5 text-[11px] font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
                    title={t.desktop.drawer.autoArchiveTooltip}
                  >
                    <ArchiveIcon className="size-3" />
                    {archiving
                      ? t.desktop.drawer.archiving
                      : t.desktop.drawer.archive}
                  </button>
                )}
                {window.octopus?.desktop?.undoMoves && !itemsError && (
                  <button
                    type="button"
                    onClick={handleUndo}
                    disabled={undoing || loadingItems}
                    className="inline-flex h-7 items-center gap-1 rounded-lg border border-border bg-white px-2.5 text-[11px] font-medium text-muted-foreground transition hover:bg-muted/50 disabled:opacity-50"
                    title={t.desktop.drawer.undoTooltip}
                  >
                    <RotateCcwIcon className="size-3" />
                    {undoing ? t.desktop.drawer.undoing : t.desktop.drawer.undo}
                  </button>
                )}
                <button
                  ref={closeButtonRef}
                  type="button"
                  onClick={() => setDesktopDrawerOpen(false)}
                  className="grid size-8 place-items-center rounded-full bg-foreground/10 text-lg leading-none text-muted-foreground transition hover:bg-foreground/15"
                  aria-label={t.desktop.drawer.closeAria}
                >
                  ×
                </button>
              </div>
            </div>

            {itemsError && (
              <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">
                <div className="flex items-center gap-2">
                  <span className="font-medium">
                    {t.desktop.drawer.readFailed}
                  </span>
                  <button
                    type="button"
                    onClick={refreshDesktopItems}
                    className="ml-auto rounded-md bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-700 transition hover:bg-red-200"
                  >
                    {t.desktop.drawer.retry}
                  </button>
                </div>
                <p className="mt-1 opacity-80">{itemsError}</p>
              </div>
            )}

            {!itemsError && (
              <>
                <div className="mt-4 flex items-center gap-2 rounded-2xl border border-white/45 bg-white/56 px-3 py-2">
                  <SearchIcon className="size-4 shrink-0 text-muted-foreground/70" />
                  <input
                    value={desktopSearch}
                    onChange={(event) => setDesktopSearch(event.target.value)}
                    placeholder={t.desktop.drawer.searchPlaceholder}
                    className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
                  />
                  {desktopSearch && (
                    <button
                      type="button"
                      onClick={() => setDesktopSearch("")}
                      className="grid size-4 place-items-center rounded-full text-muted-foreground/70 transition hover:text-muted-foreground"
                    >
                      <XIcon className="size-3" />
                    </button>
                  )}
                </div>

                <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                  {desktopCategories.map((category) => {
                    const count =
                      category.key === "all"
                        ? nativeDesktopItems.length
                        : nativeDesktopItems.filter(
                            (item) =>
                              getDesktopItemCategory(item) === category.key,
                          ).length;
                    return (
                      <button
                        key={category.key}
                        type="button"
                        onClick={() => setDesktopCategory(category.key)}
                        onDragOver={(e) => {
                          if (category.key === "all") return;
                          e.preventDefault();
                          e.dataTransfer.dropEffect = "move";
                          setDragOverCategory(category.key);
                        }}
                        onDragLeave={() => setDragOverCategory(null)}
                        onDrop={async (e) => {
                          e.preventDefault();
                          setDragOverCategory(null);
                          const srcPath = e.dataTransfer.getData("text/plain");
                          if (!srcPath || !window.octopus?.desktop?.moveItem)
                            return;
                          const desktopPath = await window.octopus.desktop
                            .listItems()
                            .then((r) => r.desktopPath || "");
                          const folderName = ARCHIVE_FOLDER_MAP[category.key];
                          if (!folderName) return;
                          const destDir = desktopPath + "\\" + folderName;
                          const result = await window.octopus.desktop.moveItem(
                            srcPath,
                            destDir,
                          );
                          if (result.ok) {
                            refreshDesktopItems();
                            toast.success(t.desktop.toasts.fileMoved);
                          } else {
                            toast.error(result.error || t.desktop.errors.move);
                          }
                        }}
                        className={cn(
                          "shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition",
                          desktopCategory === category.key
                            ? "bg-foreground text-white"
                            : dragOverCategory === category.key
                              ? "bg-blue-500 text-white ring-2 ring-blue-300"
                              : "bg-white/56 text-muted-foreground hover:bg-white/80",
                        )}
                      >
                        {category.label}
                        <span className="ml-1 opacity-65">{count}</span>
                      </button>
                    );
                  })}
                </div>

                <div className="mt-4 max-h-[calc(100%-132px)] overflow-auto pr-1">
                  {loadingItems ? (
                    <div className="grid h-56 place-items-center">
                      <div className="text-center">
                        <Loader2Icon className="mx-auto size-8 animate-spin text-muted-foreground/70" />
                        <p className="mt-3 text-sm font-medium text-muted-foreground">
                          {t.desktop.loadingItems}
                        </p>
                      </div>
                    </div>
                  ) : filteredDesktopItems.length > 0 ? (
                    <div className="space-y-5">
                      {(desktopCategory === "all"
                        ? groupedDesktopItems
                        : [
                            {
                              key: desktopCategory,
                              title:
                                desktopCategories.find(
                                  (item) => item.key === desktopCategory,
                                )?.label || t.desktop.fallbackGroupTitle,
                              items: filteredDesktopItems,
                            },
                          ]
                      ).map((group) => (
                        <div key={group.key}>
                          <div className="mb-2 text-xs font-semibold text-muted-foreground">
                            {group.title}
                          </div>
                          <div className="grid grid-cols-5 gap-3">
                            {group.items.map((item) => {
                              const category = getDesktopItemCategory(item);
                              const Icon =
                                category === "folder"
                                  ? FolderIcon
                                  : category === "app"
                                    ? AppWindowIcon
                                    : category === "image"
                                      ? ImageIcon
                                      : FileTextIcon;
                              return (
                                <button
                                  key={item.path}
                                  type="button"
                                  draggable={item.kind === "file"}
                                  onDragStart={(e) => {
                                    e.dataTransfer.setData(
                                      "text/plain",
                                      item.path,
                                    );
                                    e.dataTransfer.effectAllowed = "move";
                                  }}
                                  onClick={() => openDesktopFile(item)}
                                  onContextMenu={(e) => {
                                    e.preventDefault();
                                    setContextMenu({
                                      x: e.clientX,
                                      y: e.clientY,
                                      item,
                                    });
                                  }}
                                  title={item.path}
                                  className="group flex min-h-[92px] flex-col items-center justify-center gap-1.5 rounded-2xl p-2 text-center transition hover:bg-white/62 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
                                >
                                  <span
                                    className={cn(
                                      "grid size-12 place-items-center rounded-[14px] text-white shadow-lg shadow-black/12 ring-1 ring-white/35 transition-transform duration-150 group-hover:scale-105",
                                      category === "folder"
                                        ? "bg-gradient-to-br from-amber-400 to-orange-500"
                                        : category === "app"
                                          ? "bg-gradient-to-br from-violet-500 to-fuchsia-500"
                                          : category === "image"
                                            ? "bg-gradient-to-br from-cyan-400 to-blue-500"
                                            : category === "document"
                                              ? "bg-gradient-to-br from-blue-500 to-indigo-500"
                                              : category === "package"
                                                ? "bg-gradient-to-br from-rose-500 to-orange-500"
                                                : "bg-gradient-to-br from-muted-foreground to-muted-foreground/70",
                                    )}
                                  >
                                    <Icon className="size-6" />
                                  </span>
                                  <span className="line-clamp-2 max-w-24 text-[11px] font-medium leading-tight text-foreground">
                                    {item.name}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="grid h-56 place-items-center rounded-3xl border border-dashed border-border/80 bg-white/32 text-center">
                      <div>
                        <SearchIcon className="mx-auto size-8 text-muted-foreground/70" />
                        <p className="mt-3 text-sm font-medium text-muted-foreground">
                          {desktopSearch.trim()
                            ? t.desktop.empty.noSearchResults
                            : nativeDesktopItems.length === 0
                              ? t.desktop.empty.noDesktopFiles
                              : t.desktop.empty.noFilesInCategory}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground/70">
                          {desktopSearch.trim()
                            ? t.desktop.empty.tryAnotherKeyword
                            : t.desktop.empty.dropFilesHere}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </section>
        </div>

        {contextMenu && (
          <div
            data-desktop-interactive
            className="fixed z-50 w-40 rounded-lg border border-border bg-card py-1 shadow-xl"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <button
              type="button"
              onClick={() => handleContextMenuAction("open", contextMenu.item)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-foreground transition hover:bg-muted"
            >
              <ExternalLinkIcon className="size-3.5" />
              {t.desktop.contextMenu.open}
            </button>
            {contextMenu.item.kind === "file" && (
              <button
                type="button"
                onClick={() =>
                  handleContextMenuAction("archive", contextMenu.item)
                }
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-foreground transition hover:bg-muted"
              >
                <FolderInputIcon className="size-3.5" />
                {t.desktop.contextMenu.archiveToCategory}
              </button>
            )}
            <div className="my-1 h-px bg-muted" />
            <button
              type="button"
              onClick={() =>
                handleContextMenuAction("delete", contextMenu.item)
              }
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 transition hover:bg-red-50"
            >
              <Trash2Icon className="size-3.5" />
              {t.desktop.contextMenu.delete}
            </button>
          </div>
        )}

        <nav
          data-desktop-interactive
          className="absolute bottom-5 left-1/2 z-20 flex -translate-x-1/2 items-end gap-2.5 rounded-[24px] border border-white/38 bg-white/48 px-3.5 py-2.5 shadow-2xl shadow-black/22 backdrop-blur-2xl"
        >
          {dockApps.map((app) => {
            const Icon = app.icon;
            return (
              <button
                key={app.name}
                type="button"
                onClick={() => openApp(app)}
                title={app.name}
                className={cn(
                  "grid size-[54px] place-items-center rounded-[15px] bg-gradient-to-br text-white shadow-lg shadow-black/18 ring-1 ring-white/25 transition hover:-translate-y-2 hover:scale-110",
                  app.color,
                )}
              >
                <Icon className="size-6" />
              </button>
            );
          })}
          <span className="mx-1 h-10 w-px bg-foreground/15" />
          {localAppPlaceholders.map((app) => {
            const Icon = app.icon;
            return (
              <button
                key={app.name}
                type="button"
                onClick={() => openApp(app)}
                title={`${app.name} · ${app.subtitle}`}
                className={cn(
                  "grid size-[54px] place-items-center rounded-[15px] bg-gradient-to-br shadow-lg shadow-black/12 ring-1 ring-white/25 transition hover:-translate-y-2 hover:scale-110",
                  app.color,
                )}
              >
                <Icon className="size-6" />
              </button>
            );
          })}
          <span className="mx-1 h-10 w-px bg-foreground/15" />
          <button
            type="button"
            onClick={() => setDesktopDrawerOpen(true)}
            title={t.desktop.dock.desktopFiles}
            className="grid size-[54px] place-items-center rounded-[15px] bg-white/76 text-orange-500 shadow-lg shadow-black/12 transition hover:-translate-y-2 hover:scale-110"
          >
            <FolderIcon className="size-6" />
          </button>
          <button
            type="button"
            onClick={() => setShowWidget(!showWidget)}
            title={t.desktop.dock.systemMonitor}
            className={cn(
              "grid size-[54px] place-items-center rounded-[15px] shadow-lg shadow-black/12 transition hover:-translate-y-2 hover:scale-110",
              showWidget
                ? "bg-blue-500 text-white ring-2 ring-blue-300"
                : "bg-white/76 text-foreground",
            )}
          >
            <CpuIcon className="size-6" />
          </button>
          <button
            type="button"
            onClick={() => navigate("/workspace")}
            title={t.desktop.dock.settings}
            className="grid size-[54px] place-items-center rounded-[15px] bg-white/76 text-foreground shadow-lg shadow-black/12 transition hover:-translate-y-2 hover:scale-110"
          >
            <SettingsIcon className="size-6" />
          </button>
        </nav>
        {showWidget && systemInfo && (
          <div
            data-desktop-interactive
            className="absolute bottom-24 right-8 z-20 w-64 rounded-2xl border border-white/34 bg-white/78 p-4 text-foreground shadow-2xl shadow-black/24 backdrop-blur-2xl"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-muted-foreground">
                {t.desktop.systemWidget.title}
              </span>
              <button
                type="button"
                onClick={() => setShowWidget(false)}
                className="grid size-5 place-items-center rounded-full text-muted-foreground/70 transition hover:bg-muted hover:text-muted-foreground"
              >
                <XIcon className="size-3" />
              </button>
            </div>
            <div className="mt-3 space-y-3">
              <div>
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <CpuIcon className="size-3" /> {t.desktop.systemWidget.cpu}
                  </span>
                  <span className="font-medium">{systemInfo.cpu.usage}%</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      systemInfo.cpu.usage > 80
                        ? "bg-red-500"
                        : systemInfo.cpu.usage > 50
                          ? "bg-amber-500"
                          : "bg-emerald-500",
                    )}
                    style={{ width: `${systemInfo.cpu.usage}%` }}
                  />
                </div>
                <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                  {systemInfo.cpu.model.split(" ").slice(0, 3).join(" ")} ·{" "}
                  {systemInfo.cpu.cores} {t.desktop.systemWidget.cores}
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <HardDriveIcon className="size-3" />{" "}
                    {t.desktop.systemWidget.memory}
                  </span>
                  <span className="font-medium">
                    {systemInfo.memory.percent}%
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      systemInfo.memory.percent > 80
                        ? "bg-red-500"
                        : systemInfo.memory.percent > 50
                          ? "bg-amber-500"
                          : "bg-blue-500",
                    )}
                    style={{ width: `${systemInfo.memory.percent}%` }}
                  />
                </div>
                <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                  {systemInfo.memory.used} / {systemInfo.memory.total} GB
                </div>
              </div>
              <div className="text-[10px] text-muted-foreground/70">
                {t.desktop.systemWidget.uptime(
                  Math.floor(systemInfo.uptime / 60),
                  systemInfo.uptime % 60,
                )}
              </div>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
