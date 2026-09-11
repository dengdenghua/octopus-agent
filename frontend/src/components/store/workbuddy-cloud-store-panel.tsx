import { agentCreationRoute } from "@/core/agents/creation-route";
import { EmployeeBlueprints } from "./employee-blueprints";
import { PixelAgentAvatar } from "./pixel-agent-avatar";
import { DIGITAL_EMPLOYEE_GROUPS, selectDigitalEmployees } from "./digital-employee-catalog";
import { taskWorkspaceRoute } from "@/core/router/task-workspace-route";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { deleteAgent, listAgents } from "@/core/agents/api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, Users, Trash2, Plus, MoreHorizontal, MessageSquare } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  listCloudStoreCategories,
  listCloudStoreExperts,
  type CloudExpertAgent,
  type CloudStoreCategory,
} from "@/core/agents/agent-world-api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

// 商城(替换第三方 octoapk 角色商城) → WorkBuddy 专家商城 421 位云端源。
// 数据来自后端 /api/agent-market/cloud/store(见
// runtime/platform/plugins/cloud_expert_store.py + 发布脚本 publish-cloud.py)。

const TYPE_STYLE = {
  agent: { badge: "bg-primary/10 text-primary", label: "expert" },
  team: {
    badge: "bg-chart-3/10 text-chart-3 dark:text-chart-3",
    label: "team",
  },
} as const;

/** 首屏渲染上限 + 「加载更多」步长(避免 421 张带图卡片一次性全量渲染)。 */
const PAGE_SIZE = 60;
const EMBEDDED_PAGE_SIZE = 24;

export type WorkBuddyCloudStoreKind = "agent" | "team";

export interface WorkBuddyCloudStorePanelProps {
  digitalEmployeesOnly?: boolean;
  /** 外层人才市场的全局搜索词。 */
  searchQuery?: string;
  /** 固定只看专家或专家团；不传时保留原来的面板内切换。 */
  kind?: WorkBuddyCloudStoreKind;
  /** 嵌入人才市场时隐藏重复标题/搜索，并采用更舒展的卡片密度。 */
  embedded?: boolean;
  /** 聚合目录中可隐藏角色/角色团切换，让两者混排并只保留领域筛选。 */
  showTypeFilter?: boolean;
  /** 聚合目录可只提供一个专家团开关，避免恢复完整的类型筛选层。 */
  showTeamFilter?: boolean;
  /** 安装成功后通知外层刷新“角色库”。 */
  onInstalled?: (expert: CloudExpertAgent) => void;
}

/** 安装分步:后端接口为单次 POST,无分步回调,前端按阶段展示文案。 */


