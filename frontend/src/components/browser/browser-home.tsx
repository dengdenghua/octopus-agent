import {
  useEffect,
  useState,
  useCallback,
  useRef,
  useMemo,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  SearchIcon,
  BotIcon,
  HomeIcon,
  PaletteIcon,
  PanelLeftIcon,
  ImageIcon,
  Gamepad2Icon,
  CirclePlusIcon,
  SettingsIcon,
  CalendarDaysIcon,
  CheckIcon,
  ChevronDownIcon,
  FileTextIcon,
  Clock3Icon,
  LayoutGridIcon,
  SparklesIcon,
  BookOpenIcon,
  MessageCircleIcon,
  BrainCircuitIcon,
  GraduationCapIcon,
  Edit3,
  Folder,
  FolderOpen,
  Trash2,
  X,
  Plus,
  Minimize2,
  Maximize2,
  type LucideIcon,
} from "lucide-react";

import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";

import { liquidGlassClass } from "./liquid-glass";
import { useBrowserStore, type BrowserTab } from "./browser-store";

type DesktopPanelId =
  | "home"
  | "theme"
  | "widgets"
  | "wallpaper"
  | "games"
  | "add"
  | "settings";
type DesktopAppCategory = "ai" | "video" | "dev" | "knowledge";

interface BrowserDesktopApp {
  name: string;
  url: string;
  icon: LucideIcon;
  logoUrl: string;
  color: string;
  description: string;
  category: DesktopAppCategory;
}

interface QuickLink {
  id: string;
  name: string;
  url: string;
  icon: string;
  category: string;
  color?: string;
  folderId?: string;
}

interface UserFolder {
  id: string;
  name: string;
  linkIds: string[];
}

interface Widget {
  id: string;
  type: "weather" | "calendar" | "notes" | "system" | "ai-tools" | "bookmarks";
  size: "small" | "medium" | "large";
  title: string;
}

interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  targetId: string | null;
  targetType: "icon" | "widget" | "folder" | "background";
}

interface AddMenuState {
  visible: boolean;
  x: number;
  y: number;
}

interface DragState {
  draggedId: string | null;
  draggedType: "widget" | "icon" | null;
  dropTargetId: string | null;
  dropPosition: "before" | "after" | null;
}

interface EditWidgetState {
  visible: boolean;
  widgetId: string | null;
  title: string;
  type: Widget["type"];
  size: Widget["size"];
}

const AI_DESKTOP_APPS: BrowserDesktopApp[] = [
  {
    name: "Gemini",
    url: "https://gemini.google.com/app",
    icon: SparklesIcon,
    logoUrl: "https://cdn.simpleicons.org/googlegemini",
    color: "from-blue-500 to-cyan-400",
    description: "Comprehensive search, multi-turn analysis",
    category: "ai",
  },
  {
    name: "NotebookLM",
    url: "https://notebooklm.google.com/",
    icon: BookOpenIcon,
    logoUrl: "https://cdn.simpleicons.org/notebooklm",
    color: "from-amber-500 to-orange-400",
    description: "Library, citations, document research",
    category: "ai",
  },
  {
    name: "Doubao",
    url: "https://www.doubao.com/chat/",
    icon: MessageCircleIcon,
    logoUrl: "https://www.google.com/s2/favicons?domain=www.doubao.com&sz=128",
    color: "from-emerald-500 to-teal-400",
    description: "Chinese research, Chinese rewriting",
    category: "ai",
  },
  {
    name: "DeepSeek",
    url: "https://chat.deepseek.com/",
    icon: BrainCircuitIcon,
    logoUrl: "https://cdn.simpleicons.org/deepseek",
    color: "from-blue-700 to-indigo-500",
    description: "Reasoning, coding, Chinese Q&A",
    category: "ai",
  },
  {
    name: "Tongyi Qianwen",
    url: "https://chat.qwen.ai/",
    icon: SparklesIcon,
    logoUrl: "https://cdn.simpleicons.org/qwen",
    color: "from-blue-600 to-cyan-500",
    description: "Tongyi models, multimodal chat",
    category: "ai",
  },
  {
    name: "Wenxin Yiyan",
    url: "https://yiyan.baidu.com/",
    icon: MessageCircleIcon,
    logoUrl: "https://cdn.simpleicons.org/baidu",
    color: "from-indigo-600 to-blue-500",
    description: "Baidu agents, Chinese creation",
    category: "ai",
  },
  {
    name: "Tencent Yuanbao",
    url: "https://yuanbao.tencent.com/",
    icon: BotIcon,
    logoUrl:
      "https://www.google.com/s2/favicons?domain=yuanbao.tencent.com&sz=128",
    color: "from-cyan-600 to-blue-500",
    description: "Chinese search, material summary",
    category: "ai",
  },
  {
    name: "Perplexity",
    url: "https://www.perplexity.ai/",
    icon: SearchIcon,
    logoUrl: "https://cdn.simpleicons.org/perplexity",
    color: "from-sky-500 to-indigo-500",
    description: "Web search, source leads",
    category: "ai",
  },
  {
    name: "ChatGPT",
    url: "https://chatgpt.com/",
    icon: BotIcon,
    logoUrl: "https://chatgpt.com/favicon.ico",
    color: "from-zinc-700 to-zinc-500",
    description: "General chat, coding assistance",
    category: "ai",
  },
  {
    name: "Claude",
    url: "https://claude.ai/",
    icon: BrainCircuitIcon,
    logoUrl: "https://cdn.simpleicons.org/claude",
    color: "from-stone-600 to-rose-400",
    description: "Long-text analysis, writing organization",
    category: "ai",
  },
  {
    name: "Kimi",
    url: "https://www.kimi.com/",
    icon: GraduationCapIcon,
    logoUrl: "https://www.google.com/s2/favicons?domain=www.kimi.com&sz=128",
    color: "from-violet-500 to-fuchsia-500",
    description: "Long context, Chinese materials",
    category: "ai",
  },
  {
    name: "Agnes AI",
    url: "https://app.agnes-ai.com/",
    icon: ImageIcon,
    logoUrl:
      "https://www.google.com/s2/favicons?domain=app.agnes-ai.com&sz=128",
    color: "from-pink-500 to-rose-400",
    description: "AI gateway, image/video generation",
    category: "ai",
  },
  {
    name: "YouTube",
    url: "https://www.youtube.com/",
    icon: ImageIcon,
    logoUrl: "https://cdn.simpleicons.org/youtube",
    color: "from-red-600 to-red-500",
    description: "Videos, channels, live streams",
    category: "video",
  },
  {
    name: "Bilibili",
    url: "https://www.bilibili.com/",
    icon: ImageIcon,
    logoUrl: "https://cdn.simpleicons.org/bilibili",
    color: "from-sky-500 to-cyan-400",
    description: "Videos, anime, knowledge zone",
    category: "video",
  },
  {
    name: "GitHub",
    url: "https://github.com/",
    icon: BotIcon,
    logoUrl: "https://github.githubassets.com/favicons/favicon.svg",
    color: "from-zinc-900 to-zinc-700",
    description: "Code repos, project collaboration",
    category: "dev",
  },
  {
    name: "Stack Overflow",
    url: "https://stackoverflow.com/",
    icon: BrainCircuitIcon,
    logoUrl: "https://cdn.simpleicons.org/stackoverflow",
    color: "from-orange-500 to-amber-400",
    description: "Programming Q&A, troubleshooting",
    category: "dev",
  },
  {
    name: "MDN",
    url: "https://developer.mozilla.org/",
    icon: BookOpenIcon,
    logoUrl: "https://cdn.simpleicons.org/mdnwebdocs",
    color: "from-slate-900 to-blue-600",
    description: "Web docs, API reference",
    category: "dev",
  },
  {
    name: "Zhihu",
    url: "https://www.zhihu.com/",
    icon: SearchIcon,
    logoUrl: "https://cdn.simpleicons.org/zhihu",
    color: "from-blue-600 to-sky-500",
    description: "Q&A, columns, Chinese materials",
    category: "knowledge",
  },
  {
    name: "Wikipedia",
    url: "https://www.wikipedia.org/",
    icon: GraduationCapIcon,
    logoUrl: "https://cdn.simpleicons.org/wikipedia",
    color: "from-slate-700 to-slate-500",
    description: "Encyclopedia, background materials",
    category: "knowledge",
  },
];

const DESKTOP_APP_GROUPS: Array<{
  id: DesktopAppCategory;
  appUrls: string[];
}> = [
  {
    id: "ai",
    appUrls: [
      "https://gemini.google.com/app",
      "https://notebooklm.google.com/",
      "https://chatgpt.com/",
      "https://www.doubao.com/chat/",
      "https://chat.deepseek.com/",
      "https://chat.qwen.ai/",
      "https://yiyan.baidu.com/",
      "https://yuanbao.tencent.com/",
    ],
  },
  {
    id: "video",
    appUrls: ["https://www.youtube.com/", "https://www.bilibili.com/"],
  },
  {
    id: "dev",
    appUrls: [
      "https://github.com/",
      "https://stackoverflow.com/",
      "https://developer.mozilla.org/",
    ],
  },
  {
    id: "knowledge",
    appUrls: ["https://www.zhihu.com/", "https://www.wikipedia.org/"],
  },
];

const DESKTOP_SIDE_NAV: Array<{
  id: DesktopPanelId;
  icon: LucideIcon;
}> = [
  { id: "home", icon: HomeIcon },
  { id: "theme", icon: PaletteIcon },
  { id: "widgets", icon: PanelLeftIcon },
  { id: "wallpaper", icon: ImageIcon },
  { id: "games", icon: Gamepad2Icon },
];

