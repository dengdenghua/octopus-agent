import { useCallback, useEffect, useState } from "react";
import { Info, Loader2, LockIcon, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { listRegistryPlugins, type RegistryPlugin } from "@/core/registry/api";
import { cn } from "@/lib/utils";

import { RegistryAssetCard } from "./registry-asset-card";

// 插件商城:从公网 registry 浏览插件资产(kind=code · codex-plugin 集成说明)。
// 只读——沿用 octopus_runtime.materialize.SAFE_TYPES 的安全边界(只有声明式
// prompt-pack 才可一键落地),插件类暂不提供一键安装,先可见可查。卡片排版对齐
// 角色/技能商城面板(RegistryAssetCard),保持三个商城面板观感统一。
export function RegistryPluginsPanel() {
  const [plugins, setPlugins] = useState<RegistryPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRegistryPlugins({ limit: 300 });
      setPlugins(res.plugins);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? plugins.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.description.toLowerCase().includes(q) ||
          p.id.toLowerCase().includes(q),
      )
    : plugins;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <span className="text-sm font-medium">插件商城 · registry 浏览</span>
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-xs text-muted-foreground">
            {filtered.length}/{plugins.length}
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索插件"
            aria-label="搜索插件"
            className="h-8 w-44 rounded-md border border-border-default bg-background px-2 text-sm outline-none focus:border-primary/50"
          />
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        <span>
          插件类资产标记为可执行集成(kind=code),为安全暂不支持一键安装，先供浏览了解。
        </span>
      </div>

      {error ? (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex min-h-[200px] items-center justify-center text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {filtered.map((plugin) => (
            <RegistryAssetCard
              key={plugin.id}
              name={plugin.name}
              description={plugin.description}
              category={null}
              categoryLabel={plugin.category ?? undefined}
              typeLabel="商城"
              actionSlot={
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 rounded-sm px-3 text-xs"
                  disabled
                >
                  <LockIcon className="mr-1 h-3 w-3" />
                  仅浏览
                </Button>
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
