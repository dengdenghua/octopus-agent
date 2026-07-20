import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindowIcon,
  ArchiveIcon,
  BrainIcon,
  ChevronRightIcon,
  DatabaseIcon,
  ExternalLinkIcon,
  EyeIcon,
  FileArchiveIcon,
  FileImageIcon,
  FileSearchIcon,
  FileTextIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderPlusIcon,
  Grid3X3Icon,
  HardDriveIcon,
  ImageIcon,
  LayoutListIcon,
  ListFilterIcon,
  LockKeyholeIcon,
  MessageSquarePlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ServerIcon,
  ShieldCheckIcon,
  SlidersHorizontalIcon,
  SparklesIcon,
  TablePropertiesIcon,
  type LucideIcon,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import {
  createNASIndexJob,
  createNASSource,
  deleteNASSource,
  getNASBaseURL,
  getNASManifest,
  getNASPolicy,
  listNASSources,
  searchNAS,
  startNASService,
  updateNASPolicy,
  type NASManifest,
  type NASPolicy,
  type NASSearchHit,
  type NASSource,
} from "@/core/storage/api";
import { basename, isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";

type LibraryKey =
  | "overview"
  | "apps"
  | "docs"
  | "images"
  | "computer"
  | "sources";

interface TopicItem {
  title: string;
  subtitle: string;
  count: string;
  status: string;
  icon: LucideIcon;
  tone: string;
  covers: string[];
}

interface AppItem {
  name: string;
  type: string;
  path: string;
  status: string;
  icon: LucideIcon;
  tone: string;
}

interface DiskItem {
  name: string;
  path: string;
  type: string;
  size: string;
  icon: LucideIcon;
  active?: boolean;
}

interface FileItem {
  name: string;
  path: string;
  kind: string;
  updated: string;
  size: string;
  icon: LucideIcon;
  tone: string;
}

const DEFAULT_QUERY = "找我上周写的嵌入式技术笔记";

const LIBRARIES: Array<{
  key: LibraryKey;
  label: string;
  detail: string;
  icon: LucideIcon;
}> = [
  { key: "overview", label: "全部", detail: "本地数据库", icon: DatabaseIcon },
  { key: "apps", label: "应用", detail: "软件与动作", icon: AppWindowIcon },
  {
    key: "docs",
    label: "文档",
    detail: "主题 / 来源 / 最近",
    icon: FileTextIcon,
  },
  {
    key: "images",
    label: "图片",
    detail: "图库 / 主题 / 来源",
    icon: FileImageIcon,
  },
  { key: "computer", label: "本机", detail: "本地磁盘", icon: HardDriveIcon },
  {
    key: "sources",
    label: "授权目录",
    detail: "扫描范围",
    icon: FolderPlusIcon,
  },
];

const LIBRARY_KEYS = new Set<LibraryKey>(LIBRARIES.map((item) => item.key));

function isLibraryKey(value: string | null): value is LibraryKey {
  return value !== null && LIBRARY_KEYS.has(value as LibraryKey);
}

const DEFAULT_POLICY: NASPolicy = {
  mode: "efficiency",
  allow_cloud_answering: true,
  allow_snippet_export: true,
  max_exported_snippets: 8,
  max_snippet_chars: 1200,
  redact_file_paths_for_cloud: true,
};

const delay = (ms: number) =>
  new Promise((resolve) => window.setTimeout(resolve, ms));

const DOC_TOPICS: TopicItem[] = [
  topic(
    "全部文档",
    "PDF、Word、PPT、表格、Markdown 与代码",
    "1,284",
    "索引持续构建中",
    FileTextIcon,
    "blue",
    ["PDF", "DOC", "MD"],
  ),
  topic(
    "文档来源",
    "按授权目录和项目来源归类",
    "32",
    "已同步",
    FolderOpenIcon,
    "green",
    ["工作", "项目", "下载"],
  ),
  topic(
    "文档主题",
    "自动聚类合同、技术笔记、调研资料",
    "18",
    "主题 AI 构建中",
    BrainIcon,
    "violet",
    ["合同", "技术", "调研"],
  ),
  topic(
    "最近文件",
    "近期打开、修改、搜索命中的文档",
    "96",
    "最近更新",
    FileSearchIcon,
    "zinc",
    ["今天", "7天", "30天"],
  ),
];

const IMAGE_TOPICS: TopicItem[] = [
  topic(
    "全部图片",
    "照片、截图、设计物料与图片内文字",
    "8,426",
    "图片智能搜索",
    FileImageIcon,
    "green",
    ["JPG", "PNG", "WEBP"],
  ),
  topic(
    "图片主题",
    "人物、地点、节日、票据、屏幕截图",
    "41",
    "持续构建中",
    SparklesIcon,
    "violet",
    ["人物", "地点", "主题"],
  ),
  topic(
    "图片来源",
    "按目录、应用、项目来源自动归档",
    "24",
    "已同步",
    FolderOpenIcon,
    "blue",
    ["桌面", "下载", "微信"],
  ),
  topic(
    "截图 OCR",
    "截图里的文字和界面内容可被搜索",
    "1,230",
    "OCR 队列",
    ImageIcon,
    "amber",
    ["白板", "界面", "表格"],
  ),
];

const APP_ITEMS: AppItem[] = [
  app(
    "Finder",
    "系统应用",
    "/System/Applications/Finder.app",
    "已注册",
    FolderOpenIcon,
    "blue",
  ),
  app(
    "Preview",
    "图片 / PDF",
    "/System/Applications/Preview.app",
    "已注册",
    ImageIcon,
    "green",
  ),
  app(
    "Office",
    "文档表格",
    "/Applications",
    "待扫描",
    FileArchiveIcon,
    "amber",
  ),
  app(
    "Browser",
    "网页资料",
    "/Applications",
    "已注册",
    AppWindowIcon,
    "violet",
  ),
  app(
    "Terminal",
    "系统工具",
    "/System/Applications/Utilities",
    "可调用",
    ServerIcon,
    "zinc",
  ),
  app("Downloads", "下载管理", "~/Downloads", "文件夹", ArchiveIcon, "blue"),
];

const DOC_FILES: FileItem[] = [
  file(
    "AI 眼镜市场调研.md",
    "~/Documents/Research/AI Glasses.md",
    "Markdown",
    "今天 14:21",
    "128 KB",
    FileTextIcon,
    "blue",
  ),
  file(
    "2026 产品路线图.pptx",
    "~/Documents/Product/Roadmap.pptx",
    "演示文稿",
    "昨天 18:09",
    "18.4 MB",
    TablePropertiesIcon,
    "amber",
  ),
  file(
    "供应商合同扫描件.pdf",
    "~/Documents/Contracts/Vendor.pdf",
    "PDF",
    "6月12日",
    "3.2 MB",
    FileArchiveIcon,
    "rose",
  ),
  file(
    "本地小模型部署笔记.md",
    "~/Public/octopus/local-models.md",
    "Markdown",
    "6月10日",
    "42 KB",
    BrainIcon,
    "violet",
  ),
  file(
    "NAS 权限清单.xlsx",
    "~/Documents/NAS/Permissions.xlsx",
    "表格",
    "6月08日",
    "812 KB",
    FileSearchIcon,
    "green",
  ),
];

const IMAGE_FILES: FileItem[] = [
  file(
    "aoi-front-transparent.png",
    "~/Pictures/Agents/aoi-front.png",
    "人物立绘",
    "今天 11:42",
    "4.8 MB",
    FileImageIcon,
    "green",
  ),
  file(
    "会议白板 OCR.jpg",
    "~/Pictures/Whiteboard/meeting.jpg",
    "照片 / OCR",
    "昨天 16:18",
    "2.1 MB",
    ImageIcon,
    "blue",
  ),
  file(
    "产品截图-工作台.webp",
    "~/Pictures/Screenshots/workspace.webp",
    "界面截图",
    "6月12日",
    "980 KB",
    FileImageIcon,
    "violet",
  ),
  file(
    "票据-差旅.png",
    "~/Pictures/Receipts/travel.png",
    "票据",
    "6月09日",
    "1.4 MB",
    FileSearchIcon,
    "amber",
  ),
];

function topic(
  title: string,
  subtitle: string,
  count: string,
  status: string,
  icon: LucideIcon,
  tone: string,
  covers: string[],
): TopicItem {
  return { title, subtitle, count, status, icon, tone, covers };
}

function app(
  name: string,
  type: string,
  path: string,
  status: string,
  icon: LucideIcon,
  tone: string,
): AppItem {
  return { name, type, path, status, icon, tone };
}

function disk(
  name: string,
  path: string,
  type: string,
  size: string,
  icon: LucideIcon,
  active = false,
): DiskItem {
  return { name, path, type, size, icon, active };
}

function file(
  name: string,
  path: string,
  kind: string,
  updated: string,
  size: string,
  icon: LucideIcon,
  tone: string,
): FileItem {
  return { name, path, kind, updated, size, icon, tone };
}

export default function StoragePage() {
  const [searchParams] = useSearchParams();
  const [manifest, setManifest] = useState<NASManifest | null>(null);
  const [policy, setPolicy] = useState<NASPolicy>(DEFAULT_POLICY);
  const [sources, setSources] = useState<NASSource[]>([]);
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [hits, setHits] = useState<NASSearchHit[]>([]);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);
  const [hasSearchResult, setHasSearchResult] = useState(false);
  const [isPickingFolder, setIsPickingFolder] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const didAutoStartRef = useRef(false);

  const libraryParam = searchParams.get("library");
  const activeLibrary = isLibraryKey(libraryParam) ? libraryParam : "computer";
  const activeMeta = LIBRARIES.find((item) => item.key === activeLibrary)!;

  const stats = useMemo(() => {
    const files = sources.reduce((sum, source) => sum + source.file_count, 0);
    const chunks = sources.reduce((sum, source) => sum + source.chunk_count, 0);
    return { files, chunks, sources: sources.length };
  }, [sources]);

  const refreshNAS = useCallback(async () => {
    try {
      setServiceError(null);
      const [nextManifest, nextPolicy, nextSources] = await Promise.all([
        getNASManifest(),
        getNASPolicy(),
        listNASSources(),
      ]);
      setManifest(nextManifest);
      setPolicy(nextPolicy);
      setSources(nextSources);
      return true;
    } catch (error) {
      setManifest(null);
      setSources([]);
      setServiceError(error instanceof Error ? error.message : String(error));
      return false;
    }
  }, []);

  const ensureNASService = useCallback(async () => {
    const startResult = await startNASService();
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (await refreshNAS()) return true;
      await delay(500);
    }
    if (startResult.status === "not_found") {
      setServiceError(
        "未找到 octopus-storage，请安装本地知识库服务，或设置 OCTOPUS_STORAGE_CMD 后重试。",
      );
      return false;
    }
    if (startResult.status === "error") {
      setServiceError("本地知识库服务启动失败，请检查后端日志后重试。");
      return false;
    }
    setServiceError(`本地知识库服务仍未连接：${getNASBaseURL()}`);
    return false;
  }, [refreshNAS]);

  useEffect(() => {
    const init = async () => {
      if (await refreshNAS()) return;
      if (didAutoStartRef.current) return;
      didAutoStartRef.current = true;
      await ensureNASService();
    };
    void init();
  }, [ensureNASService, refreshNAS]);

  useEffect(() => {
    const reconnect = () => {
      if (document.visibilityState === "visible") {
        void refreshNAS();
      }
    };
    window.addEventListener("focus", reconnect);
    document.addEventListener("visibilitychange", reconnect);
    return () => {
      window.removeEventListener("focus", reconnect);
      document.removeEventListener("visibilitychange", reconnect);
    };
  }, [refreshNAS]);

  const addSource = async (path: string) => {
    const cleanPath = path.trim();
    if (!cleanPath) return;
    await createNASSource(cleanPath);
    await refreshNAS();
  };

  const pickFolder = async () => {
    setIsPickingFolder(true);
    try {
      if (window.octopus?.dialog?.open) {
        const result = await window.octopus.dialog.open({
          properties: ["openDirectory"],
        });
        const selected = result.filePaths[0];
        if (!result.canceled && selected) {
          await addSource(selected);
          return;
        }
      }
      folderInputRef.current?.click();
    } catch (err) {
      setServiceError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsPickingFolder(false);
    }
  };

  const onFolderInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    event.target.value = "";
    setServiceError(
      "浏览器目录选择无法提供安全的本机绝对路径，请在桌面壳中添加文件夹。",
    );
  };

  const reconnectNAS = async () => {
    if (isReconnecting) return;
    setIsReconnecting(true);
    setServiceError(null);
    try {
      await ensureNASService();
    } catch (error) {
      if (!(await refreshNAS())) {
        setServiceError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setIsReconnecting(false);
    }
  };

  const removeSource = async (id: string) => {
    await deleteNASSource(id);
    await refreshNAS();
  };

  const startIndexing = async () => {
    setIsIndexing(true);
    try {
      await createNASIndexJob();
      await refreshNAS();
    } catch (error) {
      setServiceError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsIndexing(false);
    }
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setIsSearching(true);
    setServiceError(null);
    try {
      const result = await searchNAS(query.trim());
      setHits(result.hits);
      setSearchMessage(result.message);
      setHasSearchResult(true);
    } catch (error) {
      setHits([]);
      setSearchMessage(null);
      setHasSearchResult(false);
      setServiceError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsSearching(false);
    }
  };

  const clearSearchResult = () => {
    setHasSearchResult(false);
    setHits([]);
    setSearchMessage(null);
  };

  const togglePrivacy = async () => {
    const mode = policy.mode === "privacy" ? "efficiency" : "privacy";
    const next = await updateNASPolicy({ ...policy, mode });
    setPolicy(next);
  };

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="overflow-hidden">
        <div className="flex size-full overflow-hidden p-2">
          <section className="workspace-panel flex min-h-0 flex-1 overflow-hidden rounded-lg border border-border-default bg-white">
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-white">
              {serviceError && (
                <div className="flex items-center justify-between gap-3 border-b border-amber-300/70 bg-amber-50 px-4 py-2 text-xs text-amber-900">
                  <span className="min-w-0 truncate">
                    本地知识库服务未连接：{getNASBaseURL()}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0 rounded-md border-amber-300 bg-white px-3 text-amber-900 hover:bg-amber-100"
                    onClick={() => void reconnectNAS()}
                    disabled={isReconnecting}
                  >
                    <RefreshCwIcon
                      className={cn(
                        "size-3.5",
                        isReconnecting && "animate-spin",
                      )}
                    />
                    {isReconnecting ? "连接中" : "重新连接"}
                  </Button>
                </div>
              )}

              {activeLibrary !== "sources" && (
                <div className="flex shrink-0 items-center justify-end gap-1.5 border-b border-black/5 bg-[#f5f5f5] px-3 py-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-8 rounded-md bg-white px-2 text-xs shadow-[var(--shadow-xs)]"
                    onClick={pickFolder}
                    disabled={isPickingFolder}
                  >
                    <FolderPlusIcon className="size-3.5" />
                    授权
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-8 rounded-md bg-white px-2 text-xs shadow-[var(--shadow-xs)]"
                    onClick={startIndexing}
                    disabled={isIndexing || !manifest}
                  >
                    <RefreshCwIcon
                      className={cn("size-3.5", isIndexing && "animate-spin")}
                    />
                    扫描
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 rounded-md px-2 text-xs text-muted-foreground"
                    onClick={() => void togglePrivacy()}
                  >
                    {policy.mode === "privacy" ? (
                      <LockKeyholeIcon className="size-3.5" />
                    ) : (
                      <ServerIcon className="size-3.5" />
                    )}
                    {policy.mode === "privacy" ? "隐私" : "效率"}
                  </Button>
                  <span className="ml-1 flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                    <span
                      className={cn(
                        "size-1.5 rounded-full",
                        manifest ? "bg-emerald-500" : "bg-amber-500",
                      )}
                    />
                    <span>{manifest ? "在线" : "离线"}</span>
                  </span>
                </div>
              )}

              {activeLibrary === "sources" ? (
                <SourcesView
                  sources={sources}
                  stats={stats}
                  manifest={manifest}
                  serviceError={serviceError}
                  isPickingFolder={isPickingFolder}
                  isReconnecting={isReconnecting}
                  onPickFolder={pickFolder}
                  onReconnect={() => void reconnectNAS()}
                  onRemoveSource={removeSource}
                  folderInputRef={folderInputRef}
                  onFolderInputChange={onFolderInputChange}
                />
              ) : hasSearchResult ? (
                <SearchResultsView
                  hits={hits}
                  query={query}
                  setQuery={setQuery}
                  runSearch={runSearch}
                  isSearching={isSearching}
                  manifest={manifest}
                  message={searchMessage}
                  libraryLabel={activeMeta.label}
                  onBack={clearSearchResult}
                />
              ) : activeLibrary === "computer" ? (
                <LocalDiskView
                  query={query}
                  setQuery={setQuery}
                  runSearch={runSearch}
                  isSearching={isSearching}
                  manifest={manifest}
                />
              ) : activeLibrary === "apps" ? (
                <AppsView
                  query={query}
                  setQuery={setQuery}
                  runSearch={runSearch}
                  isSearching={isSearching}
                  manifest={manifest}
                />
              ) : (
                <TopicCenterView
                  activeLibrary={activeLibrary}
                  activeMeta={activeMeta}
                  query={query}
                  setQuery={setQuery}
                  runSearch={runSearch}
                  isSearching={isSearching}
                  manifest={manifest}
                  searchMessage={searchMessage}
                />
              )}
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function ToolbarSearch({
  label,
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
}: {
  label: string;
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
}) {
  return (
    <div className="flex min-w-0 max-w-full flex-1 items-center gap-1 rounded-md border border-black/10 bg-white px-2 shadow-[var(--shadow-xs)] sm:min-w-[300px]">
      <div className="flex min-w-0 flex-1 items-center">
        <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
        <span className="ml-2 hidden shrink-0 text-xs text-muted-foreground xl:inline">
          {label}
        </span>
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") runSearch();
          }}
          placeholder="文件名、正文、OCR、路径或应用"
          className="h-8 min-w-36 border-0 bg-transparent px-1 text-sm shadow-none focus-visible:ring-0"
        />
      </div>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-label="搜索"
        className="h-7 shrink-0 rounded-md px-2"
        onClick={runSearch}
        disabled={isSearching || !manifest}
      >
        {isSearching ? (
          <RefreshCwIcon className="size-3.5 animate-spin" />
        ) : (
          <SearchIcon className="size-3.5" />
        )}
      </Button>
    </div>
  );
}

