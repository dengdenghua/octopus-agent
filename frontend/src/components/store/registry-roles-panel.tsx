import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Download, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  installRegistryRole,
  listRegistryRoles,
  type RegistryRole,
} from "@/core/registry/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import { getBackendBaseURL } from "@/core/config";

import { RegistryAssetCard } from "./registry-asset-card";

function registryAssetUrl(value?: string | null): string | null {
  if (!value || /^https?:\/\//i.test(value)) return null;
  return `${getBackendBaseURL()}${value.startsWith("/") ? value : `/${value}`}`;
}

// 角色商城:从公网 registry 浏览 / 安装角色资产(role + twin-role · 数字分身岗位模板)。
// 安装即在本地 scaffold 一个可用 agent(profile.jsonc + agent-core/SOUL.md),下次刷新
// 角色库即可见。卡片 + 分类筛选栏对齐本地角色库(agent-world-unified 的 AgentsTab)的
// 排版,保持商城/本地观感一致。

const CATEGORY_FILTERS = [
  "all",
  "assistant",
  "coder",
  "researcher",
  "creative",
  "automation",
  "specialist",
  "financial",
  "digital-twin",
] as const;

export function RegistryRolesPanel() {
  const { t } = useI18n();
  const [roles, setRoles] = useState<RegistryRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] =
    useState<(typeof CATEGORY_FILTERS)[number]>("all");
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installed, setInstalled] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRegistryRoles({ limit: 400 });
      setRoles(res.roles);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>([["all", roles.length]]);
    for (const role of roles) {
      const key = role.category || "specialist";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [roles]);

  const q = query.trim().toLowerCase();
  const filtered = roles.filter((r) => {
    // 排除第三方 CLI 伙伴角色(registry_local_ 或 role/local_ 前缀),避免商城展示本地重复角色
    if (
      r.id.startsWith("registry_local_") ||
      r.id.startsWith("role/local_")
    )
      return false;
    if (
      activeCategory !== "all" &&
      (r.category || "specialist") !== activeCategory
    )
      return false;
    if (!q) return true;
    return (
      r.name.toLowerCase().includes(q) ||
      r.description.toLowerCase().includes(q) ||
      r.id.toLowerCase().includes(q)
    );
  });

  const onInstall = async (role: RegistryRole) => {
    setInstalling((m) => ({ ...m, [role.id]: true }));
    setError(null);
    try {
      await installRegistryRole(role.id);
      setInstalled((m) => ({ ...m, [role.id]: true }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling((m) => ({ ...m, [role.id]: false }));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div
          data-testid="registry-roles-category-scroll"
          className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 pr-1 [scrollbar-width:none] [-webkit-overflow-scrolling:touch] [&::-webkit-scrollbar]:hidden"
        >
          {CATEGORY_FILTERS.map((category) => {
            const count = categoryCounts.get(category) ?? 0;
            const label =
              category === "all"
                ? t.agentWorld.categories.all
                : category === "digital-twin"
                  ? t.store.categoryDigitalTwin
                  : (t.agentWorld.categories[category] ?? category);
            return (
              <Button
                key={category}
                type="button"
                variant={activeCategory === category ? "secondary" : "outline"}
                size="sm"
                onClick={() => setActiveCategory(category)}
                className={cn(
                  "h-8 shrink-0 px-2.5 text-xs",
                  activeCategory === category &&
                    "border-primary/35 bg-primary/10 text-foreground",
                )}
              >
                {label}
                {category !== "all" && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    {count}
                  </span>
                )}
              </Button>
            );
          })}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-xs text-muted-foreground">
            {filtered.length}/{roles.length}
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.store.searchRolesPlaceholder}
            aria-label={t.store.searchRolesPlaceholder}
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
          {filtered.map((role) => {
            const done = installed[role.id];
            const busy = installing[role.id];
            return (
              <RegistryAssetCard
                key={role.id}
                name={role.name}
                description={role.description}
                category={role.category}
                categoryLabel={
                  role.type === "twin-role"
                    ? t.store.categoryDigitalTwin
                    : (t.agentWorld.categories[
                        role.category as keyof typeof t.agentWorld.categories
                      ] ??
                      role.category ??
                      undefined)
                }
                typeLabel={
                  role.type === "twin-role"
                    ? t.store.typeLabelTwinRole
                    : t.store.typeLabelStore
                }
                iconUrl={registryAssetUrl(role.logo_url || role.icon_url)}
                iconText={role.icon || "🎭"}
                actionSlot={
                  <Button
                    size="sm"
                    variant={done ? "outline" : "default"}
                    className="h-7 rounded-sm px-3 text-xs"
                    disabled={busy || done}
                    onClick={() => void onInstall(role)}
                  >
                    {busy ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : done ? (
                      <Check className="mr-1 h-3 w-3" />
                    ) : (
                      <Download className="mr-1 h-3 w-3" />
                    )}
                    {busy
                      ? t.store.installing
                      : done
                        ? t.store.installed
                        : t.store.install}
                  </Button>
                }
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
