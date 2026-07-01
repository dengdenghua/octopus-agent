import { useCallback, useEffect, useState } from "react";
import { Cloud, Info, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { listRegistryPlugins, type RegistryPlugin } from "@/core/registry/api";
import { cn } from "@/lib/utils";

// 云端插件:从公网 registry 浏览插件资产(kind=code · codex-plugin 集成说明)。
// 只读——沿用 octopus_runtime.materialize.SAFE_TYPES 的安全边界(只有声明式
// prompt-pack 才可一键落地),插件类暂不提供一键安装,先可见可查。
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
    <div className="min-h-[400px] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Cloud className="size-4 text-primary" />
        <span className="text-sm font-medium">云端插件 · registry 浏览</span>
        <span className="text-xs text-muted-foreground">
          {filtered.length}/{plugins.length}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索插件"
            className="h-8 w-44 rounded-md border border-border/70 bg-background px-2 text-sm outline-none focus:border-primary/50"
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

      <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        <span>
          插件类资产标记为可执行集成(kind=code),为安全暂不支持一键安装，先供浏览了解。
        </span>
      </div>

      {error ? (
        <div className="mb-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex min-h-[200px] items-center justify-center text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {filtered.map((plugin) => (
            <div
              key={plugin.id}
              className="rounded-lg border border-border/60 bg-card/40 p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">
                    {plugin.name}
                  </div>
                  {plugin.category ? (
                    <div className="mt-0.5 text-xs text-primary">
                      {plugin.category}
                    </div>
                  ) : null}
                </div>
              </div>
              <p className="mt-1.5 line-clamp-3 text-xs text-muted-foreground">
                {plugin.description}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
