import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BoxesIcon,
  CheckCircle,
  Plus,
  Puzzle,
  Search,
  Settings2,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import {
  listPlugins,
  hubListPlugins,
  hubGetPluginConfig,
  hubUpdatePluginConfig,
} from "@/core/plugins/api";
import type { PluginInfo } from "@/core/plugins/types";
import type { HubPluginInfo } from "@/core/plugins/types";
import { getBackendBaseURL } from "@/core/config";
import { LocalSkillDirectoryPanel } from "@/components/store/unified-store";
import { useOpenCreatePluginChat } from "@/components/store/store-utils";
import { SkillPacksTab } from "@/components/workspace/agents/skill-packs-tab";
import { cn } from "@/lib/utils";

type PluginsTab = "plugins" | "skills";
type SkillView = "directory" | "packs";
type PluginStatusFilter = "all" | "enabled" | "disabled";

function getInitialState(): { tab: PluginsTab; skillView: SkillView } {
  const hash = window.location.hash;
  if (hash.includes("tab=skill-packs")) {
    return { tab: "skills", skillView: "packs" };
  }
  if (hash.includes("tab=packs") || hash.includes("tab=skills")) {
    return { tab: "skills", skillView: "directory" };
  }
  return { tab: "plugins", skillView: "directory" };
}

function pluginImageUrl(plugin: PluginInfo | HubPluginInfo): string | null {
  const p = plugin as PluginInfo;
  const raw = p.logo_url || p.icon_url;
  if (!raw) return null;
  if (raw.startsWith("http://") || raw.startsWith("https://")) return raw;
  return `${getBackendBaseURL()}${raw}`;
}

function pluginSurfaceBadges(entry: PluginEntry): string[] {
  if (entry.source === "hub") {
    const labels = entry.plugin.capabilities
      .map((capability) => capability.type)
      .filter(Boolean)
      .map((type) => {
        if (type === "skill") return "技能";
        if (type === "channel") return "通道";
        if (type === "api") return "API";
        if (type === "config_ui") return "配置";
        return type;
      });
    return Array.from(new Set(labels)).slice(0, 4);
  }
  const surfaces = entry.plugin.smoke?.surfaces;
  const badges: string[] = [];
  if (surfaces?.mcp) badges.push("MCP");
  if (surfaces?.apps) badges.push("App");
  if (surfaces?.skills) badges.push("技能");
  if (surfaces?.commands) badges.push("命令");
  if (surfaces?.capabilities && !badges.includes("API")) badges.push("能力");
  return badges.slice(0, 5);
}

// ── Config dialog for PluginHub plugins ───────────────────────