function TopicCenterView({
  activeLibrary,
  activeMeta,
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
  searchMessage,
}: {
  activeLibrary: LibraryKey;
  activeMeta: (typeof LIBRARIES)[number];
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
  searchMessage: string | null;
}) {
  if (activeLibrary === "docs") {
    return (
      <DocumentLibraryView
        query={query}
        setQuery={setQuery}
        runSearch={runSearch}
        isSearching={isSearching}
        manifest={manifest}
        searchMessage={searchMessage}
      />
    );
  }

  if (activeLibrary === "images") {
    return (
      <ImageLibraryView
        query={query}
        setQuery={setQuery}
        runSearch={runSearch}
        isSearching={isSearching}
        manifest={manifest}
      />
    );
  }

  const topics = [...DOC_TOPICS.slice(0, 2), ...IMAGE_TOPICS.slice(0, 2)];
  const tabs = ["全部本地", "文档", "图片", "最近"];
  const recentItems = [...DOC_FILES.slice(0, 3), ...IMAGE_FILES.slice(0, 2)];

  return (
    <>
      <div className="flex h-[52px] shrink-0 items-center justify-between gap-4 border-b border-black/5 bg-[#f7f7f7] px-4">
        <div className="flex items-center gap-6">
          {tabs.map((tab, index) => (
            <button
              key={tab}
              type="button"
              className={cn(
                "text-sm transition-colors",
                index === 0
                  ? "font-semibold text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <ToolbarSearch
            label={`在 ${activeMeta.label} 中搜索：`}
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label="搜索范围筛选"
            className="rounded-full"
          >
            <ListFilterIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="网格视图"
            className="rounded-full"
          >
            <Grid3X3Icon className="size-4" />
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(420px,1fr)_320px] overflow-hidden">
        <aside className="min-h-0 overflow-y-auto border-r border-black/5 bg-[#f7f7f7] p-3">
          <div className="mb-3 rounded-lg bg-white p-3 shadow-[var(--shadow-xs)] ring-1 ring-black/5">
            <div className="text-sm font-semibold">索引持续构建中</div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              新增文件会自动进入主题、来源和全文搜索。
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-black/5">
              <div className="h-full w-2/3 rounded-full bg-black" />
            </div>
          </div>
          <div className="space-y-1">
            {topics.map((topicItem, index) => (
              <TopicNavRow
                key={topicItem.title}
                topic={topicItem}
                active={index === 0}
              />
            ))}
          </div>
        </aside>

        <main className="min-h-0 overflow-y-auto bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold">{tabs[0]}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {searchMessage ||
                  "聚合文档、图片、应用和本机目录，本地索引优先。"}
              </div>
            </div>
            <Badge
              variant="outline"
              className="rounded-full border-black/10 bg-white"
            >
              本地数据库
            </Badge>
          </div>
          <div className="grid gap-3 2xl:grid-cols-2">
            {recentItems.map((item) => (
              <FileCard key={item.path} item={item} />
            ))}
          </div>
        </main>

        <aside className="min-h-0 overflow-y-auto border-l border-black/5 bg-[#fbfbfb] p-4">
          <PreviewPanel
            title="本地小脑索引"
            subtitle="文件解析、OCR、向量化在本机执行；问答可按隐私策略切换。"
            item={DOC_FILES[0]!}
          />
        </aside>
      </div>
    </>
  );
}

function DocumentLibraryView({
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
  searchMessage,
}: {
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
  searchMessage: string | null;
}) {
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-black/5 bg-[#f5f5f5] px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">文档</div>
          <div className="truncate text-xs text-muted-foreground">
            {DOC_FILES.length} 项 · 全文、表格、OCR 与来源路径检索
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label="搜索文档："
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label="筛选"
            className="size-8 rounded-md"
          >
            <ListFilterIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="列表视图"
            className="size-8 rounded-md"
          >
            <LayoutListIcon className="size-4" />
          </Button>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden bg-white">
        <div className="flex h-12 items-center justify-between border-b border-black/5 px-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">全部文档</div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              {searchMessage || "2026年6月 · 本机索引优先"}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge
              variant="outline"
              className="rounded-md border-black/10 bg-white"
            >
              最近
            </Badge>
            <Badge
              variant="outline"
              className="rounded-md border-black/10 bg-white"
            >
              本机文档
            </Badge>
          </div>
        </div>
        <div className="grid grid-cols-[minmax(240px,1fr)_minmax(180px,280px)_92px_120px_104px] items-center gap-3 border-b border-black/5 bg-[#fbfbfb] px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>名称</span>
          <span>位置</span>
          <span>大小</span>
          <span className="text-right">修改日期</span>
          <span className="text-right">动作</span>
        </div>
        <div className="min-h-0 overflow-y-auto">
          {DOC_FILES.map((item) => (
            <FileManagerRow key={item.path} item={item} />
          ))}
        </div>
        <div className="border-t border-black/5 bg-[#fbfbfb] px-3 py-2 text-xs text-muted-foreground">
          文档只进入本机索引；引用到任务前不会自动进入上下文。
        </div>
      </main>
    </>
  );
}

function ImageLibraryView({
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
}: {
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
}) {
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-black/5 bg-[#f5f5f5] px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">图片</div>
          <div className="truncate text-xs text-muted-foreground">
            {IMAGE_FILES.length} 项 · OCR、地点、人物与截图统一检索
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label="搜索图片："
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label="筛选"
            className="size-8 rounded-md"
          >
            <ListFilterIcon className="size-4" />
          </Button>
          <Badge
            variant="outline"
            className="h-8 rounded-md border-black/10 bg-white px-2.5 text-xs"
          >
            所有图片
          </Badge>
          <Button
            size="sm"
            variant="ghost"
            aria-label="网格视图"
            className="size-8 rounded-md"
          >
            <Grid3X3Icon className="size-4" />
          </Button>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-y-auto bg-[#f7f7f7] px-4 py-4 lg:px-6">
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            全部 {IMAGE_FILES.length}
          </Badge>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            已 OCR
          </Badge>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            本机图库
          </Badge>
        </div>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
          {IMAGE_FILES.map((item) => (
            <ImageAssetTile key={item.path} item={item} />
          ))}
        </div>
      </main>
    </>
  );
}

function TopicNavRow({
  topic: item,
  active,
}: {
  topic: TopicItem;
  active: boolean;
}) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
        active ? "bg-white shadow-[var(--shadow-xs)] ring-1 ring-black/5" : "hover:bg-white/70",
      )}
    >
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-lg",
          toneClass(item.tone),
        )}
      >
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{item.title}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {item.count} 项 · {item.status}
        </span>
      </span>
      <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
    </button>
  );
}

