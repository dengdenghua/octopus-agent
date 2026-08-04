import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BoxesIcon,
  ChevronLeft,
  Download,
  Plus,
  Puzzle,
  Search,
  Settings2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import {
  listPlugins,
  fetchPluginRegistryUpdates,
  hubListPlugins,
  hubGetPluginConfig,
  hubUpdatePluginConfig,
  installPluginFromRegistry,
} from "@/core/plugins/api";
import type { PluginInfo, PluginRegistryUpdates } from "@/core/plugins/types";
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

function pluginSurfaceBadges(
  entry: PluginEntry,
  t: ReturnType<typeof useI18n>["t"],
): string[] {
  if (entry.source === "hub") {
    const labels = entry.plugin.capabilities
      .map((capability) => capability.type)
      .filter(Boolean)
      .map((type) => {
        if (type === "skill") return t.plugins.badgeSkill;
        if (type === "channel") return t.plugins.badgeChannel;
        if (type === "api") return "API";
        if (type === "config_ui") return t.plugins.badgeConfig;
        return type;
      });
    return Array.from(new Set(labels)).slice(0, 4);
  }
  const surfaces = entry.plugin.smoke?.surfaces;
  const badges: string[] = [];
  if (surfaces?.mcp) badges.push("MCP");
  if (surfaces?.apps) badges.push("App");
  if (surfaces?.skills) badges.push(t.plugins.badgeSkill);
  if (surfaces?.commands) badges.push(t.plugins.badgeCommand);
  if (surfaces?.capabilities && !badges.includes("API"))
    badges.push(t.plugins.badgeCapability);
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
  const { t } = useI18n();
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
          <DialogTitle>{t.plugins.configureTitle(plugin.name)}</DialogTitle>
          <DialogDescription>
            {t.plugins.configureDescription(plugin.name)}
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
            <p className="text-sm text-muted-foreground">
              {t.plugins.configureNoConfig}
            </p>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">{t.plugins.configureCancel}</Button>
          </DialogClose>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t.plugins.configureSaving : t.plugins.configureSave}
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
  const { t } = useI18n();
  const { plugin } = entry;
  const hubPlugin = entry.source === "hub" ? entry.plugin : null;
  const imageUrl = pluginImageUrl(plugin);
  const hasConfig = Boolean(
    hubPlugin?.config_schema && Object.keys(hubPlugin.config_schema).length > 0,
  );
  const statusTitle = plugin.error
    ? plugin.error
    : plugin.enabled
      ? t.plugins.statusEnabledTooltip
      : t.plugins.statusDisabledTooltip;
  const surfaceBadges = pluginSurfaceBadges(entry, t);
  const visibleBadges = surfaceBadges.slice(0, 2);
  const hiddenBadgeCount = Math.max(
    0,
    surfaceBadges.length - visibleBadges.length,
  );

  return (
    <Card className="group flex flex-col gap-3 border border-border bg-card p-3 shadow-none transition-colors hover:bg-accent/30 sm:flex-row sm:items-center">
      <div
        className={cn(
          "flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-background",
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
      <CardContent className="min-w-0 flex-1 p-0">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-sm font-semibold leading-5">
            {plugin.name}
          </h3>
          <span
            title={statusTitle}
            className={cn(
              "shrink-0 rounded-md border px-1.5 py-0.5 text-micro font-medium",
              plugin.error
                ? "border-destructive/20 bg-destructive/10 text-destructive"
                : plugin.enabled
                  ? "border-primary/20 bg-primary/10 text-primary"
                  : "border-border-default bg-muted/35 text-muted-foreground",
            )}
          >
            {plugin.enabled
              ? t.plugins.statusEnabledTooltip
              : plugin.error
                ? t.plugins.statusError
                : t.plugins.statusDisabledTooltip}
          </span>
        </div>
        <p className="mt-0.5 line-clamp-1 text-sm leading-5 text-muted-foreground">
          {plugin.description}
        </p>
        {surfaceBadges.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {visibleBadges.map((badge) => (
              <Badge
                key={badge}
                variant="outline"
                className="h-5 rounded-md px-1.5 text-micro font-normal"
              >
                {badge}
              </Badge>
            ))}
            {hiddenBadgeCount > 0 && (
              <Badge
                variant="outline"
                className="h-5 rounded-md px-1.5 text-micro font-normal text-muted-foreground"
              >
                +{hiddenBadgeCount}
              </Badge>
            )}
          </div>
        )}
      </CardContent>
      <div className="flex shrink-0 items-center gap-1.5">
        {hasConfig && hubPlugin && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={t.plugins.configureAria(plugin.name)}
            className="h-8 rounded-md px-2.5 text-xs"
            onClick={() => onConfigure(hubPlugin)}
          >
            <Settings2 className="mr-1.5 size-3.5" />
            {t.plugins.configure}
          </Button>
        )}
      </div>
    </Card>
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
  const [registryUpdates, setRegistryUpdates] =
    useState<PluginRegistryUpdates | null>(null);
  const [registryBusy, setRegistryBusy] = useState<string | null>(null);
  const [registryMessage, setRegistryMessage] = useState<string | null>(null);
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
      const [legacy, hub, registry] = await Promise.all([
        listPlugins().catch(() => [] as PluginInfo[]),
        hubListPlugins().catch(() => [] as HubPluginInfo[]),
        fetchPluginRegistryUpdates().catch(() => null),
      ]);
      setPlugins(legacy);
      setHubPlugins(hub);
      setRegistryUpdates(registry);
    } catch (e) {
      swallow(e);
    } finally {
      setLoading(false);
    }
  }, []);

  const installRegistryEntry = useCallback(
    async (pluginId: string) => {
      setRegistryBusy(pluginId);
      setRegistryMessage(null);
      try {
        const result = await installPluginFromRegistry(pluginId);
        setRegistryMessage(
          t.plugins.registryInstalledMessage(
            result.plugin_id,
            result.version,
          ),
        );
        await loadData();
      } catch (error) {
        setRegistryMessage(
          error instanceof Error ? error.message : String(error),
        );
      } finally {
        setRegistryBusy(null);
      }
    },
    [loadData],
  );

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
          <Puzzle className="size-8 animate-pulse text-primary" />
          <p className="text-sm text-muted-foreground">
            {t.plugins.pageLoading}
          </p>
        </div>
      </div>
    );
  }

  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => switchTab(value as PluginsTab)}
      className="flex w-full flex-col gap-5 px-4 py-4"
    >
      {/* ── Tab bar ── */}
      <section className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="h-9 gap-1 pl-2 pr-3 text-muted-foreground hover:text-foreground"
          >
            <Link to="/workspace">
              <ChevronLeft className="size-4" />
              {t.plugins.backToWorkspace}
            </Link>
          </Button>
          <TabsList variant="line">
            <TabsTrigger value="plugins">
              <Puzzle className="size-3.5" />
              {t.plugins.pageTitle}
            </TabsTrigger>
            <TabsTrigger value="skills">
              <BoxesIcon className="size-3.5" />
              {t.plugins.tabSkillMarket}
            </TabsTrigger>
          </TabsList>
        </div>
        {activeTab === "plugins" && (
          <div className="hidden items-center gap-2 sm:flex">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 px-3"
              onClick={openCreatePluginChat}
            >
              <Plus className="mr-1.5 size-4" />
              {t.common.create}
            </Button>
          </div>
        )}
      </section>

      {/* ── Plugins tab content ── */}
      <TabsContent value="plugins" className="mt-0">
        <section className="mx-auto flex w-full max-w-6xl flex-col gap-6">
          {registryUpdates && registryUpdates.plugins.length > 0 ? (
            <div
              role="region"
              aria-label="Install verified registry plugin"
              className="rounded-lg border border-primary/20 bg-primary/5 p-4"
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">
                    {t.plugins.registryTitle}
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    {t.plugins.registryDescription}
                  </p>
                </div>
                <Badge variant="outline">
                  {t.plugins.registryInstallable(
                    registryUpdates.update_count +
                      registryUpdates.install_count,
                  )}
                </Badge>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {registryUpdates.plugins.map((entry) => (
                  <div
                    key={entry.id}
                    className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {entry.id} · {entry.version}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {entry.surfaces.join(" / ") ||
                          t.plugins.surfaceFallback}
                      </p>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      disabled={
                        !entry.one_click_install || registryBusy !== null
                      }
                      aria-label={t.plugins.registryInstallAria(entry.id)}
                      onClick={() => void installRegistryEntry(entry.id)}
                    >
                      <Download className="mr-1.5 size-3.5" />
                      {registryBusy === entry.id
                        ? t.plugins.registryInstalling
                        : entry.status === "update_available"
                          ? t.plugins.registryUpgrade
                          : entry.status === "current"
                            ? t.plugins.registryUpToDate
                            : t.common.install}
                    </Button>
                  </div>
                ))}
              </div>
              {registryMessage ? (
                <p className="mt-2 text-xs text-muted-foreground" role="status">
                  {registryMessage}
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-center">
            <div className="relative w-full lg:max-w-[560px]">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label={t.common.search}
                className="h-11 rounded-lg border-border bg-background pl-11 text-base shadow-none"
                placeholder={t.common.search}
                value={pluginQuery}
                onChange={(event) => setPluginQuery(event.target.value)}
              />
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <Select
                value={pluginAuthorFilter}
                onValueChange={setPluginAuthorFilter}
              >
                <SelectTrigger className="h-11 w-auto gap-2 rounded-lg bg-background shadow-none">
                  <SelectValue>
                    {pluginAuthorFilter === "all"
                      ? t.plugins.filterAllAuthors
                      : t.plugins.filterByAuthor(pluginAuthorFilter)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    {t.plugins.filterAllAuthors}
                  </SelectItem>
                  {pluginAuthors.map((author) => (
                    <SelectItem key={author} value={author}>
                      {t.plugins.filterByAuthor(author)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={pluginStatusFilter}
                onValueChange={(value) =>
                  setPluginStatusFilter(value as PluginStatusFilter)
                }
              >
                <SelectTrigger className="h-11 w-auto gap-2 rounded-lg bg-background shadow-none">
                  <SelectValue>
                    {pluginStatusFilter === "all" && t.plugins.statusAll}
                    {pluginStatusFilter === "enabled" &&
                      t.plugins.statusEnabledFilter}
                    {pluginStatusFilter === "disabled" &&
                      t.plugins.statusDisabledFilter}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t.plugins.statusAll}</SelectItem>
                  <SelectItem value="enabled">
                    {t.plugins.statusEnabledFilter}
                  </SelectItem>
                  <SelectItem value="disabled">
                    {t.plugins.statusDisabledFilter}
                  </SelectItem>
                </SelectContent>
              </Select>
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
            <div className="rounded-lg border border-dashed border-border bg-muted/10 px-6 py-12 text-center">
              <Puzzle className="mx-auto mb-3 size-10 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">
                {allPlugins.length === 0
                  ? t.plugins.emptyTitle
                  : t.plugins.noMatches}
              </p>
              <p className="mt-1 text-xs text-muted-foreground/60">
                {allPlugins.length === 0
                  ? t.plugins.emptyHint
                  : t.plugins.tryDifferentQuery}
              </p>
            </div>
          )}
        </section>
      </TabsContent>

      {/* ── Skills tab content ── */}
      <TabsContent value="skills" className="mt-0">
        <LocalSkillDirectoryPanel
          allButtonPosition="end"
          onDirectorySelect={() => switchSkillView("directory")}
          onSkillPacksSelect={() => switchSkillView("packs")}
          skillPacksContent={<SkillPacksTab variant="embedded" />}
          skillPacksSelected={skillView === "packs"}
        />
      </TabsContent>

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
    </Tabs>
  );
}
