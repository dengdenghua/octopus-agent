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
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales";
import {
  createNASIndexJob,
  createNASSource,
  deleteNASSource,
  getNASBaseURL,
  getNASManifest,
  getNASPolicy,
  isNASAuthenticationError,
  listNASSources,
  searchNAS,
  startNASService,
  updateNASPolicy,
  type NASManifest,
  type NASPolicy,
  type NASSearchHit,
  type NASSource,
} from "@/core/storage/api";
import { pickLocalDirectory } from "@/core/workspace/pick-local-directory";
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

type StorageCopy = Translations["storage"];

interface LibraryMeta {
  key: LibraryKey;
  label: string;
  detail: string;
  icon: LucideIcon;
}

function buildLibraries(copy: StorageCopy): LibraryMeta[] {
  return [
    {
      key: "overview",
      label: copy.libraries.overviewLabel,
      detail: copy.libraries.overviewDetail,
      icon: DatabaseIcon,
    },
    {
      key: "apps",
      label: copy.libraries.appsLabel,
      detail: copy.libraries.appsDetail,
      icon: AppWindowIcon,
    },
    {
      key: "docs",
      label: copy.libraries.docsLabel,
      detail: copy.libraries.docsDetail,
      icon: FileTextIcon,
    },
    {
      key: "images",
      label: copy.libraries.imagesLabel,
      detail: copy.libraries.imagesDetail,
      icon: FileImageIcon,
    },
    {
      key: "computer",
      label: copy.libraries.computerLabel,
      detail: copy.libraries.computerDetail,
      icon: HardDriveIcon,
    },
    {
      key: "sources",
      label: copy.libraries.sourcesLabel,
      detail: copy.libraries.sourcesDetail,
      icon: FolderPlusIcon,
    },
  ];
}

const LIBRARY_KEYS = new Set<LibraryKey>([
  "overview",
  "apps",
  "docs",
  "images",
  "computer",
  "sources",
]);

function fill(
  template: string,
  vars: Record<string, string | number>,
): string {
  return Object.entries(vars).reduce(
    (result, [key, value]) =>
      result.replaceAll(`{${key}}`, String(value)),
    template,
  );
}

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

function buildDocTopics(copy: StorageCopy): TopicItem[] {
  return [
    topic(
      copy.topics.docsAllTitle,
      copy.topics.docsAllSubtitle,
      "1,284",
      copy.topics.docsAllStatus,
      FileTextIcon,
      "blue",
      ["PDF", "DOC", "MD"],
    ),
    topic(
      copy.topics.docsSourcesTitle,
      copy.topics.docsSourcesSubtitle,
      "32",
      copy.topics.docsSourcesStatus,
      FolderOpenIcon,
      "green",
      [
        copy.topics.coverWork,
        copy.topics.coverProject,
        copy.topics.coverDownloads,
      ],
    ),
    topic(
      copy.topics.docsTopicsTitle,
      copy.topics.docsTopicsSubtitle,
      "18",
      copy.topics.docsTopicsStatus,
      BrainIcon,
      "violet",
      [
        copy.topics.coverContract,
        copy.topics.coverTech,
        copy.topics.coverResearch,
      ],
    ),
    topic(
      copy.topics.docsRecentTitle,
      copy.topics.docsRecentSubtitle,
      "96",
      copy.topics.docsRecentStatus,
      FileSearchIcon,
      "zinc",
      [
        copy.topics.coverToday,
        copy.topics.cover7Days,
        copy.topics.cover30Days,
      ],
    ),
  ];
}