function FileCard({ item }: { item: FileItem }) {
  const Icon = item.icon;
  return (
    <div className="group flex min-h-20 items-center gap-3 rounded-lg border border-black/5 bg-white p-3 text-left shadow-[var(--shadow-xs)] transition-colors hover:border-black/10 hover:bg-[#fbfbfb]">
      <div
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-lg",
          toneClass(item.tone),
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{item.name}</div>
        <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <span className="truncate">{item.path}</span>
          <span className="shrink-0">·</span>
          <span className="shrink-0">{item.updated}</span>
        </div>
      </div>
      <div className="hidden shrink-0 text-right text-xs text-muted-foreground xl:block">
        <div>{item.kind}</div>
        <div className="mt-1">{item.size}</div>
      </div>
      <QuickFileActions compact />
    </div>
  );
}

function FileManagerRow({ item }: { item: FileItem }) {
  const Icon = item.icon;
  return (
    <div className="grid w-full grid-cols-[minmax(260px,1fr)_minmax(180px,260px)_100px_148px_112px] items-center gap-4 border-b border-black/[0.04] px-4 py-3 text-left last:border-b-0 hover:bg-black/[0.025]">
      <span className="flex min-w-0 items-center gap-3">
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg",
            toneClass(item.tone),
          )}
        >
          <Icon className="size-4" />
        </span>
        <span className="truncate text-sm font-medium">{item.name}</span>
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {item.path}
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {item.size}
      </span>
      <span className="truncate text-right text-xs text-muted-foreground">
        {item.updated}
      </span>
      <QuickFileActions />
    </div>
  );
}

