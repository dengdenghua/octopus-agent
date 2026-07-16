import { useEffect, useMemo, useState } from "react";
import {
  ExternalLink,
  Loader2,
  Package,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { listApps, type OctopusApp } from "@/core/apps/api";
import { listPlugins } from "@/core/plugins/api";
import type { PluginInfo } from "@/core/plugins/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  type PluginRegistryItem,
  StoreErrorState,
  classifyPluginItem,
  useAppCategoryLabel,
  useOpenCreatePluginChat,
  pluginImageUrl,
  appIconUrl,
  searchablePluginItemText,
  pluginLookupKeys,
  appPluginLookupKeys,
} from "./store-utils";

export function ApplicationRegistryPanel() {
  const { t } = useI18n();
  const [apps, setApps] = useState<OctopusApp[]>([]);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const appCategoryLabel = useAppCategoryLabel();
  const openCreatePluginChat = useOpenCreatePluginChat();

  const refresh = async () => {
    setLoading(true);
    const [appsResult, pluginsResult] = await Promise.allSettled([
      listApps(),
      listPlugins(),
    ]);

    if (appsResult.status === "fulfilled") {
      setApps(appsResult.value);
    } else {
      setApps([]);
    }

    if (pluginsResult.status === "fulfilled") {
      setPlugins(pluginsResult.value);
    } else {
      setPlugins([]);
    }

    const failures = [appsResult, pluginsResult]
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason)
      .map((reason) =>
        reason instanceof Error ? reason.message : String(reason),
      );
    setError(failures.length === 2 ? failures.join("\n") : null);
    setLoading(false);
  };

  useEffect(() => {
    void refresh();
  }, []);

  const pluginByName = useMemo(() => {
    const map = new Map<string, PluginInfo>();
    for (const plugin of plugins) {
      for (const key of pluginLookupKeys(plugin)) {
        map.set(key, plugin);
      }
    }
    return map;
  }, [plugins]);

  const registryItems = useMemo<PluginRegistryItem[]>(() => {
    const appsByPluginKey = new Map<string, OctopusApp[]>();
    for (const app of apps) {
      for (const key of appPluginLookupKeys(app)) {
        const bucket = appsByPluginKey.get(key) ?? [];
        bucket.push(app);
        appsByPluginKey.set(key, bucket);
      }
    }

    const claimedApps = new Set<string>();
    const pluginItems = plugins.map((plugin) => {
      const relatedMap = new Map<string, OctopusApp>();
      for (const key of pluginLookupKeys(plugin)) {
        for (const app of appsByPluginKey.get(key) ?? []) {
          relatedMap.set(app.id, app);
          claimedApps.add(app.id);
        }
      }
      const relatedApps = [...relatedMap.values()].sort((a, b) =>
        a.name.localeCompare(b.name),
      );
      return {
        id: `plugin:${plugin.id}`,
        name: plugin.name || plugin.id,
        description: plugin.description,
        author: plugin.author,
        plugin,
        apps: relatedApps,
        localCategory: classifyPluginItem(plugin, relatedApps),
        source: "plugin" as const,
      };
    });

    const appOnlyItems = apps
      .filter((app) => !claimedApps.has(app.id))
      .map((app) => ({
        id: `app:${app.id}`,
        name: app.name || app.id,
        description: app.description,
        author: app.author,
        plugin: pluginByName.get(app.id.toLowerCase()) ?? null,
        apps: [app],
        localCategory: classifyPluginItem(null, [app]),
        source: "app" as const,
      }));

    return [...pluginItems, ...appOnlyItems].sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [apps, pluginByName, plugins]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of registryItems) {
      counts.set(item.localCategory, (counts.get(item.localCategory) ?? 0) + 1);
    }
    return counts;
  }, [registryItems]);

  const visibleItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return registryItems.filter((item) => {
      if (category !== "all" && item.localCategory !== category) return false;
      if (!needle) return true;
      return searchablePluginItemText(item).includes(needle);
    });
  }, [category, registryItems, query]);

  const enabledCount = registryItems.filter(
    (item) => item.plugin?.enabled,
  ).length;
  const actionCount = apps.reduce(
    (sum, app) => sum + (app.action_count ?? app.actions?.length ?? 0),
    0,
  );
  const capabilityCount = plugins.reduce(
    (sum, plugin) => sum + plugin.capabilities.length,
    0,
  );

  if (loading) {
    return (
      <div className="flex min-h-[360px] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t.applicationRegistry.loading}
      </div>
    );
  }

  if (error) {
    return (
      <StoreErrorState
        title={t.applicationRegistry.errorTitle}
        detail={error}
        retryLabel={t.applicationRegistry.retryLabel}
        retrying={loading}
        onRetry={() => void refresh()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <Package className="size-4 text-primary" />
          <h3 className="text-sm font-semibold">
            {t.applicationRegistry.title}
          </h3>
          <Badge variant="secondary">{registryItems.length}</Badge>
          <Button
            aria-label={t.applicationRegistry.refreshAria}
            disabled={loading}
            size="icon-sm"
            variant="ghost"
            onClick={refresh}
          >
            <RefreshCw className={cn("size-4", loading && "animate-spin")} />
          </Button>
        </div>
        <div className="flex w-full flex-col gap-2 sm:flex-row md:w-auto">
          <Button
            className="h-9"
            size="sm"
            variant="default"
            onClick={openCreatePluginChat}
          >
            <Plus className="mr-1 size-4" />
            {t.applicationRegistry.createPlugin}
          </Button>
          <div className="relative w-full md:w-[300px]">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label={t.applicationRegistry.searchAria}
              className="h-9 rounded-full pl-9"
              placeholder={t.applicationRegistry.searchPlaceholder}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
        <Badge variant="outline" className="rounded-lg">
          {enabledCount} {t.applicationRegistry.enabled}
        </Badge>
        <Badge variant="outline" className="rounded-lg">
          {capabilityCount} {t.applicationRegistry.capabilities}
        </Badge>
        <Badge variant="outline" className="rounded-lg">
          {actionCount} {t.applicationRegistry.actions}
        </Badge>
      </div>

      <div className="flex gap-1.5 overflow-x-auto pb-1">
        <Button
          size="sm"
          variant={category === "all" ? "secondary" : "ghost"}
          className="h-8 shrink-0 rounded-full px-3 text-xs"
          onClick={() => setCategory("all")}
        >
          {t.applicationRegistry.all}
          <span className="ml-1 text-muted-foreground">
            {registryItems.length}
          </span>
        </Button>
        {Object.entries(t.storeUtils.appCategoryLabels).map(([key, label]) => {
          if (key === "all") return null;
          const count = categoryCounts.get(key) ?? 0;
          if (!count) return null;
          return (
            <Button
              key={key}
              size="sm"
              variant={category === key ? "secondary" : "ghost"}
              className="h-8 shrink-0 rounded-full px-3 text-xs"
              onClick={() => setCategory(key)}
            >
              {label}
              <span className="ml-1 text-muted-foreground">{count}</span>
            </Button>
          );
        })}
      </div>

      {visibleItems.length ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {visibleItems.map((item) => {
            const primaryApp = item.apps[0] ?? null;
            const plugin = item.plugin;
            const iconUrl =
              (plugin ? pluginImageUrl(plugin) : null) ||
              (primaryApp ? appIconUrl(primaryApp) : null);
            const itemActionCount = item.apps.reduce(
              (sum, app) =>
                sum + (app.action_count ?? app.actions?.length ?? 0),
              0,
            );
            const openable = Boolean(primaryApp?.route || primaryApp?.entry);
            const title = plugin?.name || item.name;
            const subtitle =
              plugin && plugin.id !== plugin.name
                ? plugin.id
                : item.author ||
                  primaryApp?.plugin ||
                  primaryApp?.source_plugin ||
                  item.id;
            return (
              <div
                key={item.id}
                className="group min-w-0 rounded-lg border border-border-default bg-background/70 px-3 py-2.5 transition-colors hover:border-primary/30 hover:bg-muted/15"
              >
                <div className="flex items-start gap-2">
                  <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border-default bg-muted/40">
                    {iconUrl ? (
                      <img
                        alt=""
                        className="size-6 object-contain"
                        loading="lazy"
                        src={iconUrl}
                      />
                    ) : (
                      <span className="text-sm font-semibold text-muted-foreground">
                        {title.charAt(0).toUpperCase()}
                      </span>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <p className="min-w-0 flex-1 truncate text-sm font-medium">
                        {title}
                      </p>
                      {primaryApp?.schema_version && (
                        <Badge
                          variant="outline"
                          className="h-5 rounded-full px-1.5 text-[10px]"
                        >
                          v{primaryApp.schema_version}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                      {subtitle}
                    </p>
                  </div>
                </div>
                {item.description || primaryApp?.description ? (
                  <p className="mt-2 line-clamp-2 min-h-8 text-xs leading-4 text-muted-foreground">
                    {item.description || primaryApp?.description}
                  </p>
                ) : (
                  <div className="mt-2 min-h-8 text-xs leading-4 text-muted-foreground/70">
                    {t.applicationRegistry.pluginPackageOnly}
                  </div>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="secondary"
                    className="h-5 rounded-full px-2 text-[10px]"
                  >
                    {appCategoryLabel(item.localCategory)}
                  </Badge>
                  {plugin && (
                    <Badge
                      variant={plugin.enabled ? "secondary" : "outline"}
                      className="h-5 rounded-full px-2 text-[10px]"
                    >
                      {plugin.enabled
                        ? t.applicationRegistry.enabledStatus
                        : t.applicationRegistry.disabledStatus}
                    </Badge>
                  )}
                  {item.apps.length > 0 && (
                    <Badge
                      variant="outline"
                      className="h-5 rounded-full px-2 text-[10px]"
                    >
                      {item.apps.length} {t.applicationRegistry.entries}
                    </Badge>
                  )}
                  {itemActionCount > 0 && (
                    <Badge
                      variant="outline"
                      className="h-5 rounded-full px-2 text-[10px]"
                    >
                      {itemActionCount} {t.applicationRegistry.actions}
                    </Badge>
                  )}
                  {plugin && plugin.capabilities.length > 0 && (
                    <Badge
                      variant="outline"
                      className="h-5 rounded-full px-2 text-[10px]"
                    >
                      {plugin.capabilities.length}{" "}
                      {t.applicationRegistry.capabilities}
                    </Badge>
                  )}
                  {primaryApp && (primaryApp.permissions?.length ?? 0) > 0 && (
                    <Badge
                      variant="outline"
                      className="h-5 rounded-full px-2 text-[10px]"
                    >
                      {primaryApp!.permissions!.length}{" "}
                      {t.applicationRegistry.permissions}
                    </Badge>
                  )}
                </div>
                {openable ? (
                  <Button
                    className="mt-2 h-8 w-full text-xs"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const target = primaryApp?.route || primaryApp?.entry;
                      if (!target) return;
                      if (
                        target.startsWith("http://") ||
                        target.startsWith("https://")
                      ) {
                        window.open(target, "_blank", "noopener,noreferrer");
                        return;
                      }
                      window.location.hash = target.startsWith("#")
                        ? target.slice(1)
                        : target;
                    }}
                  >
                    {t.applicationRegistry.open}
                    <ExternalLink className="ml-1 size-3.5" />
                  </Button>
                ) : (
                  <div className="mt-2 text-xs text-muted-foreground/70">
                    {t.applicationRegistry.registered}
                  </div>
                )}
                {plugin?.error && (
                  <p className="mt-2 line-clamp-2 rounded-md bg-destructive/8 px-2 py-1 text-xs text-destructive">
                    {plugin.error}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-border-default bg-muted/10 p-8 text-center text-sm text-muted-foreground">
          {t.applicationRegistry.noMatches}
        </div>
      )}
    </div>
  );
}
