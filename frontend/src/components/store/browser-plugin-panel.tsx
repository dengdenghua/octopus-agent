import { useCallback, useEffect, useState } from "react";
import { Package, Puzzle, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { listPlugins } from "@/core/plugins/api";
import type { PluginInfo } from "@/core/plugins/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { pluginImageUrl } from "./store-utils";

export function BrowserPluginPanel() {
  const { t } = useI18n();
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listPlugins();
      setPlugins(next);
      setError(null);
    } catch (err) {
      setPlugins([]);
      setError(
        err instanceof Error
          ? err.message
          : t.unifiedStore.browserPlugins.listFailed,
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const enabledCount = plugins.filter((plugin) => plugin.enabled).length;
  const errorCount = plugins.filter((plugin) => plugin.error).length;
  const capabilityCount = plugins.reduce(
    (sum, plugin) => sum + plugin.capabilities.length,
    0,
  );

  return (
    <div className="ui-density-stack grid gap-3">
      <div className="flex flex-col gap-2 rounded-lg border border-border/60 bg-background/70 px-3 py-2 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <Package className="size-4 text-primary" />
          <h3 className="text-sm font-semibold">
            {t.unifiedStore.browserPlugins.title}
          </h3>
          <Badge variant="secondary">{plugins.length}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="rounded-lg">
            {enabledCount} {t.plugins.statEnabled}
          </Badge>
          <Badge variant="outline" className="rounded-lg">
            {errorCount} {t.plugins.statErrors}
          </Badge>
          <Badge variant="outline" className="rounded-lg">
            {capabilityCount} {t.plugins.statCapabilities}
          </Badge>
          <Button
            aria-label={t.unifiedStore.browserPlugins.refreshAria}
            disabled={loading}
            size="icon-sm"
            variant="outline"
            onClick={refresh}
          >
            <RefreshCw className={cn("size-4", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {loading ? (
        <LoadingState title={t.plugins.pageLoading} />
      ) : error ? (
        <ErrorState
          title={t.unifiedStore.browserPlugins.listFailed}
          detail={error}
          actionLabel={t.unifiedStore.browserPlugins.refreshAria}
          onAction={refresh}
        />
      ) : plugins.length ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {plugins.map((plugin) => (
            <div
              key={plugin.id}
              className={cn(
                "group min-w-0 rounded-lg border border-border/60 bg-background/70 px-3 py-2.5 transition-colors hover:border-primary/30 hover:bg-muted/15",
                plugin.error && "border-destructive/35",
                !plugin.enabled && "opacity-70",
              )}
            >
              <div className="flex min-w-0 items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-2">
                  <div className="flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border/60 bg-background">
                    {pluginImageUrl(plugin) ? (
                      <img
                        src={pluginImageUrl(plugin)!}
                        alt=""
                        className="size-5 object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <Puzzle className="size-4 text-muted-foreground" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {plugin.name}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                      <Badge
                        variant={plugin.enabled ? "secondary" : "outline"}
                        className="h-5 px-1.5 text-[10px]"
                      >
                        {plugin.enabled
                          ? t.unifiedStore.browserPlugins.enabled
                          : t.unifiedStore.browserPlugins.disabled}
                      </Badge>
                      {plugin.version && (
                        <Badge
                          variant="outline"
                          className="h-5 px-1.5 text-[10px]"
                        >
                          v{plugin.version}
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {plugin.capabilities.length}
                </span>
              </div>
              <p className="mt-2 line-clamp-1 text-xs text-muted-foreground">
                {plugin.description || plugin.author || plugin.id}
              </p>
              {plugin.error && (
                <p className="mt-2 line-clamp-2 rounded-md bg-destructive/8 px-2 py-1 text-xs text-destructive">
                  {plugin.error}
                </p>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty className="min-h-[220px]">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Puzzle />
            </EmptyMedia>
            <EmptyTitle>{t.plugins.emptyTitle}</EmptyTitle>
            <EmptyDescription>
              {t.unifiedStore.browserPlugins.title}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
    </div>
  );
}