function ImageAssetTile({ item }: { item: FileItem }) {
  const Icon = item.icon;
  return (
    <div className="group min-w-0 overflow-hidden rounded-lg border border-black/5 bg-white text-left shadow-[var(--shadow-xs)] transition-colors hover:border-black/10 hover:bg-[#fcfcfc]">
      <span className="flex aspect-[4/3] w-full items-center justify-center bg-[#f7f7f7]">
        <span
          className={cn(
            "flex size-16 items-center justify-center rounded-lg",
            toneClass(item.tone),
          )}
        >
          <Icon className="size-7" />
        </span>
      </span>
      <span className="mt-3 block truncate px-3 text-sm font-medium">
        {item.name}
      </span>
      <span className="block truncate px-3 text-xs text-muted-foreground">
        {item.updated} · {item.size}
      </span>
      <div className="mt-3 flex items-center justify-between gap-2 px-3 pb-3">
        <span className="rounded-md bg-black/[0.04] px-2 py-1 text-xs text-muted-foreground">
          已 OCR
        </span>
        <QuickFileActions compact />
      </div>
    </div>
  );
}

function QuickFileActions({ compact = false }: { compact?: boolean }) {
  const buttons = [
    { label: "预览", icon: EyeIcon },
    { label: "引用到任务", icon: MessageSquarePlusIcon },
    { label: "所在位置", icon: ExternalLinkIcon },
  ];
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-end gap-1",
        compact && "gap-0.5",
      )}
    >
      {buttons.map((action) => {
        const Icon = action.icon;
        return (
          <button
            key={action.label}
            type="button"
            title={action.label}
            aria-label={action.label}
            className={cn(
              "grid place-items-center rounded-md text-muted-foreground transition-colors hover:bg-black/[0.06] hover:text-foreground",
              compact ? "size-7" : "size-8",
            )}
          >
            <Icon className={compact ? "size-3.5" : "size-4"} />
          </button>
        );
      })}
    </span>
  );
}