function HubPluginConfigDialog({
  plugin,
  open,
  onOpenChange,
}: {
  plugin: HubPluginInfo;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      hubGetPluginConfig(plugin.id)
        .then(setConfig)
        .catch((e) => swallow(e));
    }
  }, [plugin.id, open]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await hubUpdatePluginConfig(plugin.id, config);
      onOpenChange(false);
    } catch (e) {
      swallow(e);
    } finally {
      setSaving(false);
    }
  };

  const schema = plugin.config_schema as
    | {
        properties?: Record<
          string,
          {
            type?: string;
            title?: string;
            description?: string;
            format?: string;
          }
        >;
      }
    | undefined;
  const properties = schema?.properties;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{plugin.name} 配置</DialogTitle>
          <DialogDescription>
            配置 {plugin.name} 插件的运行参数
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {properties && Object.keys(properties).length > 0 ? (
            Object.entries(properties).map(([key, prop]) => (
              <div key={key} className="space-y-1">
                <Label htmlFor={`cfg-${key}`}>{prop.title || key}</Label>
                {prop.description && (
                  <p className="text-xs text-muted-foreground">
                    {prop.description}
                  </p>
                )}
                <Input
                  id={`cfg-${key}`}
                  type={
                    prop.format === "password"
                      ? "password"
                      : prop.type === "integer"
                        ? "number"
                        : "text"
                  }
                  value={String(config[key] ?? "")}
                  onChange={(e) =>
                    setConfig((prev) => ({
                      ...prev,
                      [key]:
                        prop.type === "integer"
                          ? parseInt(e.target.value) || 0
                          : e.target.value,
                    }))
                  }
                />
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">此插件无需配置</p>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">取消</Button>
          </DialogClose>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : "保存"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type PluginEntry =
  | { plugin: HubPluginInfo; source: "hub" }
  | { plugin: PluginInfo; source: "legacy" };

function PluginListItem({
  entry,
  onConfigure,
}: {
  entry: PluginEntry;
  onConfigure: (plugin: HubPluginInfo) => void;
}) {
  const { plugin } = entry;
  const hubPlugin = entry.source === "hub" ? entry.plugin : null;
  const imageUrl = pluginImageUrl(plugin);
  const hasConfig = Boolean(
    hubPlugin?.config_schema && Object.keys(hubPlugin.config_schema).length > 0,
  );
  const statusTitle = plugin.error
    ? plugin.error
    : plugin.enabled
      ? "已启用"
      : "未启用";
  const surfaceBadges = pluginSurfaceBadges(entry);

  return (
    <div className="group flex min-w-0 items-center gap-3 rounded-lg border border-border/45 bg-card/55 px-3 py-3 shadow-sm transition-colors hover:border-primary/20 hover:bg-card">
      <div
        className={cn(
          "flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border/50 bg-background shadow-sm",
          !plugin.enabled && "bg-muted/40",
        )}
      >
        {imageUrl ? (
          <img
            src={imageUrl}
            alt=""
            className="size-8 object-contain"
            loading="lazy"
          />
        ) : (
          <Puzzle
            className={cn(
              "size-5",
              plugin.enabled ? "text-primary" : "text-muted-foreground",
            )}
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-[15px] font-semibold leading-5">
            {plugin.name}
          </h3>
        </div>
        <p className="mt-1 line-clamp-1 text-sm leading-5 text-muted-foreground">
          {plugin.description}
        </p>
        {surfaceBadges.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {surfaceBadges.map((badge) => (
              <span
                key={badge}
                className="rounded-md border border-border/60 bg-muted/35 px-1.5 py-0.5 text-[11px] font-medium leading-4 text-muted-foreground"
              >
                {badge}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {hasConfig && hubPlugin && (
          <button
            type="button"
            aria-label={`配置 ${plugin.name}`}
            onClick={() => onConfigure(hubPlugin)}
            className="flex size-8 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Settings2 className="size-4" />
          </button>
        )}
        <span
          title={statusTitle}
          className={cn(
            "flex size-8 items-center justify-center rounded-lg bg-muted/55 transition-colors",
            plugin.error
              ? "text-rose-500"
              : plugin.enabled
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
                : "text-foreground hover:bg-muted",
          )}
        >
          {plugin.error ? (
            <XCircle className="size-5" />
          ) : plugin.enabled ? (
            <CheckCircle className="size-5" />
          ) : (
            <Plus className="size-5" />
          )}
        </span>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────

export default function PluginsPage() {
  const { t } = useI18n();
  const openCreatePluginChat = useOpenCreatePluginChat();
  const [initialState] = useState(getInitialState);
  const [activeTab, setActiveTab] = useState<PluginsTab>(initialState.tab);
  const [skillView, setSkillView] = useState<SkillView>(initialState.skillView);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [hubPlugins, setHubPlugins] = useState<HubPluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [configTarget, setConfigTarget] = useState<HubPluginInfo | null>(null);
  const [pluginQuery, setPluginQuery] = useState("");
  const [pluginAuthorFilter, setPluginAuthorFilter] = useState("all");
  const [pluginStatusFilter, setPluginStatusFilter] =
    useState<PluginStatusFilter>("all");

  useEffect(() => {
    const onHash = () => {
      const next = getInitialState();
      setActiveTab(next.tab);
      setSkillView(next.skillView);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const switchTab = useCallback((tab: PluginsTab) => {
    setActiveTab(tab);
    if (tab === "skills") {
      setSkillView("directory");
    }
    const hash = window.location.hash;
    const base = hash.split("?")[0] ?? "";
    window.location.hash = tab === "plugins" ? base : `${base}?tab=packs`;
  }, []);

  const switchSkillView = useCallback((view: SkillView) => {
    setActiveTab("skills");
    setSkillView(view);
    const hash = window.location.hash;
    const base = hash.split("?")[0] ?? "";
    window.location.hash =
      view === "directory" ? `${base}?tab=packs` : `${base}?tab=skill-packs`;
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [legacy, hub] = await Promise.all([
        listPlugins().catch(() => [] as PluginInfo[]),
        hubListPlugins().catch(() => [] as HubPluginInfo[]),
      ]);
      setPlugins(legacy);
      setHubPlugins(hub);
    } catch (e) {
      swallow(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const pluginEntries = useMemo<PluginEntry[]>(() => {
    const hubEntries = hubPlugins
      .filter((plugin) => plugin.id !== "openproject-pm")
      .map((plugin) => ({ plugin, source: "hub" as const }));
    const legacyEntries = plugins.map((plugin) => ({
      plugin,
      source: "legacy" as const,
    }));
    return [...hubEntries, ...legacyEntries].sort((a, b) =>
      a.plugin.name.localeCompare(b.plugin.name),
    );
  }, [hubPlugins, plugins]);

  const pluginAuthors = useMemo(() => {
    return Array.from(
      new Set(pluginEntries.map(({ plugin }) => plugin.author).filter(Boolean)),
    ).sort((a, b) => a.localeCompare(b));
  }, [pluginEntries]);

  const filteredPluginEntries = useMemo(() => {
    const needle = pluginQuery.trim().toLowerCase();
    return pluginEntries.filter(({ plugin }) => {
      if (
        pluginAuthorFilter !== "all" &&
        plugin.author !== pluginAuthorFilter
      ) {
        return false;
      }
      if (pluginStatusFilter === "enabled" && !plugin.enabled) return false;
      if (pluginStatusFilter === "disabled" && plugin.enabled) return false;
      if (!needle) return true;
      return [
        plugin.name,
        plugin.description,
        plugin.author,
        plugin.version,
        plugin.state,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [pluginAuthorFilter, pluginEntries, pluginQuery, pluginStatusFilter]);

  const allPlugins = pluginEntries;
  if (loading) {
    return (
      <div className="workspace-panel mx-auto flex min-h-[40vh] max-w-6xl items-center justify-center rounded-lg">
        <div className="flex flex-col items-center gap-3">
          <Puzzle className="size-8 animate-pulse text-purple-500" />
          <p className="text-sm text-muted-foreground">
            {t.plugins.pageLoading}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col gap-5 px-4 py-4">
      {/* ── Tab bar ── */}
      <section className="mx-auto flex w-full max-w-6xl items-center justify-between">
        <div className="inline-flex items-center gap-1 rounded-full bg-muted/50 p-1">
          <button
            type="button"
            onClick={() => switchTab("plugins")}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === "plugins"
                ? "bg-background text-primary shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            }`}
          >
            <Puzzle className="size-3.5" />
            {t.plugins.pageTitle}
          </button>
          <button
            type="button"
            onClick={() => switchTab("skills")}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === "skills"
                ? "bg-background text-emerald-600 shadow-sm dark:text-emerald-400"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            }`}
          >
            <BoxesIcon className="size-3.5" />
            {t.plugins.tabSkillMarket}
          </button>
        </div>
        {activeTab === "plugins" && (
          <div className="hidden items-center gap-2 sm:flex">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-full px-3"
              onClick={openCreatePluginChat}
            >
              <Plus className="mr-1.5 size-4" />
              创建
            </Button>
          </div>
        )}
      </section>

      {/* ── Plugins tab content ── */}
      {activeTab === "plugins" && (
        <section className="mx-auto flex w-full max-w-6xl flex-col gap-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-center">
            <div className="relative w-full lg:max-w-[560px]">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="搜索插件"
                className="h-11 rounded-2xl border-border/60 bg-background pl-11 text-base shadow-sm"
                placeholder="搜索插件"
                value={pluginQuery}
                onChange={(event) => setPluginQuery(event.target.value)}
              />
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <select
                aria-label="按作者筛选插件"
                className="h-11 shrink-0 rounded-2xl border border-transparent bg-muted/60 px-4 text-sm font-medium outline-none transition-colors hover:bg-muted focus:border-primary/40"
                value={pluginAuthorFilter}
                onChange={(event) => setPluginAuthorFilter(event.target.value)}
              >
                <option value="all">全部作者</option>
                {pluginAuthors.map((author) => (
                  <option key={author} value={author}>
                    Built by {author}
                  </option>
                ))}
              </select>
              <select
                aria-label="按状态筛选插件"
                className="h-11 shrink-0 rounded-2xl border border-transparent bg-muted/60 px-4 text-sm font-medium outline-none transition-colors hover:bg-muted focus:border-primary/40"
                value={pluginStatusFilter}
                onChange={(event) =>
                  setPluginStatusFilter(
                    event.target.value as PluginStatusFilter,
                  )
                }
              >
                <option value="all">全部</option>
                <option value="enabled">已启用</option>
                <option value="disabled">未启用</option>
              </select>
            </div>
          </div>

          {filteredPluginEntries.length > 0 ? (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
              {filteredPluginEntries.map((entry) => (
                <PluginListItem
                  key={`${entry.source}-${entry.plugin.id}`}
                  entry={entry}
                  onConfigure={setConfigTarget}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-border/70 bg-muted/10 px-6 py-12 text-center">
              <Puzzle className="mx-auto mb-3 size-10 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">
                {allPlugins.length === 0
                  ? t.plugins.emptyTitle
                  : "没有匹配的插件"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground/60">
                {allPlugins.length === 0
                  ? t.plugins.emptyHint
                  : "换个关键词或筛选条件试试"}
              </p>
            </div>
          )}
        </section>
      )}

      {/* ── Skills tab content ── */}
      {activeTab === "skills" && (
        <LocalSkillDirectoryPanel
          allButtonPosition="end"
          onDirectorySelect={() => switchSkillView("directory")}
          onSkillPacksSelect={() => switchSkillView("packs")}
          skillPacksContent={<SkillPacksTab variant="embedded" />}
          skillPacksSelected={skillView === "packs"}
        />
      )}

      {/* ── Config dialog ── */}
      {configTarget && (
        <HubPluginConfigDialog
          plugin={configTarget}
          open={true}
          onOpenChange={(open) => {
            if (!open) setConfigTarget(null);
          }}
        />
      )}
    </div>
  );
}