const SEARCH_ENGINES = [
  {
    name: "Baidu",
    url: "https://www.baidu.com/s?wd=",
    icon: "Bai",
    logoUrl: "https://www.baidu.com/favicon.ico",
    accent: "bg-[#2f6bff] text-white",
  },
  {
    name: "Google",
    url: "https://www.google.com/search?q=",
    icon: "G",
    logoUrl: "https://www.google.com/favicon.ico",
    accent: "bg-white text-[#4285f4]",
  },
  {
    name: "Bing",
    url: "https://www.bing.com/search?q=",
    icon: "B",
    logoUrl: "https://www.bing.com/favicon.ico",
    accent: "bg-[#008373] text-white",
  },
  {
    name: "GitHub",
    url: "https://github.com/search?q=",
    icon: "GH",
    logoUrl: "https://github.githubassets.com/favicons/favicon.svg",
    accent: "bg-[#24292f] text-white",
  },
];

type SearchEngine = (typeof SEARCH_ENGINES)[number];

function DesktopAppLogo({
  app,
  className,
  iconClassName,
}: {
  app: BrowserDesktopApp;
  className?: string;
  iconClassName?: string;
}) {
  const [failed, setFailed] = useState(false);
  const FallbackIcon = app.icon;

  return (
    <span
      className={cn(
        "grid place-items-center overflow-hidden rounded-[18px] border border-white/65 bg-white/72 text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.78),0_10px_26px_rgba(15,23,42,0.14)] ring-1 ring-black/5 backdrop-blur-xl transition",
        className,
        failed && "bg-gradient-to-br text-white",
        failed && app.color,
      )}
    >
      {failed ? (
        <FallbackIcon className={cn("size-1/2", iconClassName)} />
      ) : (
        <img
          src={app.logoUrl}
          alt=""
          className={cn("size-[68%] object-contain", iconClassName)}
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}

function SearchEngineLogo({
  engine,
  className,
}: {
  engine: SearchEngine;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);

  return (
    <span
      className={cn(
        "grid place-items-center overflow-hidden rounded-full bg-white shadow-sm ring-1 ring-black/5",
        className,
      )}
    >
      {failed ? (
        <span
          className={cn(
            "grid size-full place-items-center text-[10px] font-black leading-none",
            engine.accent,
          )}
        >
          {engine.icon}
        </span>
      ) : (
        <img
          src={engine.logoUrl}
          alt=""
          className="size-[68%] object-contain"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}

const DESKTOP_APP_ORDER_KEY = "octopus:browser-desktop-app-order";
const DOCK_APP_URLS_KEY = "octopus:browser:dock-app-urls";
const QUICK_LINKS_KEY = "octopus:browser:quick-links";
const FOLDERS_KEY = "octopus:browser:folders";
const WIDGETS_KEY = "octopus:browser:widgets";
const DEFAULT_DOCK_APP_URLS = [
  "https://gemini.google.com/app",
  "https://chat.deepseek.com/",
  "https://chat.qwen.ai/",
  "https://www.doubao.com/chat/",
  "https://chatgpt.com/",
  "https://notebooklm.google.com/",
  "https://www.youtube.com/",
  "https://www.bilibili.com/",
  "https://github.com/",
  "https://www.perplexity.ai/",
];

function loadDesktopAppOrder(): string[] {
  if (typeof window === "undefined")
    return AI_DESKTOP_APPS.map((app) => app.url);
  try {
    const parsed = JSON.parse(
      localStorage.getItem(DESKTOP_APP_ORDER_KEY) || "[]",
    );
    if (!Array.isArray(parsed)) return AI_DESKTOP_APPS.map((app) => app.url);
    const known = new Set(AI_DESKTOP_APPS.map((app) => app.url));
    const saved = parsed.filter(
      (item): item is string => typeof item === "string" && known.has(item),
    );
    const missing = AI_DESKTOP_APPS.map((app) => app.url).filter(
      (url) => !saved.includes(url),
    );
    return [...saved, ...missing];
  } catch (e) {
    swallow(e);
    return AI_DESKTOP_APPS.map((app) => app.url);
  }
}

function orderDesktopApps(order: string[]): BrowserDesktopApp[] {
  const byUrl = new Map(AI_DESKTOP_APPS.map((app) => [app.url, app]));
  return order
    .map((url) => byUrl.get(url))
    .filter((app): app is BrowserDesktopApp => Boolean(app));
}

function loadDockAppUrls(): string[] {
  if (typeof window === "undefined") return DEFAULT_DOCK_APP_URLS;
  try {
    const known = new Set(AI_DESKTOP_APPS.map((app) => app.url));
    const parsed = JSON.parse(localStorage.getItem(DOCK_APP_URLS_KEY) || "[]");
    if (!Array.isArray(parsed) || parsed.length === 0)
      return DEFAULT_DOCK_APP_URLS;
    return parsed.filter(
      (item): item is string => typeof item === "string" && known.has(item),
    );
  } catch (e) {
    swallow(e);
    return DEFAULT_DOCK_APP_URLS;
  }
}

function moveDesktopApp(
  order: string[],
  fromUrl: string,
  toUrl: string,
): string[] {
  if (fromUrl === toUrl) return order;
  const next = order.filter((url) => url !== fromUrl);
  const targetIndex = next.indexOf(toUrl);
  if (targetIndex < 0) return order;
  next.splice(targetIndex, 0, fromUrl);
  return next;
}

function MenuItem({
  icon: Icon,
  label,
  active,
  danger,
  shortcut,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  danger?: boolean;
  shortcut?: string;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors rounded-lg",
        active
          ? "bg-sky-400/20 text-sky-400"
          : "text-slate-600 hover:bg-white/50 hover:text-slate-800",
        danger && "text-red-500 hover:bg-red-400/10",
      )}
    >
      <Icon className="w-4 h-4 flex-shrink-0" />
      <span className="flex-1 text-left">{label}</span>
      {shortcut && <span className="text-xs text-slate-400">{shortcut}</span>}
    </button>
  );
}

function ContextMenu({
  state,
  onClose,
  onEdit,
  onDelete,
  onResize,
  currentSize,
}: {
  state: ContextMenuState;
  onClose: () => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onResize: (id: string, size: string) => void;
  currentSize?: string;
}) {
  const { t } = useI18n();
  const wt = t.browser.webviewTab;

  if (!state.visible) return null;

  const isIcon = state.targetType === "icon";
  const isWidget = state.targetType === "widget";
  const isFolder = state.targetType === "folder";

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        className="fixed z-50 bg-white/95 backdrop-blur-xl border border-white/30 rounded-2xl py-2 min-w-[160px] shadow-2xl"
        style={{ left: state.x, top: state.y }}
      >
        {isIcon && (
          <>
            <MenuItem
              icon={Edit3}
              label={wt.ctxEditIcon}
              onClick={() => {
                onEdit(state.targetId!);
                onClose();
              }}
            />
            <MenuItem
              icon={Trash2}
              label={wt.ctxDelete}
              danger
              onClick={() => {
                onDelete(state.targetId!);
                onClose();
              }}
            />
            <div className="h-px bg-slate-200 my-2" />
            <MenuItem
              icon={Minimize2}
              label={wt.ctxSizeSmall}
              active={currentSize === "small"}
              onClick={() => {
                onResize(state.targetId!, "small");
                onClose();
              }}
            />
            <MenuItem
              icon={LayoutGridIcon}
              label={wt.ctxSizeMedium}
              active={currentSize === "medium"}
              onClick={() => {
                onResize(state.targetId!, "medium");
                onClose();
              }}
            />
            <MenuItem
              icon={Maximize2}
              label={wt.ctxSizeLarge}
              active={currentSize === "large"}
              onClick={() => {
                onResize(state.targetId!, "large");
                onClose();
              }}
            />
          </>
        )}
        {isWidget && (
          <>
            <MenuItem
              icon={Edit3}
              label={wt.ctxEditWidget}
              onClick={() => {
                onEdit(state.targetId!);
                onClose();
              }}
            />
            <MenuItem
              icon={Trash2}
              label={wt.ctxDelete}
              danger
              onClick={() => {
                onDelete(state.targetId!);
                onClose();
              }}
            />
            <div className="h-px bg-slate-200 my-2" />
            <MenuItem
              icon={Minimize2}
              label={wt.ctxSizeSmall}
              active={currentSize === "small"}
              onClick={() => {
                onResize(state.targetId!, "small");
                onClose();
              }}
            />
            <MenuItem
              icon={LayoutGridIcon}
              label={wt.ctxSizeMedium}
              active={currentSize === "medium"}
              onClick={() => {
                onResize(state.targetId!, "medium");
                onClose();
              }}
            />
            <MenuItem
              icon={Maximize2}
              label={wt.ctxSizeLarge}
              active={currentSize === "large"}
              onClick={() => {
                onResize(state.targetId!, "large");
                onClose();
              }}
            />
          </>
        )}
        {isFolder && (
          <>
            <MenuItem
              icon={Edit3}
              label={wt.ctxEditFolder}
              onClick={() => {
                onEdit(state.targetId!);
                onClose();
              }}
            />
            <MenuItem
              icon={Trash2}
              label={wt.ctxDelete}
              danger
              onClick={() => {
                onDelete(state.targetId!);
                onClose();
              }}
            />
          </>
        )}
        {state.targetType === "background" && (
          <>
            <MenuItem icon={LayoutGridIcon} label={wt.ctxEditHome} />
            <MenuItem icon={Plus} label={wt.ctxAddWidget} />
            <MenuItem icon={Plus} label={wt.ctxAddIcon} />
            <div className="h-px bg-slate-200 my-2" />
            <MenuItem icon={SettingsIcon} label={wt.ctxSettings} />
          </>
        )}
      </div>
    </>
  );
}

export function BrowserHome({
  active,
  device,
  onOpen,
}: {
  active: boolean;
  device: BrowserTab["device"];
  onOpen: (url: string) => void;
}) {
  const { t } = useI18n();
  const wt = t.browser.webviewTab;
  const bt = t.browserHome;
  const { bookmarks, history } = useBrowserStore();

  const appNameMap = useMemo<Record<string, string>>(
    () => ({
      Doubao: bt.appNameDoubao,
      "Tongyi Qianwen": bt.appNameTongyiQianwen,
      "Wenxin Yiyan": bt.appNameWenxinYiyan,
      "Tencent Yuanbao": bt.appNameTencentYuanbao,
      Zhihu: bt.appNameZhihu,
    }),
    [bt],
  );

  const appDescMap = useMemo<Record<string, string>>(
    () => ({
      "Comprehensive search, multi-turn analysis": bt.appDescGemini,
      "Library, citations, document research": bt.appDescNotebookLM,
      "Chinese research, Chinese rewriting": bt.appDescDoubao,
      "Reasoning, coding, Chinese Q&A": bt.appDescTongyiQianwen,
      "Tongyi models, multimodal chat": bt.appDescWenxinYiyan,
      "Baidu agents, Chinese creation": bt.appDescTencentYuanbao,
      "Web search, source leads": bt.appDescPerplexity,
      "General chat, coding assistance": bt.appDescChatGPT,
      "Long-text analysis, writing organization": bt.appDescClaude,
      "Long context, Chinese materials": bt.appDescKimi,
      "AI gateway, image/video generation": bt.appDescAgnesAi,
      "Videos, channels, live streams": bt.appDescYouTube,
      "Videos, anime, knowledge zone": bt.appDescBilibili,
      "Code repos, project collaboration": bt.appDescGitHub,
      "Programming Q&A, troubleshooting": bt.appDescStackOverflow,
      "Web docs, API reference": bt.appDescMdn,
      "Q&A, columns, Chinese materials": bt.appDescZhihu,
      "Encyclopedia, background materials": bt.appDescWikipedia,
    }),
    [bt],
  );

  const sideNavLabelMap = useMemo<Record<string, string>>(
    () => ({
      home: wt.navHome,
      theme: wt.navTheme,
      widgets: wt.navWidgets,
      wallpaper: wt.navWallpaper,
      games: wt.navGames,
    }),
    [wt],
  );

  const [query, setQuery] = useState("");
  const [selectedEngine, setSelectedEngine] = useState(0);
  const [enginePickerOpen, setEnginePickerOpen] = useState(false);
  const [openAppGroupId, setOpenAppGroupId] =
    useState<DesktopAppCategory | null>(null);
  const [activePanel, setActivePanel] = useState<DesktopPanelId>("home");
  const [editMode, setEditMode] = useState(false);
  const [appOrder, setAppOrder] = useState<string[]>(() =>
    loadDesktopAppOrder(),
  );
  const [dockAppUrls, setDockAppUrls] = useState<string[]>(() =>
    loadDockAppUrls(),
  );
  const [draggingUrl, setDraggingUrl] = useState<string | null>(null);
  const [searchFilter, setSearchFilter] = useState("");
  const [quickLinks, setQuickLinks] = useState<QuickLink[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      return JSON.parse(localStorage.getItem(QUICK_LINKS_KEY) || "[]");
    } catch (e) {
      swallow(e);
      return [];
    }
  });
  const [folders, setFolders] = useState<UserFolder[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      return JSON.parse(localStorage.getItem(FOLDERS_KEY) || "[]");
    } catch (e) {
      swallow(e);
      return [];
    }
  });
  const [widgets, setWidgets] = useState<Widget[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      return JSON.parse(localStorage.getItem(WIDGETS_KEY) || "[]");
    } catch (e) {
      swallow(e);
      return [];
    }
  });
  const [folderOpenStates, setFolderOpenStates] = useState<
    Record<string, boolean>
  >({});
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    targetId: null,
    targetType: "background",
  });
  const [addMenu, setAddMenu] = useState<AddMenuState>({
    visible: false,
    x: 0,
    y: 0,
  });
  const [dragState, setDragState] = useState<DragState>({
    draggedId: null,
    draggedType: null,
    dropTargetId: null,
    dropPosition: null,
  });
  const [editWidgetState, setEditWidgetState] = useState<EditWidgetState>({
    visible: false,
    widgetId: null,
    title: "",
    type: "notes",
    size: "medium",
  });

  const orderedApps = orderDesktopApps(appOrder);
  const appByUrl = useMemo(
    () => new Map(AI_DESKTOP_APPS.map((app) => [app.url, app])),
    [],
  );
  const dockApps = useMemo(
    () =>
      dockAppUrls
        .map((url) => appByUrl.get(url))
        .filter((app): app is BrowserDesktopApp => Boolean(app)),
    [appByUrl, dockAppUrls],
  );
  const getAppName = useCallback(
    (name: string) => appNameMap[name] ?? name,
    [appNameMap],
  );
  const getAppDesc = useCallback(
    (desc: string) => appDescMap[desc] ?? desc,
    [appDescMap],
  );
  const bookmarkPanelItems = useMemo(() => {
    const sourceItems =
      bookmarks.length > 0
        ? bookmarks.map((item) => ({
            url: item.url,
            title: item.title || item.url,
            favicon: item.favicon,
            meta: bt.metaBookmark,
          }))
        : history
            .filter(
              (item) =>
                item.url &&
                !item.url.startsWith("about:") &&
                !item.url.startsWith("octopus:"),
            )
            .map((item) => ({
              url: item.url,
              title: item.title || item.url,
              favicon: item.favicon,
              meta: bt.metaRecent,
            }));

    if (sourceItems.length > 0) return sourceItems.slice(0, 6);

    return [
      "https://chat.deepseek.com/",
      "https://chat.qwen.ai/",
      "https://www.youtube.com/",
      "https://github.com/",
      "https://www.bilibili.com/",
      "https://www.perplexity.ai/",
    ]
      .map((url) => appByUrl.get(url))
      .filter((app): app is BrowserDesktopApp => Boolean(app))
      .map((app) => ({
        url: app.url,
        title: appNameMap[app.name] ?? app.name,
        favicon: app.logoUrl,
        meta:
          app.category === "video"
            ? bt.categoryVideo
            : app.category === "dev"
              ? bt.categoryDev
              : "AI",
      }));
  }, [appByUrl, appNameMap, bookmarks, bt, history]);
  const desktopAppGroups = useMemo(() => {
    const titles: Record<
      DesktopAppCategory,
      { title: string; subtitle: string }
    > = {
      ai: { title: bt.groupAiTools, subtitle: bt.groupAiToolsSubtitle },
      video: { title: bt.groupVideo, subtitle: bt.groupVideoSubtitle },
      dev: { title: bt.groupDev, subtitle: bt.groupDevSubtitle },
      knowledge: {
        title: bt.groupKnowledge,
        subtitle: bt.groupKnowledgeSubtitle,
      },
    };
    return DESKTOP_APP_GROUPS.map((group) => ({
      ...titles[group.id],
      id: group.id,
      apps: group.appUrls
        .map((url) => appByUrl.get(url))
        .filter((app): app is BrowserDesktopApp => Boolean(app)),
    }));
  }, [appByUrl, bt]);
  const compactDesktop = device !== "desktop";
  const tabletDesktop = device === "tablet";
  const mobileDesktop = device === "mobile";
  const today = new Date();
  const day = today.getDate().toString().padStart(2, "0");
  const month = wt.monthFormat(today.getFullYear(), today.getMonth() + 1);
  const week = wt.weekdays[today.getDay()];
  const searchInputRef = useRef<HTMLInputElement>(null);
  const enginePickerRef = useRef<HTMLDivElement>(null);
  const searchEngineNameMap = useMemo<Record<string, string>>(
    () => ({
      Baidu: bt.searchEngineBaidu,
    }),
    [bt],
  );
  const searchEngineIconMap = useMemo<Record<string, string>>(
    () => ({
      Bai: bt.searchEngineBaiduIcon,
    }),
    [bt],
  );
  const engines = useMemo(
    () =>
      SEARCH_ENGINES.map((engine) => ({
        ...engine,
        name: searchEngineNameMap[engine.name] ?? engine.name,
        icon: searchEngineIconMap[engine.icon] ?? engine.icon,
      })),
    [searchEngineNameMap, searchEngineIconMap],
  );
  const selectedSearchEngine = engines[selectedEngine] ?? engines[0]!;
  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(DESKTOP_APP_ORDER_KEY, JSON.stringify(appOrder));
  }, [appOrder]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(DOCK_APP_URLS_KEY, JSON.stringify(dockAppUrls));
  }, [dockAppUrls]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(QUICK_LINKS_KEY, JSON.stringify(quickLinks));
  }, [quickLinks]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders));
  }, [folders]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(WIDGETS_KEY, JSON.stringify(widgets));
  }, [widgets]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
      if (e.key === "/" && document.activeElement !== searchInputRef.current) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
      if (e.key === "Escape") {
        setContextMenu((prev) => ({ ...prev, visible: false }));
        setAddMenu((prev) => ({ ...prev, visible: false }));
        setEnginePickerOpen(false);
        setEditMode(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (!enginePickerOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        enginePickerRef.current &&
        !enginePickerRef.current.contains(event.target as Node)
      ) {
        setEnginePickerOpen(false);
      }
    };
    window.addEventListener("pointerdown", handlePointerDown);
    return () => window.removeEventListener("pointerdown", handlePointerDown);
  }, [enginePickerOpen]);

  const submitSearch = () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    const engine = selectedSearchEngine;
    if (!engine) return;
    const target = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed)
      ? trimmed
      : /\s/.test(trimmed) || !trimmed.includes(".")
        ? engine.url + encodeURIComponent(trimmed)
        : `https://${trimmed}`;
    setEnginePickerOpen(false);
    onOpen(target);
  };

  const onSearchKey = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") submitSearch();
  };

  const startAppDrag = (event: DragEvent<HTMLElement>, url: string) => {
    if (!editMode) return;
    setDraggingUrl(url);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", url);
  };

  const dropApp = (event: DragEvent<HTMLElement>, targetUrl: string) => {
    if (!editMode) return;
    event.preventDefault();
    const sourceUrl = draggingUrl || event.dataTransfer.getData("text/plain");
    if (!sourceUrl) return;
    setAppOrder((prev) => moveDesktopApp(prev, sourceUrl, targetUrl));
    setDraggingUrl(null);
  };

  const dropDockApp = (event: DragEvent<HTMLElement>, targetUrl: string) => {
    if (!editMode) return;
    event.preventDefault();
    const sourceUrl = draggingUrl || event.dataTransfer.getData("text/plain");
    if (!sourceUrl) return;
    setDockAppUrls((prev) => moveDesktopApp(prev, sourceUrl, targetUrl));
    setDraggingUrl(null);
  };

  const addAppToDock = useCallback((url: string) => {
    setDockAppUrls((prev) =>
      prev.includes(url) ? prev : [...prev, url].slice(0, 12),
    );
  }, []);

  const removeAppFromDock = useCallback((url: string) => {
    setDockAppUrls((prev) => prev.filter((item) => item !== url));
  }, []);

  const resetDesktopLayout = () => {
    setAppOrder(AI_DESKTOP_APPS.map((app) => app.url));
    setDockAppUrls(DEFAULT_DOCK_APP_URLS);
    setDraggingUrl(null);
  };

  const handleContext = useCallback(
    (
      e: React.MouseEvent,
      id: string | null,
      type: ContextMenuState["targetType"],
    ) => {
      e.preventDefault();
      setContextMenu({
        visible: true,
        x: Math.min(e.clientX, window.innerWidth - 180),
        y: Math.min(e.clientY, window.innerHeight - 300),
        targetId: id,
        targetType: type,
      });
    },
    [],
  );

  const handleBackgroundContext = useCallback(
    (e: React.MouseEvent) => {
      handleContext(e, null, "background");
    },
    [handleContext],
  );

  const handleEdit = useCallback(
    (id: string) => {
      const widget = widgets.find((w) => w.id === id);
      if (widget) {
        setEditWidgetState({
          visible: true,
          widgetId: id,
          title: widget.title,
          type: widget.type,
          size: widget.size,
        });
      }
    },
    [widgets],
  );

  const handleSaveWidget = useCallback(() => {
    const { widgetId, title, type, size } = editWidgetState;
    if (!widgetId) return;
    setWidgets((prev) =>
      prev.map((w) => (w.id === widgetId ? { ...w, title, type, size } : w)),
    );
    setEditWidgetState({
      visible: false,
      widgetId: null,
      title: "",
      type: "notes",
      size: "medium",
    });
  }, [editWidgetState]);

  const handleDelete = useCallback((id: string) => {
    setQuickLinks((prev) => prev.filter((l) => l.id !== id));
    setWidgets((prev) => prev.filter((w) => w.id !== id));
    setFolders((prev) =>
      prev.map((f) => ({
        ...f,
        linkIds: f.linkIds.filter((linkId) => linkId !== id),
      })),
    );
  }, []);

  const handleResize = useCallback((_id: string, _size: string) => {}, []);

  const handleAddWidget = useCallback(() => {
    const newWidget: Widget = {
      id: `w-${Date.now()}`,
      type: "notes",
      size: "medium",
      title: wt.newWidget,
    };
    setWidgets((prev) => [...prev, newWidget]);
  }, [wt.newWidget]);

  const handleAddIcon = useCallback(() => {
    const name = prompt(wt.promptSiteName);
    if (!name) return;
    const url = prompt(wt.promptSiteUrl);
    if (!url) return;
    const newLink: QuickLink = {
      id: Date.now().toString(),
      name,
      url: url.startsWith("http") ? url : `https://${url}`,
      icon: "Globe",
      category: "tool",
    };
    setQuickLinks((prev) => [...prev, newLink]);
  }, [wt.promptSiteName, wt.promptSiteUrl]);

  const handleCreateFolder = useCallback(() => {
    const name = prompt(wt.promptFolderName);
    if (!name) return;
    const newFolder: UserFolder = {
      id: `folder-${Date.now()}`,
      name,
      linkIds: [],
    };
    setFolders((prev) => [...prev, newFolder]);
  }, [wt.promptFolderName]);

  const handleWidgetDragStart = useCallback((id: string) => {
    setDragState({
      draggedId: id,
      draggedType: "widget",
      dropTargetId: null,
      dropPosition: null,
    });
  }, []);

  const handleWidgetDragOver = useCallback((e: React.DragEvent, id: string) => {
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const position = e.clientY < midY ? "before" : "after";
    setDragState((prev) => ({
      ...prev,
      dropTargetId: id,
      dropPosition: position,
    }));
  }, []);

  const handleWidgetDrop = useCallback(
    (targetId: string) => {
      const { draggedId, draggedType, dropPosition } = dragState;
      if (!draggedId || draggedType !== "widget" || draggedId === targetId)
        return;
      setWidgets((prev) => {
        const draggedIndex = prev.findIndex((w) => w.id === draggedId);
        const targetIndex = prev.findIndex((w) => w.id === targetId);
        if (draggedIndex === -1 || targetIndex === -1) return prev;
        const newWidgets = [...prev];
        const [draggedWidget] = newWidgets.splice(draggedIndex, 1);
        const newTargetIndex = newWidgets.findIndex((w) => w.id === targetId);
        const insertIndex =
          dropPosition === "after" ? newTargetIndex + 1 : newTargetIndex;
        if (draggedWidget) newWidgets.splice(insertIndex, 0, draggedWidget);
        return newWidgets;
      });
      setDragState({
        draggedId: null,
        draggedType: null,
        dropTargetId: null,
        dropPosition: null,
      });
    },
    [dragState],
  );

  const handleIconDragStart = useCallback((id: string) => {
    setDragState({
      draggedId: id,
      draggedType: "icon",
      dropTargetId: null,
      dropPosition: null,
    });
  }, []);

  const handleIconDragOver = useCallback((e: React.DragEvent, id: string) => {
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const midX = rect.left + rect.width / 2;
    const position = e.clientX < midX ? "before" : "after";
    setDragState((prev) => ({
      ...prev,
      dropTargetId: id,
      dropPosition: position,
    }));
  }, []);

  const handleIconDrop = useCallback(
    (targetId: string) => {
      const { draggedId, draggedType, dropPosition } = dragState;
      if (!draggedId || draggedType !== "icon" || draggedId === targetId)
        return;
      setQuickLinks((prev) => {
        const standaloneLinks = prev.filter((l) => !l.folderId);
        const draggedIndex = standaloneLinks.findIndex(
          (l) => l.id === draggedId,
        );
        const targetIndex = standaloneLinks.findIndex((l) => l.id === targetId);
        if (draggedIndex === -1 || targetIndex === -1) return prev;
        const newLinks = [...prev];
        const draggedLink = newLinks.find((l) => l.id === draggedId);
        if (!draggedLink) return prev;
        const newStandaloneLinks = newLinks.filter((l) => !l.folderId);
        const [removedDragged] = newStandaloneLinks.splice(draggedIndex, 1);
        const newTargetIndex = newStandaloneLinks.findIndex(
          (l) => l.id === targetId,
        );
        const insertIndex =
          dropPosition === "after" ? newTargetIndex + 1 : newTargetIndex;
        if (removedDragged)
          newStandaloneLinks.splice(insertIndex, 0, removedDragged);
        const folderLinks = newLinks.filter((l) => l.folderId);
        return [...newStandaloneLinks, ...folderLinks];
      });
      setDragState({
        draggedId: null,
        draggedType: null,
        dropTargetId: null,
        dropPosition: null,
      });
    },
    [dragState],
  );

  const handleDropOnFolder = useCallback(
    (folderId: string) => {
      const { draggedId, draggedType } = dragState;
      if (!draggedId || draggedType !== "icon") return;
      setFolders((prev) =>
        prev.map((f) =>
          f.id === folderId
            ? {
                ...f,
                linkIds: f.linkIds.includes(draggedId)
                  ? f.linkIds
                  : [...f.linkIds, draggedId],
              }
            : f,
        ),
      );
      setQuickLinks((prev) =>
        prev.map((l) => (l.id === draggedId ? { ...l, folderId } : l)),
      );
      setDragState({
        draggedId: null,
        draggedType: null,
        dropTargetId: null,
        dropPosition: null,
      });
    },
    [dragState],
  );

  const toggleFolder = useCallback((folderId: string) => {
    setFolderOpenStates((prev) => ({ ...prev, [folderId]: !prev[folderId] }));
  }, []);

  const handleDragEnd = useCallback(() => {
    setDragState({
      draggedId: null,
      draggedType: null,
      dropTargetId: null,
      dropPosition: null,
    });
  }, []);

  const standaloneLinks = quickLinks.filter((l) => !l.folderId);
  const folderLinks = folders.map((folder) => ({
    folder,
    links: quickLinks.filter((l) => folder.linkIds.includes(l.id)),
  }));

  return (
    <div
      style={
        active
          ? { display: "flex", width: "100%", height: "100%" }
          : {
              display: "flex",
              position: "absolute",
              width: 0,
              height: 0,
              visibility: "hidden",
              pointerEvents: "none",
            }
      }
      className="relative min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_18%_12%,rgba(255,255,255,0.72),transparent_28%),radial-gradient(circle_at_78%_8%,rgba(147,197,253,0.28),transparent_24%),radial-gradient(circle_at_84%_78%,rgba(251,207,232,0.32),transparent_32%),linear-gradient(145deg,#91a3b7_0%,#ada9b8_45%,#c0a197_100%)] text-white"
      onContextMenu={handleBackgroundContext}
    >
      <div
        className={cn(
          "absolute left-4 top-5 z-10 flex h-[calc(100%-2.5rem)] w-12 flex-col items-center rounded-[24px] border border-white/25 bg-white/14 py-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.42),0_20px_60px_rgba(15,23,42,0.20)] backdrop-blur-2xl",
          compactDesktop && "left-3 top-4 h-[calc(100%-2rem)]",
          mobileDesktop && "left-2 w-11",
        )}
      >
        <div className="grid size-8 place-items-center rounded-2xl border border-white/60 bg-white/50 text-slate-700 shadow-sm backdrop-blur-xl">
          <BotIcon className="size-5" />
        </div>
        <div className="mt-8 flex flex-col gap-4">
          {DESKTOP_SIDE_NAV.map((item) => {
            const Icon = item.icon;
            const selected = activePanel === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActivePanel(item.id)}
                className={cn(
                  "grid size-9 place-items-center rounded-2xl text-white/72 transition hover:bg-white/22 hover:text-white",
                  selected &&
                    "border border-white/35 bg-white/24 text-white shadow-[inset_0_1px_1px_rgba(255,255,255,0.35)]",
                )}
                title={sideNavLabelMap[item.id]}
              >
                <Icon className="size-5" />
              </button>
            );
          })}
        </div>
        <div className="mt-auto flex flex-col gap-4">
          <button
            type="button"
            onClick={() => setActivePanel("add")}
            className={cn(
              "grid size-9 place-items-center rounded-2xl border border-white/20 bg-white/18 text-white transition hover:bg-white/28",
              activePanel === "add" && "bg-white/30",
            )}
            title={wt.addTitle}
          >
            <CirclePlusIcon className="size-5" />
          </button>
          <button
            type="button"
            onClick={() => setActivePanel("settings")}
            className={cn(
              "grid size-9 place-items-center rounded-2xl text-white/75 transition hover:bg-white/22 hover:text-white",
              activePanel === "settings" && "bg-white/24 text-white",
            )}
            title={wt.settingsTitle}
          >
            <SettingsIcon className="size-5" />
          </button>
        </div>
      </div>

      <div
        className={cn(
          "flex h-full min-h-0 flex-col pl-24 pr-12 pt-8",
          compactDesktop && "pl-20 pr-5 pt-6 pb-28",
          tabletDesktop && "pl-24 pr-8",
          mobileDesktop && "pl-16 pr-4 pt-5 pb-24",
        )}
      >
        <div
          ref={enginePickerRef}
          className={cn(
            "relative mx-auto w-full max-w-[720px]",
            compactDesktop && "max-w-none",
            tabletDesktop && "max-w-[760px]",
          )}
        >
          <div
            className={cn(
              "flex h-14 items-center gap-3 rounded-[22px] border border-white/55 bg-white/30 px-3 text-slate-600 shadow-[inset_0_1px_1px_rgba(255,255,255,0.78),0_20px_70px_rgba(15,23,42,0.14)] ring-1 ring-black/5 backdrop-blur-2xl",
              mobileDesktop && "h-12 rounded-2xl px-2.5",
            )}
          >
            <button
              type="button"
              onClick={() => setEnginePickerOpen((value) => !value)}
              aria-haspopup="menu"
              aria-expanded={enginePickerOpen}
              title={bt.switchSearchEngine}
              className={cn(
                "group flex h-10 shrink-0 items-center gap-1 rounded-xl px-2 transition-colors hover:bg-slate-900/5",
                mobileDesktop && "h-9 px-1.5",
              )}
            >
              <SearchEngineLogo
                engine={selectedSearchEngine}
                className="size-7"
              />
              <ChevronDownIcon
                className={cn(
                  "size-3.5 text-slate-400 transition-transform group-hover:text-slate-600",
                  enginePickerOpen && "rotate-180 text-slate-700",
                )}
              />
            </button>
            <div className="h-7 w-px bg-slate-300/60" />
            <SearchIcon className="size-5 shrink-0 text-blue-600/80" />
            <input
              ref={searchInputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onSearchKey}
              placeholder={wt.searchPlaceholderFormat(
                selectedSearchEngine?.name ?? wt.searchEngineFallback,
              )}
              className="min-w-0 flex-1 bg-transparent text-lg font-medium text-slate-700 outline-none placeholder:text-slate-400"
            />
          </div>

          {enginePickerOpen && (
            <div
              role="menu"
              className="absolute left-2 top-[calc(100%+10px)] z-30 w-56 rounded-2xl border border-white/60 bg-white/55 p-1.5 text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_22px_70px_rgba(15,23,42,0.18)] backdrop-blur-2xl"
            >
              {engines.map((engine, index) => {
                const active = selectedEngine === index;
                return (
                  <button
                    key={engine.name}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    onClick={() => {
                      setSelectedEngine(index);
                      setEnginePickerOpen(false);
                      searchInputRef.current?.focus();
                    }}
                    className={cn(
                      "flex h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium transition-colors",
                      active
                        ? "bg-slate-950 text-white"
                        : "hover:bg-slate-900/5",
                    )}
                  >
                    <SearchEngineLogo engine={engine} className="size-7" />
                    <span className="min-w-0 flex-1 truncate">
                      {engine.name}
                    </span>
                    {active && <CheckIcon className="size-4" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div
          className={cn(
            "absolute right-12 top-8 flex items-center gap-2",
            compactDesktop && "right-6 top-7",
            tabletDesktop && "right-8",
            mobileDesktop && "right-5 top-6",
          )}
        >
          {editMode && (
            <>
              <button
                type="button"
                onClick={resetDesktopLayout}
                className="rounded-full border border-white/50 bg-white/34 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_8px_26px_rgba(15,23,42,0.10)] backdrop-blur-xl transition hover:bg-white/52"
              >
                {wt.resetLayout}
              </button>
              <button
                type="button"
                onClick={handleCreateFolder}
                className="rounded-full border border-white/50 bg-white/34 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_8px_26px_rgba(15,23,42,0.10)] backdrop-blur-xl transition hover:bg-white/52"
              >
                <Folder className="w-3 h-3 inline mr-1" />
                {wt.newFolder}
              </button>
              <button
                type="button"
                onClick={handleAddIcon}
                className="rounded-full border border-white/50 bg-white/34 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_8px_26px_rgba(15,23,42,0.10)] backdrop-blur-xl transition hover:bg-white/52"
              >
                <Plus className="w-3 h-3 inline mr-1" />
                {wt.addIconBtn}
              </button>
              <button
                type="button"
                onClick={handleAddWidget}
                className="rounded-full border border-white/50 bg-white/34 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_8px_26px_rgba(15,23,42,0.10)] backdrop-blur-xl transition hover:bg-white/52"
              >
                <PanelLeftIcon className="w-3 h-3 inline mr-1" />
                {wt.addWidgetBtn}
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setEditMode((value) => !value)}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium shadow-lg shadow-black/10 backdrop-blur-xl transition",
              editMode
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "border border-white/50 bg-white/34 text-slate-700 hover:bg-white/52",
            )}
          >
            {editMode ? wt.finishEditing : wt.editDesktop}
          </button>
        </div>

        {editMode && (
          <div
            className={cn(
              "absolute left-24 top-8 rounded-full bg-black/22 px-3 py-1.5 text-xs font-medium text-white shadow-lg backdrop-blur",
              compactDesktop && "left-20 top-24",
              tabletDesktop && "left-24",
              mobileDesktop && "left-16 right-4 text-center",
            )}
          >
            {wt.dragHint}
          </div>
        )}

        <div
          className={cn(
            "grid min-h-0 flex-1 grid-cols-[360px_minmax(420px,1fr)] gap-12 py-14",
            compactDesktop &&
              "grid-cols-1 gap-8 overflow-y-auto pb-8 pt-8 pr-1",
            tabletDesktop &&
              "grid-cols-[300px_minmax(360px,1fr)] gap-8 pb-32 pr-2",
            mobileDesktop && "gap-6 pb-6 pt-6",
          )}
        >
          <div
            className={cn(
              "flex flex-col items-center gap-8",
              compactDesktop && "gap-6",
              tabletDesktop && "justify-start",
            )}
          >
            <div className="text-center">
              <div className="flex overflow-hidden rounded-[22px] border border-white/55 bg-white/36 text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.78),0_18px_50px_rgba(15,23,42,0.13)] ring-1 ring-black/5 backdrop-blur-2xl">
                <div
                  className={cn(
                    "grid w-24 place-items-center border-r border-white/38 bg-white/40 px-4 py-3 text-center",
                    mobileDesktop && "w-20 px-3 py-2",
                  )}
                >
                  <div
                    className={cn(
                      "text-4xl font-semibold text-rose-500",
                      mobileDesktop && "text-3xl",
                    )}
                  >
                    {day}
                  </div>
                  <div className="text-sm font-medium text-rose-500">
                    {week}
                  </div>
                </div>
                <div
                  className={cn(
                    "flex min-w-40 flex-col justify-center bg-white/16 px-5 text-left",
                    mobileDesktop && "min-w-32 px-4",
                  )}
                >
                  <div
                    className={cn(
                      "text-lg font-semibold",
                      mobileDesktop && "text-base",
                    )}
                  >
                    {month}
                  </div>
                  <div className="text-sm text-slate-500">
                    {wt.aiBrowserDesktop}
                  </div>
                </div>
              </div>
            </div>

            <div className="relative">
              <div
                className={cn(
                  "grid grid-cols-2 gap-5 rounded-[26px] border border-white/42 bg-white/28 p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.68),0_22px_70px_rgba(15,23,42,0.15)] ring-1 ring-black/5 backdrop-blur-2xl",
                  mobileDesktop && "gap-3 rounded-[20px] p-4",
                )}
              >
                {desktopAppGroups.map((group) => (
                  <button
                    key={group.id}
                    type="button"
                    onClick={() =>
                      setOpenAppGroupId((current) =>
                        current === group.id ? null : group.id,
                      )
                    }
                    className="group flex min-w-0 flex-col items-center gap-2 rounded-2xl p-1 text-center transition hover:bg-white/24 focus:outline-none focus:ring-2 focus:ring-white/55"
                    title={`${group.title} · ${group.subtitle}`}
                  >
                    <span className="grid size-20 grid-cols-2 gap-1.5 rounded-[22px] border border-white/55 bg-white/42 p-2 shadow-[inset_0_1px_1px_rgba(255,255,255,0.76),0_12px_30px_rgba(15,23,42,0.12)] ring-1 ring-black/5 backdrop-blur-xl transition group-hover:bg-white/52">
                      {group.apps.slice(0, 4).map((app) => (
                        <DesktopAppLogo
                          key={app.url}
                          app={app}
                          className="size-full rounded-[12px] shadow-sm"
                          iconClassName="size-[82%]"
                        />
                      ))}
                    </span>
                    <span className="w-28 truncate text-sm font-semibold text-slate-700">
                      {group.title}
                    </span>
                  </button>
                ))}
              </div>
              <div className="mt-3 text-center text-sm font-medium text-white/88">
                {bt.commonCategories}
              </div>

              {desktopAppGroups.map((group) =>
                openAppGroupId === group.id ? (
                  <div
                    key={group.id}
                    className="absolute left-1/2 top-[calc(100%+10px)] z-20 w-72 -translate-x-1/2 rounded-[24px] border border-white/58 bg-white/46 p-3 text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.78),0_26px_80px_rgba(15,23,42,0.20)] ring-1 ring-black/5 backdrop-blur-2xl"
                  >
                    <div className="mb-2 flex items-center justify-between px-1">
                      <div>
                        <div className="text-sm font-semibold">
                          {group.title}
                        </div>
                        <div className="text-xs text-slate-500">
                          {group.subtitle}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setOpenAppGroupId(null)}
                        className="grid size-7 place-items-center rounded-full text-slate-400 transition hover:bg-slate-900/5 hover:text-slate-700"
                      >
                        <X className="size-4" />
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {group.apps.map((app) => (
                        <button
                          key={app.url}
                          type="button"
                          onClick={() => {
                            setOpenAppGroupId(null);
                            onOpen(app.url);
                          }}
                          className="group flex items-center gap-2 rounded-2xl border border-transparent p-2 text-left transition hover:border-white/45 hover:bg-white/34"
                          title={`${getAppName(app.name)} · ${getAppDesc(app.description)}`}
                        >
                          <DesktopAppLogo
                            app={app}
                            className="size-9 rounded-xl shadow-sm"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold">
                              {getAppName(app.name)}
                            </span>
                            <span className="block truncate text-[11px] text-slate-500">
                              {getAppDesc(app.description)}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null,
              )}
            </div>
          </div>

          <div className={cn("flex flex-col gap-9", compactDesktop && "gap-7")}>
            <section
              className={cn(
                "w-[360px] self-end rounded-[26px] border border-white/42 bg-white/24 p-4 text-slate-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.68),0_22px_70px_rgba(15,23,42,0.15)] ring-1 ring-black/5 backdrop-blur-2xl",
                compactDesktop && "w-full self-stretch",
                mobileDesktop && "rounded-[22px] p-3",
              )}
            >
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-800">
                    {bt.bookmarksLabel}
                  </div>
                  <div className="text-xs text-slate-500">
                    {bookmarks.length > 0
                      ? bt.bookmarkCount(bookmarks.length)
                      : history.length > 0
                        ? bt.recentVisits
                        : bt.commonEntries}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setActivePanel("add")}
                  className="grid size-8 place-items-center rounded-full border border-white/45 bg-white/30 text-slate-500 shadow-[inset_0_1px_1px_rgba(255,255,255,0.65)] transition hover:bg-white/48 hover:text-slate-800"
                  title={bt.addToDock}
                >
                  <Plus className="size-4" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {bookmarkPanelItems.map((item) => {
                  let fallbackIcon = "";
                  try {
                    fallbackIcon = `https://www.google.com/s2/favicons?domain=${
                      new URL(item.url).hostname
                    }&sz=64`;
                  } catch (e) {
                    swallow(e);
                  }
                  return (
                    <button
                      key={item.url}
                      type="button"
                      onClick={() => onOpen(item.url)}
                      className="group flex min-w-0 items-center gap-2 rounded-2xl border border-white/28 bg-white/20 p-2 text-left shadow-[inset_0_1px_1px_rgba(255,255,255,0.45)] transition hover:border-white/45 hover:bg-white/34"
                      title={item.title}
                    >
                      <span className="grid size-9 shrink-0 place-items-center overflow-hidden rounded-xl border border-white/55 bg-white/62 shadow-sm">
                        {item.favicon || fallbackIcon ? (
                          <img
                            src={item.favicon || fallbackIcon}
                            alt=""
                            className="size-[68%] object-contain"
                            onError={(event) => {
                              event.currentTarget.style.display = "none";
                            }}
                          />
                        ) : (
                          <BookOpenIcon className="size-4 text-slate-500" />
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-semibold text-slate-700">
                          {item.title}
                        </span>
                        <span className="block truncate text-[10px] text-slate-500">
                          {item.meta}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            {widgets.length > 0 && (
              <div className="grid grid-cols-2 gap-4">
                {widgets.map((widget) => {
                  const isDragging = dragState.draggedId === widget.id;
                  const isDropTarget = dragState.dropTargetId === widget.id;
                  return (
                    <div
                      key={widget.id}
                      className={cn(
                        "rounded-[24px] border border-white/44 bg-white/30 p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.70),0_18px_54px_rgba(15,23,42,0.13)] ring-1 ring-black/5 backdrop-blur-2xl transition-all",
                        isDragging && "opacity-40 scale-95",
                        isDropTarget && "ring-2 ring-blue-400",
                      )}
                      draggable
                      onDragStart={() => handleWidgetDragStart(widget.id)}
                      onDragOver={(e) => handleWidgetDragOver(e, widget.id)}
                      onDrop={() => handleWidgetDrop(widget.id)}
                      onDragEnd={handleDragEnd}
                      onContextMenu={(e) =>
                        handleContext(e, widget.id, "widget")
                      }
                    >
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-lg font-semibold text-slate-700">
                          {widget.title}
                        </span>
                        {editMode && (
                          <button
                            onClick={() => handleEdit(widget.id)}
                            className="text-slate-400 hover:text-slate-600"
                          >
                            <Edit3 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                      <div className="text-sm text-slate-500">
                        {widget.type === "notes" && (
                          <div className="space-y-2">
                            <div className="rounded-xl border border-white/45 bg-white/32 p-2 backdrop-blur-xl">
                              <p className="text-xs text-slate-500">
                                {bt.todoPlaceholder}
                              </p>
                            </div>
                          </div>
                        )}
                        {widget.type === "weather" && (
                          <div className="flex items-center gap-2">
                            <span className="text-2xl">☀️</span>
                            <span className="text-xl text-slate-600">26°C</span>
                          </div>
                        )}
                        {widget.type === "system" && (
                          <div className="space-y-2">
                            <div className="h-2 rounded-full bg-white/32">
                              <div className="h-full bg-blue-500 rounded-full w-[23%]" />
                            </div>
                            <div className="h-2 rounded-full bg-white/32">
                              <div className="h-full bg-violet-500 rounded-full w-[45%]" />
                            </div>
                          </div>
                        )}
                        {widget.type === "ai-tools" && (
                          <div className="grid grid-cols-3 gap-2">
                            {["ChatGPT", "Claude", "Gemini"].map((name) => (
                              <div
                                key={name}
                                className="rounded-xl border border-white/40 bg-white/34 p-2 text-center text-xs text-slate-600"
                              >
                                {name}
                              </div>
                            ))}
                          </div>
                        )}
                        {widget.type === "calendar" && (
                          <div className="text-center">
                            <div className="text-3xl font-semibold text-slate-700">
                              {day}
                            </div>
                            <div className="text-sm text-slate-500">
                              {month}
                            </div>
                          </div>
                        )}
                        {widget.type === "bookmarks" && (
                          <div className="space-y-1">
                            {["GitHub", "StackOverflow", "MDN"].map((name) => (
                              <div
                                key={name}
                                className="rounded-lg border border-white/40 bg-white/34 p-1 text-xs text-slate-600"
                              >
                                {name}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div>
              <div
                className={cn(
                  "grid grid-cols-4 gap-6",
                  compactDesktop && "grid-cols-3 gap-4",
                  mobileDesktop && "grid-cols-2 gap-4",
                )}
              >
                {standaloneLinks
                  .filter(
                    (link) =>
                      !searchFilter ||
                      link.name
                        .toLowerCase()
                        .includes(searchFilter.toLowerCase()),
                  )
                  .map((link) => {
                    const isDragging = dragState.draggedId === link.id;
                    const isDropTarget = dragState.dropTargetId === link.id;
                    return (
                      <div
                        key={link.id}
                        className={cn(
                          "group relative",
                          isDragging && "opacity-40 scale-95",
                        )}
                      >
                        <button
                          draggable
                          onClick={() => onOpen(link.url)}
                          className={cn(
                            "w-full flex flex-col items-center gap-2 p-3 rounded-2xl transition-all",
                            editMode
                              ? "hover:bg-white/10 cursor-move"
                              : "hover:bg-white/10",
                            isDropTarget && "ring-2 ring-blue-400",
                          )}
                          onDragStart={() => handleIconDragStart(link.id)}
                          onDragOver={(e) => handleIconDragOver(e, link.id)}
                          onDrop={() => handleIconDrop(link.id)}
                          onDragEnd={handleDragEnd}
                          onContextMenu={(e) =>
                            handleContext(e, link.id, "icon")
                          }
                        >
                          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-sky-400 to-violet-400 flex items-center justify-center shadow-lg">
                            <span className="text-white text-xl font-bold">
                              {link.name[0]}
                            </span>
                          </div>
                          <span className="text-xs text-white/80 truncate w-full text-center">
                            {link.name}
                          </span>
                        </button>
                        {editMode && (
                          <button
                            onClick={() => handleDelete(link.id)}
                            className="absolute -top-1 -right-1 w-5 h-5 bg-red-400 rounded-full flex items-center justify-center shadow-lg"
                          >
                            <X className="w-3 h-3 text-white" />
                          </button>
                        )}
                      </div>
                    );
                  })}

                {folderLinks.map(({ folder, links }) => {
                  const isOpen = folderOpenStates[folder.id];
                  const isDropTarget = dragState.dropTargetId === folder.id;
                  return (
                    <div key={folder.id} className="group relative">
                      <button
                        className={cn(
                          "w-full flex flex-col items-center gap-2 p-3 rounded-2xl transition-all hover:bg-white/10",
                          isDropTarget &&
                            "ring-2 ring-violet-400 bg-violet-400/20",
                        )}
                        onContextMenu={(e) =>
                          handleContext(e, folder.id, "folder")
                        }
                        onDragOver={(e) => {
                          e.preventDefault();
                          setDragState((prev) => ({
                            ...prev,
                            dropTargetId: folder.id,
                            dropPosition: null,
                          }));
                        }}
                        onDrop={() => handleDropOnFolder(folder.id)}
                        onDragLeave={() => {
                          setDragState((prev) =>
                            prev.dropTargetId === folder.id
                              ? { ...prev, dropTargetId: null }
                              : prev,
                          );
                        }}
                        onClick={() => toggleFolder(folder.id)}
                      >
                        <div className="w-14 h-14 rounded-2xl bg-white/20 flex items-center justify-center shadow-lg relative">
                          {isOpen ? (
                            <FolderOpen className="w-6 h-6 text-white" />
                          ) : (
                            <Folder className="w-6 h-6 text-white/60" />
                          )}
                          <span className="absolute -top-1 -right-1 w-4 h-4 bg-blue-400 rounded-full flex items-center justify-center text-[10px] text-white font-bold">
                            {links.length}
                          </span>
                        </div>
                        <span className="text-xs text-white/80 truncate w-full text-center">
                          {folder.name}
                        </span>
                      </button>
                      {isOpen && (
                        <div className="absolute z-10 mt-2 p-3 bg-white/90 backdrop-blur-xl border border-white/30 rounded-2xl shadow-2xl min-w-[200px]">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-sm font-medium text-slate-700">
                              {folder.name}
                            </span>
                            <button onClick={() => toggleFolder(folder.id)}>
                              <X className="w-4 h-4 text-slate-400 hover:text-slate-600" />
                            </button>
                          </div>
                          <div className="grid grid-cols-3 gap-2">
                            {links.map((link) => (
                              <button
                                key={link.id}
                                onClick={() => onOpen(link.url)}
                                className="flex flex-col items-center gap-1 p-2 rounded-xl bg-slate-100 hover:bg-slate-200 transition-colors"
                              >
                                <span className="text-lg font-bold text-slate-600">
                                  {link.name[0]}
                                </span>
                                <span className="text-[10px] text-slate-500 truncate w-full text-center">
                                  {link.name}
                                </span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        <div
          className={cn(
            "mx-auto mb-7 flex h-20 max-w-[780px] items-center gap-4 overflow-hidden rounded-[28px] border border-white/44 bg-white/32 px-4 py-2 shadow-[inset_0_1px_1px_rgba(255,255,255,0.74),0_26px_80px_rgba(15,23,42,0.18)] ring-1 ring-black/5 backdrop-blur-2xl",
            compactDesktop &&
              "absolute bottom-5 left-20 right-5 z-10 mx-0 mb-0 justify-start gap-3 overflow-x-auto rounded-[22px] px-4 py-3",
            tabletDesktop &&
              "left-24 right-8 justify-center gap-4 rounded-[26px] px-5",
            mobileDesktop && "bottom-4 left-16 right-4 gap-2 px-3",
          )}
        >
          {dockApps.map((app) => (
            <div key={app.url} className="group/dock relative shrink-0">
              <button
                key={app.url}
                type="button"
                draggable={editMode}
                onClick={() => {
                  if (!editMode) onOpen(app.url);
                }}
                onDragStart={(event) => startAppDrag(event, app.url)}
                onDragOver={(event) => {
                  if (editMode) event.preventDefault();
                }}
                onDrop={(event) => dropDockApp(event, app.url)}
                onDragEnd={() => setDraggingUrl(null)}
                className={cn(
                  "group grid size-14 place-items-center rounded-[18px] transition hover:-translate-y-0.5",
                  compactDesktop && "size-13 shrink-0 rounded-2xl",
                  tabletDesktop && "size-13",
                  mobileDesktop && "size-11 rounded-[15px]",
                  editMode &&
                    "cursor-move ring-2 ring-white/35 hover:translate-y-0",
                  draggingUrl === app.url && "scale-95 opacity-45",
                )}
                title={`${getAppName(app.name)} · ${getAppDesc(app.description)}`}
              >
                <DesktopAppLogo
                  app={app}
                  className="size-full rounded-[18px]"
                  iconClassName={cn(
                    "size-[60%]",
                    compactDesktop && "size-[58%]",
                    mobileDesktop && "size-[56%]",
                  )}
                />
              </button>
              {editMode && (
                <button
                  type="button"
                  onClick={() => removeAppFromDock(app.url)}
                  className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-rose-500 text-white shadow-lg transition hover:bg-rose-600"
                  title={bt.removeFromDock}
                >
                  <X className="size-3" />
                </button>
              )}
            </div>
          ))}
          {editMode && (
            <button
              type="button"
              onClick={() => setActivePanel("add")}
              className={cn(
                "grid size-14 shrink-0 place-items-center rounded-[18px] border border-dashed border-white/55 bg-white/26 text-slate-600 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_10px_28px_rgba(15,23,42,0.12)] backdrop-blur-xl transition hover:-translate-y-0.5 hover:bg-white/48",
                compactDesktop && "size-13 rounded-2xl",
                tabletDesktop && "size-13",
                mobileDesktop && "size-11 rounded-[15px]",
              )}
              title={bt.addToDock}
            >
              <Plus className="size-6" />
            </button>
          )}
        </div>
      </div>

      <ContextMenu
        state={contextMenu}
        onClose={() => setContextMenu((prev) => ({ ...prev, visible: false }))}
        onEdit={handleEdit}
        onDelete={handleDelete}
        onResize={handleResize}
      />

      {editWidgetState.visible && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-medium text-slate-800">
                {wt.editWidgetDialogTitle}
              </h3>
              <button
                onClick={() =>
                  setEditWidgetState({
                    visible: false,
                    widgetId: null,
                    title: "",
                    type: "notes",
                    size: "medium",
                  })
                }
              >
                <X className="w-5 h-5 text-slate-400 hover:text-slate-600" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-slate-600 mb-2">
                  {wt.editWidgetTitleLabel}
                </label>
                <input
                  type="text"
                  value={editWidgetState.title}
                  onChange={(e) =>
                    setEditWidgetState((prev) => ({
                      ...prev,
                      title: e.target.value,
                    }))
                  }
                  className="w-full bg-slate-100 border border-slate-200 rounded-xl px-4 py-2 text-slate-800 focus:outline-none focus:border-blue-400"
                  placeholder={wt.editWidgetTitlePlaceholder}
                />
              </div>
              <div>
                <label className="block text-sm text-slate-600 mb-2">
                  {wt.editWidgetTypeLabel}
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    {
                      type: "weather" as const,
                      label: wt.editWidgetTypeWeather,
                    },
                    {
                      type: "calendar" as const,
                      label: wt.editWidgetTypeCalendar,
                    },
                    { type: "notes" as const, label: wt.editWidgetTypeNotes },
                    { type: "system" as const, label: wt.editWidgetTypeSystem },
                    {
                      type: "ai-tools" as const,
                      label: wt.editWidgetTypeAiTools,
                    },
                    {
                      type: "bookmarks" as const,
                      label: wt.editWidgetTypeBookmarks,
                    },
                  ].map(({ type, label }) => (
                    <button
                      key={type}
                      onClick={() =>
                        setEditWidgetState((prev) => ({ ...prev, type }))
                      }
                      className={cn(
                        "flex flex-col items-center gap-1 p-2 rounded-xl border transition-all",
                        editWidgetState.type === type
                          ? "bg-blue-50 border-blue-400 text-blue-600"
                          : "bg-slate-50 border-slate-200 text-slate-500 hover:bg-slate-100",
                      )}
                    >
                      <span className="text-xs">{label}</span>
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={handleSaveWidget}
                className="w-full py-3 bg-blue-500 text-white rounded-xl hover:bg-blue-600 transition-colors font-medium"
              >
                {wt.editWidgetSave}
              </button>
            </div>
          </div>
        </div>
      )}

      {activePanel !== "home" && (
        <DesktopControlPanel
          panel={activePanel}
          onClose={() => setActivePanel("home")}
          onOpen={onOpen}
          dockAppUrls={dockAppUrls}
          onAddToDock={addAppToDock}
        />
      )}
    </div>
  );
}

function DesktopControlPanel({
  panel,
  onClose,
  onOpen,
  dockAppUrls,
  onAddToDock,
}: {
  panel: DesktopPanelId;
  onClose: () => void;
  onOpen: (url: string) => void;
  dockAppUrls: string[];
  onAddToDock: (url: string) => void;
}) {
  const { t } = useI18n();
  const wt = t.browser.webviewTab;
  const bt = t.browserHome;

  const title =
    panel === "theme"
      ? wt.panelTitleTheme
      : panel === "widgets"
        ? wt.panelTitleWidgets
        : panel === "wallpaper"
          ? wt.panelTitleWallpaper
          : panel === "games"
            ? wt.panelTitleGames
            : panel === "add"
              ? wt.panelTitleAddApp
              : wt.panelTitleDesktopSettings;

  const appNameMap = useMemo<Record<string, string>>(
    () => ({
      Doubao: bt.appNameDoubao,
      "Tongyi Qianwen": bt.appNameTongyiQianwen,
      "Wenxin Yiyan": bt.appNameWenxinYiyan,
      "Tencent Yuanbao": bt.appNameTencentYuanbao,
      Zhihu: bt.appNameZhihu,
    }),
    [bt],
  );

  const getAppName = useCallback(
    (name: string) => appNameMap[name] ?? name,
    [appNameMap],
  );

  return (
    <div className="absolute bottom-7 left-24 top-24 z-20 w-[360px] overflow-hidden rounded-[30px] border border-white/48 bg-white/34 text-slate-800 shadow-[inset_0_1px_1px_rgba(255,255,255,0.76),0_30px_90px_rgba(15,23,42,0.24)] ring-1 ring-black/5 backdrop-blur-2xl">
      <div className="flex items-center justify-between border-b border-white/38 bg-white/16 px-5 py-4">
        <div>
          <div className="text-base font-semibold">{title}</div>
          <div className="text-xs text-slate-500">{wt.panelSubtitle}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full border border-white/45 bg-white/30 px-3 py-1 text-xs font-medium text-slate-600 shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_8px_20px_rgba(15,23,42,0.10)] transition hover:bg-white/48"
        >
          {wt.panelClose}
        </button>
      </div>
      <div className="max-h-[calc(100%-72px)] overflow-y-auto p-5">
        {panel === "theme" && (
          <div className="space-y-4">
            {wt.themeNames.map((name, index) => (
              <button
                key={name}
                type="button"
                className={cn(
                  "flex w-full items-center gap-3 rounded-2xl border p-3 text-left shadow-[inset_0_1px_1px_rgba(255,255,255,0.58)] backdrop-blur-xl transition hover:bg-white/46",
                  index === 0
                    ? "border-blue-400/70 bg-white/48"
                    : "border-white/42 bg-white/24",
                )}
              >
                <span className="size-10 rounded-2xl bg-gradient-to-br from-slate-400 via-zinc-300 to-rose-300 shadow-inner" />
                <span>
                  <span className="block text-sm font-semibold">{name}</span>
                  <span className="block text-xs text-slate-500">
                    {wt.themeDescs[index]}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
        {panel === "widgets" && (
          <div className="space-y-3">
            {[CalendarDaysIcon, FileTextIcon, Clock3Icon, LayoutGridIcon].map(
              (Icon, index) => (
                <div
                  key={wt.widgetPanelNames[index]}
                  className="flex items-center gap-3 rounded-2xl border border-white/38 bg-white/24 p-3 shadow-[inset_0_1px_1px_rgba(255,255,255,0.58)] backdrop-blur-xl"
                >
                  <span className="grid size-10 place-items-center rounded-2xl bg-blue-500 text-white">
                    <Icon className="size-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold">
                      {wt.widgetPanelNames[index]}
                    </div>
                    <div className="truncate text-xs text-slate-500">
                      {wt.widgetPanelDescs[index]}
                    </div>
                  </div>
                  <span className="rounded-full bg-emerald-500/14 px-2 py-1 text-[10px] font-medium text-emerald-700">
                    {wt.widgetEnabled}
                  </span>
                </div>
              ),
            )}
          </div>
        )}
        {panel === "wallpaper" && (
          <div className="grid grid-cols-2 gap-3">
            {[
              "from-slate-400 via-zinc-300 to-rose-300",
              "from-sky-300 via-indigo-300 to-slate-500",
              "from-emerald-300 via-teal-400 to-slate-600",
              "from-stone-500 via-neutral-400 to-orange-200",
            ].map((gradient, index) => (
              <button
                key={gradient}
                type="button"
                className={cn(
                  "h-24 rounded-3xl border border-white/40 bg-gradient-to-br shadow-[inset_0_1px_2px_rgba(255,255,255,0.42),0_10px_28px_rgba(15,23,42,0.12)]",
                  gradient,
                )}
                title={wt.wallpaperTitle(index + 1)}
              />
            ))}
          </div>
        )}
        {panel === "games" && (
          <div className="space-y-3">
            {wt.gameNames.map((name, index) => {
              const Icon = index === 0 ? Gamepad2Icon : SparklesIcon;
              return (
                <button
                  key={name}
                  type="button"
                  className="flex w-full items-center gap-3 rounded-2xl border border-white/38 bg-white/24 p-3 text-left shadow-[inset_0_1px_1px_rgba(255,255,255,0.58)] backdrop-blur-xl transition hover:bg-white/46"
                  onClick={() => {
                    if (name === wt.gameNames[0])
                      onOpen("https://www.bilibili.com/");
                  }}
                >
                  <span className="grid size-10 place-items-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 text-white">
                    <Icon className="size-5" />
                  </span>
                  <span className="text-sm font-semibold">{name}</span>
                </button>
              );
            })}
          </div>
        )}
        {panel === "add" && (
          <div className="space-y-3">
            {AI_DESKTOP_APPS.map((app) => {
              const inDock = dockAppUrls.includes(app.url);
              return (
                <div
                  key={app.url}
                  className="flex w-full items-center gap-3 rounded-2xl border border-white/38 bg-white/24 p-3 text-left shadow-[inset_0_1px_1px_rgba(255,255,255,0.58)] backdrop-blur-xl transition hover:bg-white/46"
                >
                  <button
                    type="button"
                    onClick={() => onOpen(app.url)}
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  >
                    <DesktopAppLogo app={app} className="size-10 rounded-2xl" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold">
                        {getAppName(app.name)}
                      </span>
                      <span className="block truncate text-xs text-slate-500">
                        {app.url}
                      </span>
                    </span>
                  </button>
                  <button
                    type="button"
                    disabled={inDock}
                    onClick={() => onAddToDock(app.url)}
                    className={cn(
                      "shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold transition",
                      inDock
                        ? "border border-white/30 bg-white/18 text-slate-400"
                        : "bg-slate-950/88 text-white shadow-lg shadow-black/15 hover:bg-slate-700",
                    )}
                  >
                    {inDock ? bt.alreadyInDock : bt.add}
                  </button>
                </div>
              );
            })}
          </div>
        )}
        {panel === "settings" && (
          <div className="space-y-3">
            {wt.settingNames.map((name, index) => (
              <div
                key={name}
                className="rounded-2xl border border-white/38 bg-white/24 p-3 shadow-[inset_0_1px_1px_rgba(255,255,255,0.58)] backdrop-blur-xl"
              >
                <div className="text-sm font-semibold">{name}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {wt.settingDescs[index]}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