function ExpertDetailDialog({
  expert,
  open,
  onOpenChange,
  onInstall,
  onUninstall,
  onStartChat,
  installing,
}: {
  expert: CloudExpertAgent;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInstall: (expert: CloudExpertAgent) => void;
  onUninstall: (expert: CloudExpertAgent) => void;
  onStartChat: (expert: CloudExpertAgent) => void;
  installing: boolean;
}) {
  const { t } = useI18n();
  const isTeam = !!expert.is_team;
  const typeStyle = isTeam ? TYPE_STYLE.team : TYPE_STYLE.agent;
  const prompts = expert.quick_prompts?.filter(Boolean) ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <div className="flex items-start gap-3 pr-6">
            <PixelAgentAvatar id={expert.id} name={`${expert.display_name} ${expert.profession}`} team={isTeam} className="size-12" />
            <div className="min-w-0">
              <DialogTitle className="text-base">
                {t.store.detailTitle(expert.display_name)}
              </DialogTitle>
              <DialogDescription className="mt-0.5 line-clamp-2 text-ui-caption">
                {expert.profession || expert.description}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[50vh] pr-3">
          <div className="flex flex-col gap-3">
            {expert.description ? (
              <div>
                <p className="text-ui-caption font-medium text-muted-foreground">
                  {t.store.detailDescription}
                </p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {expert.description}
                </p>
              </div>
            ) : null}

            {expert.tags.length > 0 ? (
              <div>
                <p className="mb-1 text-ui-caption font-medium text-muted-foreground">
                  {t.store.detailTags}
                </p>
                <div className="flex flex-wrap gap-1">
                  {expert.tags.map((tag) => (
                    <Badge
                      key={tag}
                      variant="outline"
                      className="text-[11px] font-normal text-muted-foreground"
                    >
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}

            {prompts.length > 0 ? (
              <div>
                <p className="mb-1 text-ui-caption font-medium text-muted-foreground">
                  {t.store.detailQuickPrompts}
                </p>
                <div className="flex flex-col gap-1.5">
                  {prompts.map((p, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-border-default bg-muted/40 px-2.5 py-1.5 text-ui-caption text-foreground/90"
                    >
                      {p}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </ScrollArea>

        <DialogFooter className="flex items-center justify-between gap-2">
          <Badge
            className={cn("border-transparent text-[11px]", typeStyle.badge)}
          >
            {isTeam && <Users className="mr-1 inline size-3 align-[-2px]" />}
            {isTeam ? t.store.expertTypeTeam : t.store.expertTypeAgent}
          </Badge>
          <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant={expert.is_installed ? "outline" : "default"}
            className="h-8 rounded-sm px-3 text-ui-caption"
            disabled={installing}
            onClick={() => expert.is_installed ? onStartChat(expert) : onInstall(expert)}
          >
            {installing ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : expert.is_installed ? (
              <MessageSquare className="mr-1 h-3 w-3" />
            ) : (
              <Plus className="mr-1 h-3 w-3" />
            )}
            {installing
              ? t.store.addingExpert
              : expert.is_installed
                ? t.store.startExpertChat
                : t.store.detailInstall}
          </Button>
          {expert.is_installed && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon" variant="ghost" className="size-8" disabled={installing} aria-label={t.store.manageExpert}>
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={() => onUninstall(expert)}>
                  <Trash2 className="size-4" />{t.store.removeExpert}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ExpertCardSkeleton() {
  return (
    <div className="flex items-center gap-3 px-2 py-3">
      <Skeleton className="size-5 shrink-0 rounded" />
      <div className="min-w-0 flex-1 space-y-1.5"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-3 w-full" /></div>
      <Skeleton className="size-8 shrink-0 rounded" />
    </div>
  );
}

export function WorkBuddyCloudStorePanel({
  searchQuery = "",
  digitalEmployeesOnly = false,
  kind,
  embedded = false,
  showTypeFilter = true,
  showTeamFilter = false,
  onInstalled,
}: WorkBuddyCloudStorePanelProps = {}) {
  const { t } = useI18n();
  const { confirm, confirmDialog } = useConfirmDialog();
  const [experts, setExperts] = useState<CloudExpertAgent[]>([]);
  const [categories, setCategories] = useState<CloudStoreCategory[]>([]);
  const [metaCount, setMetaCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState("all");
  const [installedOnly, setInstalledOnly] = useState(false);
  const [typeFilter, setTypeFilter] = useState<"all" | "agent" | "team">("all");
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installed, setInstalled] = useState<Record<string, boolean>>({});
  // 详情弹窗 + 安装分步弹窗
  const [detailTarget, setDetailTarget] = useState<CloudExpertAgent | null>(
    null,
  );
  // 增量渲染:首屏 PAGE_SIZE,「加载更多」逐步追加
  const pageSize = embedded ? EMBEDDED_PAGE_SIZE : PAGE_SIZE;
  const [visibleCount, setVisibleCount] = useState(pageSize);
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
        setCategories(digitalEmployeesOnly ? DIGITAL_EMPLOYEE_GROUPS.filter(g => g.id !== "workplace").map(({ id, name }) => ({ id, name })) : catRes.categories);
        setMetaCount(
          (catRes.meta?.count as number | undefined) ?? storeRes.total,
        );
        // 标注已安装
        const done: Record<string, boolean> = {};
        for (const e of storeRes.agents) if (e.is_installed) done[e.id] = true;
        setInstalled((prev) => ({ ...prev, ...done }));
        setVisibleCount(pageSize);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [pageSize, digitalEmployeesOnly],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const effectiveTypeFilter =
    kind ?? (showTypeFilter || showTeamFilter ? typeFilter : "all");
  const catalogExperts = useMemo(() => digitalEmployeesOnly
    ? selectDigitalEmployees(experts.map((expert) => ({ ...expert, is_installed: installed[expert.id] ?? expert.is_installed })), installedOnly).filter(e => installedOnly || e.category_id !== "workplace")
    : experts, [digitalEmployeesOnly, experts, installed, installedOnly]);
  const categoryCounts = useMemo(() => {
    const typeScopedExperts =
      effectiveTypeFilter === "all"
        ? catalogExperts
        : catalogExperts.filter(
            (expert) =>
              (expert.is_team ? "team" : "agent") === effectiveTypeFilter,
          );
    const counts = new Map<string, number>([["all", typeScopedExperts.length]]);
    for (const e of typeScopedExperts) {
      const key = e.category_id || "all";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [effectiveTypeFilter, catalogExperts]);

  const zhName = (n?: { en?: string; zh?: string }): string =>
    n?.zh || n?.en || "";

  const externalQuery = searchQuery.trim().toLowerCase();
  const localQuery = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    return catalogExperts.filter((e) => {
      if (installedOnly && !installed[e.id]) return false;
      if (activeCategory !== "all" && (e.category_id || "") !== activeCategory)
        return false;
      if (
        effectiveTypeFilter !== "all" &&
        (e.is_team ? "team" : "agent") !== effectiveTypeFilter
      )
        return false;
      const hay = [
        e.display_name,
        e.profession || "",
        e.description,
        e.id,
        ...e.tags,
      ]
        .join(" ")
        .toLowerCase();
      if (externalQuery && !hay.includes(externalQuery)) return false;
      if (localQuery && !hay.includes(localQuery)) return false;
      return true;
    });
  }, [
    activeCategory,
    effectiveTypeFilter,
    catalogExperts,
    externalQuery,
    localQuery,
    installedOnly,
    installed,
  ]);

  useEffect(() => {
    setVisibleCount(pageSize);
  }, [
    activeCategory,
    installedOnly,
    effectiveTypeFilter,
    externalQuery,
    localQuery,
    pageSize,
  ]);

  const visible = filtered.slice(0, visibleCount);
  const hasMore = visibleCount < filtered.length;

  const onStartChat = async (expert: CloudExpertAgent) => {
    setInstalling((m) => ({ ...m, [expert.id]: true }));
    try {
      const agents = await listAgents();
      const slug = expert.id.replace(/^wb_/, "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      const matches = agents.filter((agent) => agent.name === expert.id || agent.name === slug);
      if (matches.length !== 1) throw new Error(t.store.localExpertNotFound);
      window.location.hash = taskWorkspaceRoute({ agentId: matches[0]!.name });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.store.localExpertNotFound);
    } finally {
      setInstalling((m) => ({ ...m, [expert.id]: false }));
    }
  };

  const onUninstall = async (expert: CloudExpertAgent) => {
    if (!(await confirm({
      title: t.store.removeExpertTitle(expert.display_name),
      description: t.store.removeExpertDescription,
      confirmLabel: t.store.removeExpert,
    }))) return;
    setInstalling((m) => ({ ...m, [expert.id]: true }));
    try {
      const agents = await listAgents();
      // Match the cloud store's two supported installation directory formats.
      const slug = expert.id.replace(/^wb_/, "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      const matches = agents.filter((agent) => agent.name === expert.id || agent.name === slug);
      if (matches.length !== 1) throw new Error("无法唯一确认本地专家，请刷新目录后重试");
      await deleteAgent(matches[0]!.name);
      setInstalled((m) => ({ ...m, [expert.id]: false }));
      setExperts((items) => items.map((item) => item.id === expert.id ? { ...item, is_installed: false } : item));
      setDetailTarget((item) => item?.id === expert.id ? { ...item, is_installed: false } : item);
      onInstalled?.({ ...expert, is_installed: false });
      toast.success(t.store.removeExpertSuccess(expert.display_name));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.store.removeExpertFailed);
    } finally {
      setInstalling((m) => ({ ...m, [expert.id]: false }));
    }
  };

  const onInstall = (expert: CloudExpertAgent) => {
    if (installed[expert.id] || expert.is_installed) return;
    setDetailTarget(null);
    window.location.hash = agentCreationRoute({ cloudExpertId: expert.id });
  };



  return (
    <div className="space-y-3">
      {confirmDialog}
      {/* 面板标题 */}
      {!embedded ? (
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">
            {t.store.expertsPanelTitle}
          </span>
        </div>
      ) : null}

      {/* 分类 + 类型 + 搜索 */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div
          data-testid="workbuddy-category-scroll"
          className="flex min-w-0 flex-wrap gap-1"
          role="group"
          aria-label="角色分类"
        >
          <Button
            type="button"
            size="sm"
            aria-pressed={
              !installedOnly &&
              activeCategory === "all" &&
              (!showTeamFilter || typeFilter !== "team")
            }
            variant={
              embedded
                ? "ghost"
                : activeCategory === "all" && !installedOnly
                  ? "secondary"
                  : "outline"
            }
            onClick={() => {
              setInstalledOnly(false);
              setActiveCategory("all");
              if (showTeamFilter) setTypeFilter("all");
            }}
            className={cn(
              "h-8 shrink-0 px-2.5 text-ui-caption",
              embedded &&
                "rounded-md font-normal text-muted-foreground shadow-none",
              embedded &&
                !installedOnly &&
                activeCategory === "all" &&
                (!showTeamFilter || typeFilter !== "team") &&
                "bg-muted font-medium text-foreground",
            )}
          >
            {t.store.typeAll}
            {!embedded || showTypeFilter ? (
              <span className="ml-1 text-ui-caption text-muted-foreground">
                {categoryCounts.get("all") ?? 0}
              </span>
            ) : null}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={installedOnly ? "secondary" : "ghost"}
            aria-pressed={installedOnly}
            onClick={() => { setInstalledOnly(true); setActiveCategory("all"); setTypeFilter("all"); }}
            className="h-8 px-2.5 text-ui-caption"
          >
            {t.store.detailInstalled}
          </Button>
          {digitalEmployeesOnly && <Button size="sm" variant={activeCategory === "employees" ? "secondary" : "ghost"} aria-pressed={activeCategory === "employees"} onClick={() => { setActiveCategory("employees"); setInstalledOnly(false); setTypeFilter("all"); }}>数字员工</Button>}
          {!kind && !showTypeFilter && showTeamFilter ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-pressed={typeFilter === "team"}
              onClick={() => {
                setInstalledOnly(false);
                setActiveCategory("all");
                setTypeFilter("team");
              }}
              className={cn(
                "h-8 shrink-0 rounded-md px-2.5 text-ui-caption font-normal text-muted-foreground shadow-none",
                typeFilter === "team" && "bg-muted font-medium text-foreground",
              )}
            >
              {t.store.expertTypeTeam}
            </Button>
          ) : null}
          {categories
            .filter((c) => !kind || (categoryCounts.get(c.id) ?? 0) > 0)
            .map((c) => {
              const count = categoryCounts.get(c.id) ?? 0;
              return (
                <Button
                  key={c.id}
                  aria-pressed={activeCategory === c.id}
                  type="button"
                  size="sm"
                  variant={
                    embedded
                      ? "ghost"
                      : activeCategory === c.id
                        ? "secondary"
                        : "outline"
                  }
                  onClick={() => {
                    setInstalledOnly(false);
                    setActiveCategory(c.id);
                    if (showTeamFilter) setTypeFilter("all");
                  }}
                  className={cn(
                    "h-8 shrink-0 px-2.5 text-ui-caption",
                    embedded &&
                      "rounded-md font-normal text-muted-foreground shadow-none",
                    !embedded &&
                      activeCategory === c.id &&
                      "border-primary/35 bg-primary/10 text-foreground",
                    embedded &&
                      activeCategory === c.id &&
                      "bg-muted font-medium text-foreground",
                  )}
                >
                  {zhName(c.name)}
                  {!embedded || showTypeFilter ? (
                    <span className="ml-1 text-ui-caption text-muted-foreground">
                      {count}
                    </span>
                  ) : null}
                </Button>
              );
            })}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {!kind && showTypeFilter ? (
            <div className="flex items-center gap-1">
              {(["all", "agent", "team"] as const).map((tp) => (
                <Button
                  key={tp}
                  type="button"
                  size="sm"
                  variant={typeFilter === tp ? "secondary" : "ghost"}
                  onClick={() => setTypeFilter(tp)}
                  className="h-8 px-2.5 text-ui-caption"
                >
                  {tp === "all"
                    ? t.store.typeAll
                    : tp === "team"
                      ? t.store.expertTypeTeam
                      : t.store.expertTypeAgent}
                </Button>
              ))}
            </div>
          ) : null}
          {!embedded ? (
            <span className="text-ui-caption text-muted-foreground">
              {filtered.length}/{experts.length}
            </span>
          ) : null}
          {!embedded ? (
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.store.searchExpertsPlaceholder}
              aria-label={t.store.searchExpertsPlaceholder}
              className="h-8 w-40 rounded-md border border-border-default bg-background px-2 text-sm outline-none focus:border-primary/50"
            />
          ) : null}
          {!embedded ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={loading}
              onClick={() => void load(true)}
              title={t.store.refreshTooltip}
            >
              <RefreshCw
                className={cn("size-3.5", loading && "animate-spin")}
              />
            </Button>
          ) : null}
        </div>
      </div>

      {digitalEmployeesOnly && !installedOnly && effectiveTypeFilter === "all" && (activeCategory === "all" || activeCategory === "employees") && <EmployeeBlueprints searchQuery={searchQuery || query} showCategories={activeCategory === "employees"} />}
      {activeCategory !== "employees" && <>
      {error ? (
        <div className="flex items-center justify-between gap-2 rounded-md bg-destructive/10 px-3 py-2 text-ui-caption text-destructive">
          <span className="line-clamp-2">{error}</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 shrink-0 px-2 text-ui-caption"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className="mr-1 size-3" />
            {t.store.retry}
          </Button>
        </div>
      ) : null}

      {loading ? (
        <div
          className={cn(
            "grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2",
            embedded
              ? "xl:grid-cols-3"
              : "lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5",
          )}
          aria-label={t.store.expertLoadingAria}
        >
          {Array.from({ length: embedded ? 6 : 10 }).map((_, i) => (
            <ExpertCardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <>
          <div
            className={cn(
              "grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2",
              embedded
                ? "xl:grid-cols-3"
                : "lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5",
            )}
          >
            {visible.map((expert) => {
              const isTeam = !!expert.is_team;
              const done = installed[expert.id] || expert.is_installed;
              const busy = installing[expert.id];
              return (
                <Card key={expert.id} className="flex min-w-0 flex-row items-center gap-3 rounded-md border-0 bg-transparent px-2 py-3 shadow-none hover:bg-muted/50" onClick={() => setDetailTarget(expert)}>
                  <PixelAgentAvatar id={expert.id} name={`${expert.display_name} ${expert.profession}`} team={isTeam} />
                  <button type="button" className="min-w-0 flex-1 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={expert.display_name} onClick={() => setDetailTarget(expert)}>
                    <span className="block truncate text-sm font-medium">{expert.display_name}</span>
                    <span className="mt-1 block truncate text-xs text-muted-foreground" title={expert.description}>{isTeam ? "专家团 · " : ""}{expert.profession && expert.profession !== expert.display_name ? expert.profession : expert.description}</span>
                  </button>
                  <Button size="icon" variant="ghost" className="size-8 shrink-0" disabled={busy} aria-label={done ? `管理${expert.display_name}` : t.store.addExpert} title={done ? "已添加 · 更多操作" : t.store.addExpert} onClick={(ev) => { ev.stopPropagation(); if (done) setDetailTarget(expert); else onInstall(expert); }}>
                    {busy ? <Loader2 className="size-4 animate-spin" /> : done ? <MoreHorizontal className="size-4" /> : <Plus className="size-4" />}
                  </Button>
                </Card>
              );
            })}
          </div>

          {visible.length > 0 && (
            <div className="flex justify-center">
              {hasMore ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 px-4 text-ui-caption"
                  onClick={() =>
                    setVisibleCount((c) =>
                      Math.min(c + pageSize, filtered.length),
                    )
                  }
                >
                  {t.store.loadMore}
                  <span className="ml-1 text-muted-foreground">
                    ({visibleCount}/{filtered.length})
                  </span>
                </Button>
              ) : (
                <span className="text-ui-caption text-muted-foreground">
                  {t.store.noMoreItems}
                </span>
              )}
            </div>
          )}
        </>
      )}

      {!loading && !error && filtered.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">
          <p>{externalQuery || localQuery ? "没有匹配的智能体，请调整搜索词。" : installedOnly ? "暂无已添加的智能体" : effectiveTypeFilter === "team" ? "暂无可展示的专家团" : "该分类暂无智能体"}</p>
          <Button variant="ghost" size="sm" className="mt-2" onClick={() => { setInstalledOnly(false); setActiveCategory("all"); setTypeFilter("all"); setQuery(""); }}>查看全部</Button>
        </div>
      ) : null}

      </>}
      {/* 详情弹窗 */}
      {detailTarget && (
        <ExpertDetailDialog
          expert={{ ...detailTarget, is_installed: installed[detailTarget.id] ?? detailTarget.is_installed }}
          open
          onOpenChange={(open) => {
            if (!open) setDetailTarget(null);
          }}
          onInstall={onInstall}
          onUninstall={(expert) => void onUninstall(expert)}
          onStartChat={(expert) => void onStartChat(expert)}
          installing={!!(detailTarget && installing[detailTarget.id])}
        />
      )}

    </div>
  );
}