function PreviewPanel({
  title,
  subtitle,
  item,
}: {
  title: string;
  subtitle: string;
  item: FileItem;
}) {
  const Icon = item.icon;
  return (
    <div className="flex min-h-full flex-col">
      <div className="rounded-lg bg-white p-4 shadow-[var(--shadow-xs)] ring-1 ring-black/5">
        <div className="text-sm font-semibold">{title}</div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {subtitle}
        </p>
        <div className="mt-4 rounded-lg bg-[#f7f7f7] p-4">
          <div
            className={cn(
              "mx-auto flex size-20 items-center justify-center rounded-lg",
              toneClass(item.tone),
            )}
          >
            <Icon className="size-9" />
          </div>
          <div className="mt-4 text-center text-sm font-semibold">
            {item.name}
          </div>
          <div className="mt-1 truncate text-center text-xs text-muted-foreground">
            {item.path}
          </div>
        </div>
      </div>

      <div className="mt-3 rounded-lg bg-white p-4 shadow-[var(--shadow-xs)] ring-1 ring-black/5">
        <div className="text-sm font-semibold">来源定位</div>
        <div className="mt-3 space-y-2 text-xs text-muted-foreground">
          <div className="flex justify-between gap-3">
            <span>类型</span>
            <span className="text-foreground">{item.kind}</span>
          </div>
          <div className="flex justify-between gap-3">
            <span>更新时间</span>
            <span className="text-foreground">{item.updated}</span>
          </div>
          <div className="flex justify-between gap-3">
            <span>大小</span>
            <span className="text-foreground">{item.size}</span>
          </div>
        </div>
      </div>

      <div className="mt-3 rounded-lg bg-white p-4 shadow-[var(--shadow-xs)] ring-1 ring-black/5">
        <div className="text-sm font-semibold">可带入任务的片段</div>
        <p className="mt-2 rounded-lg bg-[#f7f7f7] p-3 text-xs leading-5 text-muted-foreground">
          本地命中摘要会先停留在预览区。点击引用后，仅当前片段、文件名和来源定位进入任务上下文。
        </p>
      </div>

      <div className="mt-3 grid gap-2">
        <Button
          variant="secondary"
          className="justify-start rounded-lg bg-white shadow-[var(--shadow-xs)]"
        >
          <FileSearchIcon className="size-4" />
          在对话中引用
        </Button>
        <Button
          variant="secondary"
          className="justify-start rounded-lg bg-white shadow-[var(--shadow-xs)]"
        >
          <FolderOpenIcon className="size-4" />
          打开所在位置
        </Button>
      </div>
    </div>
  );
}