function buildImageTopics(copy: StorageCopy): TopicItem[] {
  return [
    topic(
      copy.topics.imagesAllTitle,
      copy.topics.imagesAllSubtitle,
      "8,426",
      copy.topics.imagesAllStatus,
      FileImageIcon,
      "green",
      ["JPG", "PNG", "WEBP"],
    ),
    topic(
      copy.topics.imagesTopicsTitle,
      copy.topics.imagesTopicsSubtitle,
      "41",
      copy.topics.imagesTopicsStatus,
      SparklesIcon,
      "violet",
      [
        copy.topics.coverPeople,
        copy.topics.coverPlaces,
        copy.topics.coverTheme,
      ],
    ),
    topic(
      copy.topics.imagesSourcesTitle,
      copy.topics.imagesSourcesSubtitle,
      "24",
      copy.topics.imagesSourcesStatus,
      FolderOpenIcon,
      "blue",
      [
        copy.topics.coverDesktop,
        copy.topics.coverDownloads,
        copy.topics.coverWechat,
      ],
    ),
    topic(
      copy.topics.imagesOcrTitle,
      copy.topics.imagesOcrSubtitle,
      "1,230",
      copy.topics.imagesOcrStatus,
      ImageIcon,
      "amber",
      [
        copy.topics.coverWhiteboard,
        copy.topics.coverInterface,
        copy.topics.coverSpreadsheet,
      ],
    ),
  ];
}

function buildAppItems(copy: StorageCopy): AppItem[] {
  return [
    app(
      "Finder",
      copy.apps.typeSystemApp,
      "/System/Applications/Finder.app",
      copy.apps.statusRegistered,
      FolderOpenIcon,
      "blue",
    ),
    app(
      "Preview",
      copy.apps.typeImagePdf,
      "/System/Applications/Preview.app",
      copy.apps.statusRegistered,
      ImageIcon,
      "green",
    ),
    app(
      "Office",
      copy.apps.typeDocsSheets,
      "/Applications",
      copy.apps.statusPendingScan,
      FileArchiveIcon,
      "amber",
    ),
    app(
      "Browser",
      copy.apps.typeWebResources,
      "/Applications",
      copy.apps.statusRegistered,
      AppWindowIcon,
      "violet",
    ),
    app(
      "Terminal",
      copy.apps.typeSystemTool,
      "/System/Applications/Utilities",
      copy.apps.statusCallable,
      ServerIcon,
      "zinc",
    ),
    app(
      "Downloads",
      copy.apps.typeDownloadManager,
      "~/Downloads",
      copy.apps.statusFolder,
      ArchiveIcon,
      "blue",
    ),
  ];
}

function buildDocFiles(copy: StorageCopy): FileItem[] {
  return [
    file(
      copy.demoFiles.doc1Name,
      "~/Documents/Research/AI Glasses.md",
      copy.demoFiles.doc1Kind,
      copy.demoFiles.doc1Updated,
      "128 KB",
      FileTextIcon,
      "blue",
    ),
    file(
      copy.demoFiles.doc2Name,
      "~/Documents/Product/Roadmap.pptx",
      copy.demoFiles.doc2Kind,
      copy.demoFiles.doc2Updated,
      "18.4 MB",
      TablePropertiesIcon,
      "amber",
    ),
    file(
      copy.demoFiles.doc3Name,
      "~/Documents/Contracts/Vendor.pdf",
      copy.demoFiles.doc3Kind,
      copy.demoFiles.doc3Updated,
      "3.2 MB",
      FileArchiveIcon,
      "rose",
    ),
    file(
      copy.demoFiles.doc4Name,
      "~/Public/octopus/local-models.md",
      copy.demoFiles.doc4Kind,
      copy.demoFiles.doc4Updated,
      "42 KB",
      BrainIcon,
      "violet",
    ),
    file(
      copy.demoFiles.doc5Name,
      "~/Documents/NAS/Permissions.xlsx",
      copy.demoFiles.doc5Kind,
      copy.demoFiles.doc5Updated,
      "812 KB",
      FileSearchIcon,
      "green",
    ),
  ];
}

