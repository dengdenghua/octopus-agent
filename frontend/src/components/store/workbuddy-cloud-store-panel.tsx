import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  CloudDownload,
  Loader2,
  RefreshCw,
  Users,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  installCloudExpert,
  listCloudStoreCategories,
  listCloudStoreExperts,
  type CloudExpertAgent,
  type CloudStoreCategory,
} from "@/core/agents/agent-world-api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

// 商城(替换第三方 octoapk 角色商城) → WorkBuddy 专家商城 421 位云端源。
// 数据来自后端 /api/agent-market/cloud/store(见
// runtime/platform/plugins/cloud_expert_store.py + 发布脚本 publish-cloud.py)。

function avatarUrl(value?: string): string | null {
  if (!value) return null;
  if (/^https?:\/\//i.test(value)) return value;
  return `${getBackendBaseURL()}${value.startsWith("/") ? value : `/${value}`}`;
}

const TYPE_STYLE = {
  agent: { badge: "bg-primary/10 text-primary", label: "专家" },
  team: { badge: "bg-chart-3/10 text-chart-3 dark:text-chart-3", label: "专家团" },
} as const;

export function WorkBuddyCloudStorePanel() {
  const { t } = useI18n();
  const [experts, setExperts] = useState<CloudExpertAgent[]>([]);
  const [categories, setCategories] = useState<CloudStoreCategory[]>([]);
  const [metaCount, setMetaCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "agent" | "team">("all");
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installed, setInstalled] = useState<Record<string, boolean>>({});

  const load = useCallback(
    async (refresh = false) => {
      setLoading(true);
      setError(null);
      try {
        const [storeRes, catRes] = await Promise.all([
          listCloudStoreExperts({ limit: 500, refresh }),
          listCloudStoreCategories(),
        ]);
        setExperts(storeRes.agents);
        setCategories(catRes.categories);
        setMetaCount(
          (catRes.meta?.count as number | undefined) ?? storeRes.total,
        );
        // 标注已安装
        const done: Record<string, boolean> = {};
        for (const e of storeRes.agents) if (e.is_installed) done[e.id] = true;
        setInstalled((prev) => ({ ...prev, ...done }));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>([["all", experts.length]]);
    for (const e of experts) {
      const key = e.category_id || "all";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [experts]);

  const zhName = (n?: { en?: string; zh?: string }): string =>
    n?.zh || n?.en || "";

  const q = query.trim().toLowerCase();
  const filtered = experts.filter((e) => {
    if (
      activeCategory !== "all" &&
      (e.category_id || "") !== activeCategory
    )
      return false;
    if (typeFilter !== "all" && (e.is_team ? "team" : "agent") !== typeFilter)
      return false;
    if (!q) return true;
    const hay = [
      e.display_name,
      e.profession || "",
      e.description,
      e.id,
      ...e.tags,
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });

  const onInstall = async (expert: CloudExpertAgent) => {
    setInstalling((m) => ({ ...m, [expert.id]: true }));
    setError(null);
    try {
      await installCloudExpert(expert.id);
      setInstalled((m) => ({ ...m, [expert.id]: true }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling((m) => ({ ...m, [expert.id]: false }));
    }
  };

  return (
    <div className="space-y-3">
      {/* 分类 + 类型 + 搜索 */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div
          data-testid="workbuddy-category-scroll"
          className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 pr-1 [scrollbar-width:none] [-webkit-overflow-scrolling:touch] [&::-webkit-scrollbar]:hidden"
        >
          <Button
            type="button"
            size="sm"
            variant={activeCategory === "all" ? "secondary" : "outline"}
            onClick={() => setActiveCategory("all")}
            className="h-8 shrink-0 px-2.5 text-xs"
          >
            {t.agentWorld.categories.all}
            <span className="ml-1 text-xs text-muted-foreground">
              {categoryCounts.get("all") ?? 0}
            </span>
          </Button>
          {categories.map((c) => {
            const count = categoryCounts.get(c.id) ?? 0;
            return (
              <Button
                key={c.id}
                type="button"
                size="sm"
                variant={activeCategory === c.id ? "secondary" : "outline"}
                onClick={() => setActiveCategory(c.id)}
                className={cn(
                  "h-8 shrink-0 px-2.5 text-xs",
                  activeCategory === c.id &&
                    "border-primary/35 bg-primary/10 text-foreground",
                )}
              >
                {zhName(c.name)}
                <span className="ml-1 text-xs text-muted-foreground">
                  {count}
                </span>
              </Button>
            );
          })}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <div className="flex items-center gap-1">
            {(["all", "agent", "team"] as const).map((tp) => (
              <Button
                key={tp}
                type="button"
                size="sm"
                variant={typeFilter === tp ? "secondary" : "ghost"}
                onClick={() => setTypeFilter(tp)}
                className="h-8 px-2.5 text-xs"
              >
                {tp === "all"
                  ? t.agentWorld.categories.all
                  : tp === "team"
                    ? "专家团"
                    : "专家"}
              </Button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {filtered.length}/{experts.length}
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索专家 / 领域 / 标签"
            aria-label="搜索专家"
            className="h-8 w-40 rounded-md border border-border-default bg-background px-2 text-sm outline-none focus:border-primary/50"
          />
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load(true)}
            title="刷新(重新拉取云端数据)"
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
          {filtered.map((expert) => {
            const isTeam = !!expert.is_team;
            const typeStyle = isTeam ? TYPE_STYLE.team : TYPE_STYLE.agent;
            const done = installed[expert.id];
            const busy = installing[expert.id];
            const av = avatarUrl(expert.avatar_url);
            return (
              <Card
                key={expert.id}
                className="gap-2.5 py-3 transition-colors hover:border-primary/40"
              >
                <CardHeader className="flex-row items-center gap-2.5 px-3 pt-0">
                  {av ? (
                    <img
                      src={av}
                      alt=""
                      loading="lazy"
                      className="size-10 shrink-0 rounded-lg border border-border-default object-cover"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display =
                          "none";
                      }}
                    />
                  ) : (
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border-default bg-muted text-base">
                      {isTeam ? "👥" : "🧑‍💼"}
                    </div>
                  )}
                  <div className="min-w-0">
                    <CardTitle className="truncate text-sm">
                      {expert.display_name}
                    </CardTitle>
                    <CardDescription className="truncate text-xs">
                      {expert.profession || expert.description}
                    </CardDescription>
                  </div>
                </CardHeader>
                <div className="flex flex-wrap gap-1 px-3">
                  <Badge
                    className={cn(
                      "border-transparent text-[11px]",
                      typeStyle.badge,
                    )}
                  >
                    {isTeam && (
                      <Users className="mr-1 inline size-3 align-[-2px]" />
                    )}
                    {typeStyle.label}
                  </Badge>
                  {expert.tags.slice(0, 2).map((tag) => (
                    <Badge
                      key={tag}
                      variant="outline"
                      className="text-[11px] font-normal text-muted-foreground"
                    >
                      {tag}
                    </Badge>
                  ))}
                </div>
                <CardFooter className="px-3 pb-0">
                  <Button
                    size="sm"
                    variant={done ? "outline" : "default"}
                    className="h-7 rounded-sm px-3 text-xs"
                    disabled={busy || done}
                    onClick={() => void onInstall(expert)}
                  >
                    {busy ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : done ? (
                      <Check className="mr-1 h-3 w-3" />
                    ) : (
                      <CloudDownload className="mr-1 h-3 w-3" />
                    )}
                    {busy
                      ? "安装中…"
                      : done
                        ? "已安装"
                        : "安装"}
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}

      {!loading && !error && filtered.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">
          {metaCount ? `共 ${metaCount} 位专家 · 无匹配结果` : "无匹配结果"}
        </div>
      ) : null}
    </div>
  );
}