function AppsView({
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
}: {
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
}) {
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-black/5 bg-[#f5f5f5] px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">应用</div>
          <div className="truncate text-xs text-muted-foreground">
            {APP_ITEMS.length} 项 · 本机应用注册表
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label="搜索应用："
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label="排序"
            className="size-8 rounded-md"
          >
            <SlidersHorizontalIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="列表视图"
            className="size-8 rounded-md"
          >
            <LayoutListIcon className="size-4" />
          </Button>
        </div>
      </div>
      <main className="min-h-0 flex-1 overflow-hidden bg-white">
        <div className="flex h-12 items-center justify-between border-b border-black/5 px-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">已收录应用</div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              按启动器、系统组件与工具分类统一检索
            </div>
          </div>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            列表
          </Badge>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_140px_130px_120px] gap-3 border-b border-black/5 bg-[#fbfbfb] px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>名称</span>
          <span>类型</span>
          <span>状态</span>
          <span className="text-right">动作</span>
        </div>
        <div className="min-h-0 overflow-y-auto">
          {APP_ITEMS.map((item) => (
            <AppListRow key={item.name} item={item} />
          ))}
        </div>
      </main>
    </>
  );
}

function AppListRow({ item }: { item: AppItem }) {
  const Icon = item.icon;
  return (
    <div className="grid w-full grid-cols-[minmax(0,1fr)_140px_130px_120px] items-center gap-3 border-b border-black/[0.035] px-3 py-2.5 text-left text-sm transition-colors hover:bg-black/[0.025]">
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-md",
            toneClass(item.tone),
          )}
        >
          <Icon className="size-4" />
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium">{item.name}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {item.path}
          </span>
        </span>
      </div>
      <span className="truncate text-xs text-muted-foreground">
        {item.type}
      </span>
      <span>
        <Badge
          variant="outline"
          className="rounded-md border-black/10 bg-white text-xs"
        >
          {item.status}
        </Badge>
      </span>
      <span className="flex justify-end gap-1">
        <button
          type="button"
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-black/[0.05] hover:text-foreground"
        >
          打开
        </button>
        <button
          type="button"
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-black/[0.05] hover:text-foreground"
        >
          动作
        </button>
      </span>
    </div>
  );
}

function LocalDiskView({
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
}: {
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
}) {
  const userFolders = [
    disk("Applications", "/Applications", "文件夹", "142 项", AppWindowIcon),
    disk("Desktop", "~/Desktop", "文件夹", "12 项", FolderOpenIcon),
    disk("Documents", "~/Documents", "文件夹", "326 项", FileTextIcon),
    disk("Downloads", "~/Downloads", "文件夹", "58 项", ArchiveIcon),
    disk("Pictures", "~/Pictures", "文件夹", "8,426 项", FileImageIcon),
    disk("Public", "~/Public", "文件夹", "4 项", FolderIcon),
  ];

  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-black/5 bg-[#f5f5f5] px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:px-3 lg:py-0">
        <div className="flex min-w-0 flex-wrap items-center text-sm">
          {["Macintosh HD", "Users", "dangbei"].map((item, index, items) => (
            <span key={item} className="flex min-w-0 items-center">
              <button
                type="button"
                className={cn(
                  "max-w-32 truncate rounded px-1.5 py-1",
                  index === items.length - 1
                    ? "font-semibold text-foreground"
                    : "text-muted-foreground hover:bg-black/[0.04] hover:text-foreground",
                )}
              >
                {item}
              </button>
              {index < items.length - 1 && (
                <ChevronRightIcon className="mx-0.5 size-3 text-muted-foreground/60" />
              )}
            </span>
          ))}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label="在当前位置中搜索："
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label="排序"
            className="size-8 rounded-md"
          >
            <SlidersHorizontalIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="列表视图"
            className="size-8 rounded-md"
          >
            <LayoutListIcon className="size-4" />
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden bg-white">
          <div className="flex h-12 items-center justify-between border-b border-black/5 px-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">dangbei</div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">
                /Users/dangbei · {userFolders.length} 项
              </div>
            </div>
            <Badge
              variant="outline"
              className="rounded-md border-black/10 bg-white"
            >
              当前目录
            </Badge>
          </div>
          <div className="border-b border-black/5 bg-[#fafafa] px-3 py-2 text-xs text-muted-foreground">
            默认停在当前用户目录，避免一进来就展开到深层项目路径。
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_120px_96px_36px] gap-3 border-b border-black/5 bg-[#fbfbfb] px-3 py-2 text-xs font-medium text-muted-foreground">
            <span>名称</span>
            <span>类型</span>
            <span>项目</span>
            <span />
          </div>
          <div className="min-h-0 overflow-y-auto">
            {userFolders.map((item) => (
              <LocalDiskEntryRow key={item.path} item={item} />
            ))}
          </div>
          <div className="border-t border-black/5 bg-[#fbfbfb] px-3 py-2 text-xs text-muted-foreground">
            {manifest
              ? "常用位置与 Octopus NAS 已接入。本地数据库只保存路径、缩略图、OCR 文本和向量索引。"
              : "常用位置可直接浏览；Octopus NAS 正等待连接。本地数据库只保存路径、缩略图、OCR 文本和向量索引。"}
          </div>
        </main>
      </div>
    </>
  );
}