function buildImageFiles(copy: StorageCopy): FileItem[] {
  return [
    file(
      "aoi-front-transparent.png",
      "~/Pictures/Agents/aoi-front.png",
      copy.demoFiles.image1Kind,
      copy.demoFiles.image1Updated,
      "4.8 MB",
      FileImageIcon,
      "green",
    ),
    file(
      copy.demoFiles.image2Name,
      "~/Pictures/Whiteboard/meeting.jpg",
      copy.demoFiles.image2Kind,
      copy.demoFiles.image2Updated,
      "2.1 MB",
      ImageIcon,
      "blue",
    ),
    file(
      copy.demoFiles.image3Name,
      "~/Pictures/Screenshots/workspace.webp",
      copy.demoFiles.image3Kind,
      copy.demoFiles.image3Updated,
      "980 KB",
      FileImageIcon,
      "violet",
    ),
    file(
      copy.demoFiles.image4Name,
      "~/Pictures/Receipts/travel.png",
      copy.demoFiles.image4Kind,
      copy.demoFiles.image4Updated,
      "1.4 MB",
      FileSearchIcon,
      "amber",
    ),
  ];
}

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
  const { t } = useI18n();
  const copy = t.storage;
  const [searchParams] = useSearchParams();
  const [manifest, setManifest] = useState<NASManifest | null>(null);
  const [policy, setPolicy] = useState<NASPolicy>(DEFAULT_POLICY);
  const [sources, setSources] = useState<NASSource[]>([]);
  const [query, setQuery] = useState(() => copy.defaultQuery);
  const [hits, setHits] = useState<NASSearchHit[]>([]);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);
  const [hasSearchResult, setHasSearchResult] = useState(false);
  const [isPickingFolder, setIsPickingFolder] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const didAutoStartRef = useRef(false);

  const libraryParam = searchParams.get("library");
  const activeLibrary = isLibraryKey(libraryParam) ? libraryParam : "computer";
  const libraries = useMemo(() => buildLibraries(copy), [copy]);
  const activeMeta = libraries.find((item) => item.key === activeLibrary)!;

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
      setServiceError(
        isNASAuthenticationError(error)
          ? copy.service.credentialsExpired
          : error instanceof Error
            ? error.message
            : String(error),
      );
      return false;
    }
  }, [copy]);

  const ensureNASService = useCallback(async () => {
    const startResult = await startNASService();
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (await refreshNAS()) return true;
      await delay(500);
    }
    if (startResult.status === "not_found") {
      setServiceError(copy.service.notFound);
      return false;
    }
    if (startResult.status === "error") {
      setServiceError(copy.service.startFailed);
      return false;
    }
    setServiceError(
      fill(copy.service.notConnected, { url: getNASBaseURL() }),
    );
    return false;
  }, [copy, refreshNAS]);

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
      const selected = await pickLocalDirectory();
      if (selected) await addSource(selected);
    } catch (err) {
      setServiceError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsPickingFolder(false);
    }
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
                  <span className="min-w-0 truncate">{serviceError}</span>
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
                    {isReconnecting
                      ? copy.toolbar.reconnecting
                      : copy.toolbar.reconnect}
                  </Button>
                </div>
              )}

              {activeLibrary !== "sources" && (
                <div className="flex shrink-0 items-center justify-end gap-1.5 border-b border-border bg-muted px-3 py-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-8 rounded-md bg-white px-2 text-xs shadow-[var(--shadow-xs)]"
                    onClick={pickFolder}
                    disabled={isPickingFolder}
                  >
                    <FolderPlusIcon className="size-3.5" />
                    {copy.toolbar.authorize}
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
                    {copy.toolbar.scan}
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
                    {policy.mode === "privacy"
                      ? copy.toolbar.privacy
                      : copy.toolbar.efficiency}
                  </Button>
                  <span className="ml-1 flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                    <span
                      className={cn(
                        "size-1.5 rounded-full",
                        manifest ? "bg-emerald-500" : "bg-amber-500",
                      )}
                    />
                    <span>
                      {manifest ? copy.toolbar.online : copy.toolbar.offline}
                    </span>
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
  const { t } = useI18n();
  const copy = t.storage;
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
          placeholder={copy.toolbar.searchPlaceholder}
          className="h-8 min-w-36 border-0 bg-transparent px-1 text-sm shadow-none focus-visible:ring-0"
        />
      </div>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-label={copy.toolbar.searchAria}
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
  activeMeta: LibraryMeta;
  query: string;
  setQuery: (value: string) => void;
  runSearch: () => void;
  isSearching: boolean;
  manifest: NASManifest | null;
  searchMessage: string | null;
}) {
  const { t } = useI18n();
  const copy = t.storage;
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

  const docTopics = buildDocTopics(copy);
  const imageTopics = buildImageTopics(copy);
  const docFiles = buildDocFiles(copy);
  const imageFiles = buildImageFiles(copy);
  const topics = [...docTopics.slice(0, 2), ...imageTopics.slice(0, 2)];
  const tabs = [
    copy.overview.tabAll,
    copy.overview.tabDocs,
    copy.overview.tabImages,
    copy.overview.tabRecent,
  ];
  const recentItems = [...docFiles.slice(0, 3), ...imageFiles.slice(0, 2)];

  return (
    <>
      <div className="flex h-[52px] shrink-0 items-center justify-between gap-4 border-b border-border bg-muted/50 px-4">
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
            label={fill(copy.toolbar.searchIn, { label: activeMeta.label })}
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.scopeFilterAria}
            className="rounded-full"
          >
            <ListFilterIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.gridViewAria}
            className="rounded-full"
          >
            <Grid3X3Icon className="size-4" />
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(420px,1fr)_320px] overflow-hidden">
        <aside className="min-h-0 overflow-y-auto border-r border-border bg-muted/50 p-3">
          <div className="mb-3 rounded-lg bg-white p-3 shadow-[var(--shadow-xs)] ring-1 ring-border">
            <div className="text-sm font-semibold">
              {copy.overview.indexingTitle}
            </div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              {copy.overview.indexingDesc}
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full w-2/3 rounded-full bg-foreground" />
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
                {searchMessage || copy.overview.aggregateDesc}
              </div>
            </div>
            <Badge
              variant="outline"
              className="rounded-full border-black/10 bg-white"
            >
              {copy.overview.localDatabaseBadge}
            </Badge>
          </div>
          <div className="grid gap-3 2xl:grid-cols-2">
            {recentItems.map((item) => (
              <FileCard key={item.path} item={item} />
            ))}
          </div>
        </main>

        <aside className="min-h-0 overflow-y-auto border-l border-border bg-muted/30 p-4">
          <PreviewPanel
            title={copy.overview.previewTitle}
            subtitle={copy.overview.previewSubtitle}
            item={docFiles[0]!}
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
  const { t } = useI18n();
  const copy = t.storage;
  const docFiles = buildDocFiles(copy);
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-muted px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{copy.docs.title}</div>
          <div className="truncate text-xs text-muted-foreground">
            {fill(copy.docs.subtitle, { count: docFiles.length })}
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label={copy.docs.searchLabel}
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.filterAria}
            className="size-8 rounded-md"
          >
            <ListFilterIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.listViewAria}
            className="size-8 rounded-md"
          >
            <LayoutListIcon className="size-4" />
          </Button>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden bg-white">
        <div className="flex h-12 items-center justify-between border-b border-border px-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">
              {copy.docs.allDocs}
            </div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              {searchMessage || copy.docs.indexNote}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge
              variant="outline"
              className="rounded-md border-black/10 bg-white"
            >
              {copy.docs.badgeRecent}
            </Badge>
            <Badge
              variant="outline"
              className="rounded-md border-black/10 bg-white"
            >
              {copy.docs.badgeLocalDocs}
            </Badge>
          </div>
        </div>
        <div className="grid grid-cols-[minmax(240px,1fr)_minmax(180px,280px)_92px_120px_104px] items-center gap-3 border-b border-border bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>{copy.docs.colName}</span>
          <span>{copy.docs.colLocation}</span>
          <span>{copy.docs.colSize}</span>
          <span className="text-right">{copy.docs.colModified}</span>
          <span className="text-right">{copy.docs.colActions}</span>
        </div>
        <div className="min-h-0 overflow-y-auto">
          {docFiles.map((item) => (
            <FileManagerRow key={item.path} item={item} />
          ))}
        </div>
        <div className="border-t border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          {copy.docs.footerNote}
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
  const { t } = useI18n();
  const copy = t.storage;
  const imageFiles = buildImageFiles(copy);
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-muted px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">
            {copy.images.title}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {fill(copy.images.subtitle, { count: imageFiles.length })}
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label={copy.images.searchLabel}
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.filterAria}
            className="size-8 rounded-md"
          >
            <ListFilterIcon className="size-4" />
          </Button>
          <Badge
            variant="outline"
            className="h-8 rounded-md border-black/10 bg-white px-2.5 text-xs"
          >
            {copy.images.badgeAllImages}
          </Badge>
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.gridViewAria}
            className="size-8 rounded-md"
          >
            <Grid3X3Icon className="size-4" />
          </Button>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-y-auto bg-muted/50 px-4 py-4 lg:px-6">
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            {fill(copy.images.filterAll, { count: imageFiles.length })}
          </Badge>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            {copy.images.filterOcr}
          </Badge>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            {copy.images.filterLocalLibrary}
          </Badge>
        </div>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
          {imageFiles.map((item) => (
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
  const { t } = useI18n();
  const Icon = item.icon;
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
        active
          ? "bg-white shadow-[var(--shadow-xs)] ring-1 ring-border"
          : "hover:bg-white/70",
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
          {fill(t.storage.overview.itemsWithStatus, {
            count: item.count,
            status: item.status,
          })}
        </span>
      </span>
      <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
    </button>
  );
}

function FileCard({ item }: { item: FileItem }) {
  const Icon = item.icon;
  return (
    <div className="group flex min-h-20 items-center gap-3 rounded-lg border border-border bg-white p-3 text-left shadow-[var(--shadow-xs)] transition-colors hover:border-black/10 hover:bg-muted/30">
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
  const { t } = useI18n();
  const Icon = item.icon;
  return (
    <div className="group min-w-0 overflow-hidden rounded-lg border border-border bg-white text-left shadow-[var(--shadow-xs)] transition-colors hover:border-black/10 hover:bg-muted/30">
      <span className="flex aspect-[4/3] w-full items-center justify-center bg-muted/50">
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
          {t.storage.images.ocrBadge}
        </span>
        <QuickFileActions compact />
      </div>
    </div>
  );
}

function QuickFileActions({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const copy = t.storage;
  const buttons = [
    { label: copy.preview.actionPreview, icon: EyeIcon },
    { label: copy.preview.actionQuote, icon: MessageSquarePlusIcon },
    { label: copy.preview.actionLocate, icon: ExternalLinkIcon },
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
  const { t } = useI18n();
  const copy = t.storage;
  const Icon = item.icon;
  return (
    <div className="flex min-h-full flex-col">
      <div className="rounded-lg bg-white p-4 shadow-[var(--shadow-xs)] ring-1 ring-border">
        <div className="text-sm font-semibold">{title}</div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {subtitle}
        </p>
        <div className="mt-4 rounded-lg bg-muted/50 p-4">
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

      <div className="mt-3 rounded-lg bg-white p-4 shadow-[var(--shadow-xs)] ring-1 ring-border">
        <div className="text-sm font-semibold">{copy.preview.sourceLocation}</div>
        <div className="mt-3 space-y-2 text-xs text-muted-foreground">
          <div className="flex justify-between gap-3">
            <span>{copy.preview.typeLabel}</span>
            <span className="text-foreground">{item.kind}</span>
          </div>
          <div className="flex justify-between gap-3">
            <span>{copy.preview.updatedLabel}</span>
            <span className="text-foreground">{item.updated}</span>
          </div>
          <div className="flex justify-between gap-3">
            <span>{copy.preview.sizeLabel}</span>
            <span className="text-foreground">{item.size}</span>
          </div>
        </div>
      </div>

      <div className="mt-3 rounded-lg bg-white p-4 shadow-[var(--shadow-xs)] ring-1 ring-border">
        <div className="text-sm font-semibold">{copy.preview.snippetTitle}</div>
        <p className="mt-2 rounded-lg bg-muted/50 p-3 text-xs leading-5 text-muted-foreground">
          {copy.preview.snippetDesc}
        </p>
      </div>

      <div className="mt-3 grid gap-2">
        <Button
          variant="secondary"
          className="justify-start rounded-lg bg-white shadow-[var(--shadow-xs)]"
        >
          <FileSearchIcon className="size-4" />
          {copy.preview.quoteInChat}
        </Button>
        <Button
          variant="secondary"
          className="justify-start rounded-lg bg-white shadow-[var(--shadow-xs)]"
        >
          <FolderOpenIcon className="size-4" />
          {copy.preview.openLocation}
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
  const { t } = useI18n();
  const copy = t.storage;
  const appItems = buildAppItems(copy);
  return (
    <>
      <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-muted px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{copy.apps.title}</div>
          <div className="truncate text-xs text-muted-foreground">
            {fill(copy.apps.subtitle, { count: appItems.length })}
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ToolbarSearch
            label={copy.apps.searchLabel}
            query={query}
            setQuery={setQuery}
            runSearch={runSearch}
            isSearching={isSearching}
            manifest={manifest}
          />
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.sortAria}
            className="size-8 rounded-md"
          >
            <SlidersHorizontalIcon className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={copy.toolbar.listViewAria}
            className="size-8 rounded-md"
          >
            <LayoutListIcon className="size-4" />
          </Button>
        </div>
      </div>
      <main className="min-h-0 flex-1 overflow-hidden bg-white">
        <div className="flex h-12 items-center justify-between border-b border-border px-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">
              {copy.apps.registeredTitle}
            </div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              {copy.apps.registeredSubtitle}
            </div>
          </div>
          <Badge
            variant="outline"
            className="rounded-md border-black/10 bg-white"
          >
            {copy.apps.badgeList}
          </Badge>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_140px_130px_120px] gap-3 border-b border-border bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>{copy.apps.colName}</span>
          <span>{copy.apps.colType}</span>
          <span>{copy.apps.colStatus}</span>
          <span className="text-right">{copy.apps.colActions}</span>
        </div>
        <div className="min-h-0 overflow-y-auto">
          {appItems.map((item) => (
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
      <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-muted px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:px-3 lg:py-0">
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
          <div className="flex h-12 items-center justify-between border-b border-border px-3">
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
          <div className="border-b border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            默认停在当前用户目录，避免一进来就展开到深层项目路径。
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_120px_96px_36px] gap-3 border-b border-border bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
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
          <div className="border-t border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
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
        <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground ring-1 ring-border">
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
}) {
  return (
    <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
      <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-muted px-3 py-2 lg:h-12 lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0">
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

      <div className="grid shrink-0 gap-2 border-b border-border bg-muted/30 p-3 sm:grid-cols-3">
        <Metric label="授权目录" value={String(stats.sources)} />
        <Metric label="扫描文件" value={String(stats.files)} />
        <Metric label="索引片段" value={String(stats.chunks)} />
      </div>

      {!manifest && (
        <div className="flex shrink-0 flex-col gap-2 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950 lg:flex-row lg:items-center lg:justify-between">
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

      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-3 py-2">
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
        <div className="hidden grid-cols-[minmax(260px,1fr)_92px_92px_120px] border-b border-border bg-muted/30 px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
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
                    className={cn("size-4", isReconnecting && "animate-spin")}
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
          <div className="divide-y divide-border">
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

      <div className="shrink-0 border-t border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>隐私机制: 文件解析、OCR 与向量索引默认落在本机。</span>
          <span>扫描队列: 等待扫描 0 · OCR 处理中 0 · 失败文件 0</span>
        </div>
      </div>
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
      <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-muted/50 px-3 py-2 lg:h-[60px] lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:px-4 lg:py-0">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            size="sm"
            variant="ghost"
            className="h-8 shrink-0 rounded-lg bg-white px-2 shadow-[var(--shadow-xs)] ring-1 ring-border"
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
      <div className="min-h-0 flex-1 overflow-y-auto bg-muted/50 p-5">
        {hasHits ? (
          <div className="overflow-hidden rounded-lg bg-white shadow-[var(--shadow-xs)] ring-1 ring-border">
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
          <div className="flex min-h-[340px] flex-col items-center justify-center rounded-lg bg-white px-6 text-center shadow-[var(--shadow-xs)] ring-1 ring-border">
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