function LocalDiskEntryRow({ item }: { item: DiskItem }) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      className="grid w-full grid-cols-[minmax(0,1fr)_120px_96px_36px] items-center gap-3 border-b border-black/[0.035] px-3 py-2.5 text-left text-sm transition-colors hover:bg-black/[0.025]"
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-md bg-[#f5f5f5] text-muted-foreground ring-1 ring-black/5">
          <Icon className="size-4" />
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium">{item.name}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {item.path}
          </span>
        </span>
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {item.type}
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {item.size}
      </span>
      <ChevronRightIcon className="ml-auto size-4 text-muted-foreground" />
    </button>
  );
}

function SourcesView({
  sources,
  stats,
  manifest,
  serviceError,
  isPickingFolder,
  isReconnecting,
  onPickFolder,
  onReconnect,
  onRemoveSource,
  folderInputRef,
  onFolderInputChange,
}: {
  sources: NASSource[];
  stats: { files: number; chunks: number; sources: number };
  manifest: NASManifest | null;
  serviceError: string | null;
  isPickingFolder: boolean;
  isReconnecting: boolean;
  onPickFolder: () => void;
  onReconnect: () => void;
  onRemoveSource: (id: string) => Promise<void>;
  folderInputRef: React.RefObject<HTMLInputElement | null>;
  onFolderInputChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
      <div className="flex shrink-0 flex-col gap-2 border-b border-black/5 bg-[#f5f5f5] px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">授权目录</div>
          <div className="truncate text-xs text-muted-foreground">
            管理已授权目录、索引状态与扫描范围
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Button
            size="sm"
            className="h-8 rounded-md bg-black px-2.5 text-xs text-white hover:bg-black/85"
            onClick={onPickFolder}
            disabled={isPickingFolder}
          >
            <FolderPlusIcon className="size-3.5" />
            添加
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="扫描队列"
            className="size-8 rounded-md"
          >
            <RefreshCwIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="隐私策略"
            className="size-8 rounded-md"
          >
            <ShieldCheckIcon className="size-4" />
          </Button>
        </div>
      </div>

      <div className="grid shrink-0 gap-2 border-b border-black/5 bg-[#fbfbfb] p-3 sm:grid-cols-3">
        <Metric label="授权目录" value={String(stats.sources)} />
        <Metric label="扫描文件" value={String(stats.files)} />
        <Metric label="索引片段" value={String(stats.chunks)} />
      </div>

      {!manifest && (
        <div className="flex shrink-0 flex-col gap-2 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="font-medium">下一步：重新连接本地知识库服务</div>
            <div className="mt-0.5 truncate text-amber-900/80">
              {serviceError || `当前未连接 ${getNASBaseURL()}`}
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-8 shrink-0 rounded-md border-amber-300 bg-white px-3 text-amber-950 hover:bg-amber-100"
            onClick={onReconnect}
            disabled={isReconnecting}
          >
            <RefreshCwIcon
              className={cn("size-3.5", isReconnecting && "animate-spin")}
            />
            {isReconnecting ? "连接中" : "重新连接"}
          </Button>
        </div>
      )}

      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-black/5 px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {["Documents", "Pictures", "Downloads", "Public/octopus"].map(
            (item) => (
              <button
                key={item}
                type="button"
                className="rounded-md border border-black/10 bg-white px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {item}
              </button>
            ),
          )}
        </div>
        <div className="hidden shrink-0 items-center gap-2 md:flex">
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white text-xs"
          >
            本地索引
          </Badge>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white text-xs"
          >
            原文件不上传
          </Badge>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="hidden grid-cols-[minmax(260px,1fr)_92px_92px_120px] border-b border-black/5 bg-[#fbfbfb] px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
          <span>目录</span>
          <span>文件</span>
          <span>片段</span>
          <span className="text-right">状态</span>
        </div>
        {sources.length === 0 ? (
          <div className="flex min-h-[360px] flex-col items-center justify-center px-8 text-center">
            <div className="grid size-14 place-items-center rounded-lg bg-black text-white shadow-[var(--shadow-xs)]">
              <FolderPlusIcon className="size-7" />
            </div>
            <div className="mt-4 text-base font-semibold">
              {manifest
                ? "选择一个本机文件夹开始建索引"
                : "先恢复本地服务，再添加文件夹"}
            </div>
            <div className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
              {manifest
                ? "本地数据库会在本机解析文件、OCR 图片并生成向量索引。原文件不上传；只有你确认引用的片段会进入任务上下文。"
                : "离线时可以浏览常用位置，但无法扫描新目录。重新连接后再添加文件夹，索引会在本机生成。"}
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              <Button
                className="rounded-md bg-black text-white hover:bg-black/85"
                onClick={manifest ? onPickFolder : onReconnect}
                disabled={manifest ? isPickingFolder : isReconnecting}
              >
                {manifest ? (
                  <FolderPlusIcon className="size-4" />
                ) : (
                  <RefreshCwIcon
                    className={cn(
                      "size-4",
                      isReconnecting && "animate-spin",
                    )}
                  />
                )}
                {manifest
                  ? "添加文件夹"
                  : isReconnecting
                    ? "连接中"
                    : "重新连接"}
              </Button>
              <Button
                variant="secondary"
                className="rounded-md bg-black/[0.04]"
              >
                <ShieldCheckIcon className="size-4" />
                查看隐私策略
              </Button>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-black/5">
            {sources.map((source) => (
              <SourceRow
                key={source.source_id}
                source={source}
                onRemove={() => void onRemoveSource(source.source_id)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-black/5 bg-[#fbfbfb] px-4 py-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>隐私机制: 文件解析、OCR 与向量索引默认落在本机。</span>
          <span>扫描队列: 等待扫描 0 · OCR 处理中 0 · 失败文件 0</span>
        </div>
      </div>

      <input
        ref={folderInputRef}
        type="file"
        // @ts-expect-error - Chromium/WebKit folder picker fallback
        webkitdirectory=""
        directory=""
        multiple
        hidden
        aria-label="选择文件夹"
        onChange={onFolderInputChange}
      />
    </main>
  );
}

function SearchResultsView({
  hits,
  query,
  setQuery,
  runSearch,
  isSearching,
  manifest,
  message,
  libraryLabel,
  onBack,
}: {
  hits: NASSearchHit[];
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
  message?: string | null;
  libraryLabel: string;
  onBack: () => void;
}) {
  const hasHits = hits.length > 0;
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-black/5 bg-[#f7f7f7] px-3 py-2 lg:h-[60px] lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:px-4 lg:py-0">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            size="sm"
            variant="ghost"
            className="h-8 shrink-0 rounded-lg bg-white px-2 shadow-[var(--shadow-xs)] ring-1 ring-black/5"
            onClick={onBack}
          >
            返回{libraryLabel}
          </Button>
          <div className="min-w-0">
            <div className="text-sm font-semibold">
              {hasHits ? "搜索结果" : "检索状态"}
            </div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              {hasHits
                ? `“${query}” · 本机索引命中 ${hits.length} 条，引用前不会进入任务上下文`
                : `“${query}” · 本机资料官未返回命中`}
            </div>
          </div>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <ToolbarSearch
            label="继续搜索："
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            className="h-9 shrink-0 rounded-lg bg-black px-3 text-white hover:bg-black/85"
            disabled={!hasHits}
          >
            <MessageSquarePlusIcon className="size-4" />
            引用选中
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto bg-[#f7f7f7] p-5">
        {hasHits ? (
          <div className="overflow-hidden rounded-lg bg-white shadow-[var(--shadow-xs)] ring-1 ring-black/5">
            {hits.map((hit) => (
              <div
                key={hit.chunk_id}
                className="flex w-full items-center gap-3 border-b border-black/[0.04] px-4 py-3 text-left last:border-b-0 hover:bg-black/[0.025]"
              >
                <FileSearchIcon className="size-5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {hit.title || basename(hit.path)}
                  </div>
                  <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                    {hit.snippet}
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground/75">
                    {hit.path}
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className="rounded-full border-black/10"
                >
                  {Math.round(hit.score * 100)}%
                </Badge>
                <QuickFileActions />
              </div>
            ))}
          </div>
        ) : (
          <div className="flex min-h-[340px] flex-col items-center justify-center rounded-lg bg-white px-6 text-center shadow-[var(--shadow-xs)] ring-1 ring-black/5">
            <div className="grid size-14 place-items-center rounded-lg bg-amber-50 text-amber-700">
              <FileSearchIcon className="size-6" />
            </div>
            <div className="mt-4 text-base font-semibold">
              {message?.includes("not attached")
                ? "本机检索引擎尚未接入"
                : "没有找到匹配资料"}
            </div>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
              {message ??
                "换一个关键词，或先在“授权目录”里添加文件夹并运行索引。"}
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                className="rounded-lg bg-black/[0.04]"
                onClick={() => {
                  window.location.hash =
                    "/workspace/storage?surface=company&library=sources";
                }}
              >
                查看授权目录
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="rounded-lg bg-black/[0.04]"
              >
                切换隐私模式
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-default bg-background/80 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function SourceRow({
  source,
  onRemove,
}: {
  source: NASSource;
  onRemove: () => void;
}) {
  const { confirm, confirmDialog } = useConfirmDialog();
  const isReady = source.status === "ready";
  const displayPath = isAbsolutePath(source.path) ? source.path : source.path;
  return (
    <div className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[minmax(260px,1fr)_92px_92px_120px] md:items-center md:gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <HardDriveIcon className="size-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <div className="truncate font-medium">{source.display_name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {displayPath}
          </div>
        </div>
      </div>
      <div className="flex items-center text-xs text-muted-foreground md:block">
        {source.file_count} 文件
      </div>
      <div className="flex items-center text-xs text-muted-foreground md:block">
        {source.chunk_count} 片段
      </div>
      <div className="flex items-center gap-2 md:justify-end">
        <Badge
          variant="outline"
          className={cn(
            "h-5 px-1.5 text-xs",
            isReady
              ? "border-emerald-300/55 bg-emerald-50 text-emerald-800"
              : "border-amber-300/55 bg-amber-50 text-amber-800",
          )}
        >
          {isReady ? "已就绪" : "待索引"}
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          onClick={async () => {
            if (
              await confirm({
                title: "移除授权目录",
                description: `将移除「${source.display_name}」及其索引数据，此操作不可撤销。`,
                confirmLabel: "移除",
              })
            ) {
              onRemove();
            }
          }}
        >
          移除
        </Button>
      </div>
      {confirmDialog}
    </div>
  );
}

function toneClass(tone: string) {
  const classes: Record<string, string> = {
    blue: "bg-sky-50 text-sky-700",
    green: "bg-emerald-50 text-emerald-700",
    violet: "bg-violet-50 text-violet-700",
    amber: "bg-amber-50 text-amber-700",
    rose: "bg-rose-50 text-rose-700",
    zinc: "bg-muted text-muted-foreground",
  };
  return classes[tone] ?? tone;
}
