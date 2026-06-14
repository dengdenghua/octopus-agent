/* Implementation note. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  BotIcon,
  Building2Icon,
  ChevronDownIcon,
  Code2Icon,
  FingerprintIcon,
  ImportIcon,
  LandmarkIcon,
  Layers3Icon,
  Loader2Icon,
  PaletteIcon,
  PlusIcon,
  SearchCheckIcon,
  SearchIcon,
  StoreIcon,
  TargetIcon,
  WorkflowIcon,
  type LucideIcon,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EnterpriseAssetsTab } from "@/components/workspace/agents/enterprise-assets-tab";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  importAgentFromPack,
  installAgent,
  listStoreAgents,
  previewAgentPack,
  type AgentPackImportResult,
  type AgentPackPreview,
} from "@/core/agents/agent-world-api";
import type {
  Agent,
  AgentWorldAgent,
  AgentWorldCategory,
} from "@/core/agents/types";

import { AgentCard } from "./agent-card";
import { AgentRoleProfileDialog } from "./agent-role-profile-dialog";
import { AgentWorldCard } from "./agent-world-card";
import { LocalAgentConnectDialog } from "./local-agent-connect-dialog";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Types + data + helpers extracted to agent-world-data.ts
import {
  AGENT_CATEGORY_FILTERS,
  BUILTIN_LOCAL_AGENT_IDS,
  CATEGORY_ICONS,
  DIGITAL_TWIN_INDUSTRY_FILTERS,
  DIGITAL_TWIN_INDUSTRY_LABELS,
  DIGITAL_TWIN_PROFILES,
  DIGITAL_TWIN_ROLE_GROUPS,
  DIGITAL_TWIN_STATUS_STYLES,
  LOCAL_AGENT_RANK,
  LOCAL_AGENT_ORDER,
  localAgentToWorldAgent as _localAgentToWorldAgent,
  worldAgentToAgent,
  type AgentCategoryFilter,
  type DigitalTwinIndustry,
  type DigitalTwinProfile,
  type DigitalTwinRoleGroup,
  type DigitalTwinRoleTemplate,
  type DigitalTwinRoleTier,
  type DigitalTwinStatus,
} from "./agent-world-data";

function normalizeAgentDisplayKey(agent: AgentWorldAgent): string {
  return (agent.display_name || agent.name || agent.id)
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function scoreAgentForDisplay(agent: AgentWorldAgent): number {
  let score = 0;
  if (agent.is_installed) score += 1_000_000_000;
  if (BUILTIN_LOCAL_AGENT_IDS.has(agent.id)) score += 100_000_000;
  if (agent.is_official) score += 10_000_000;
  if (agent.is_featured) score += 1_000_000;
  score += Math.max(0, agent.downloads ?? 0);
  score += Math.max(0, agent.rating_count ?? 0) * 10;
  score += Math.round(Math.max(0, agent.rating ?? 0) * 100);
  return score;
}

function dedupeAgentWorldAgents(agents: AgentWorldAgent[]): AgentWorldAgent[] {
  const byName = new Map<string, AgentWorldAgent>();
  for (const agent of agents) {
    const key = normalizeAgentDisplayKey(agent);
    if (!key) continue;
    const current = byName.get(key);
    if (
      !current ||
      scoreAgentForDisplay(agent) > scoreAgentForDisplay(current)
    ) {
      byName.set(key, agent);
    }
  }
  return Array.from(byName.values());
}

// ---------------------------------------------------------------------------
// Agents Tab
// ---------------------------------------------------------------------------

function AgentPackImportPanel({ onImported }: { onImported: () => void }) {
  const { t } = useI18n();
  const [path, setPath] = useState("");
  const [preview, setPreview] = useState<AgentPackPreview | null>(null);
  const [selectedAgentName, setSelectedAgentName] = useState("");
  const [result, setResult] = useState<AgentPackImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);

  const counts: Array<[string, number]> = preview
    ? [
        ["Plugins", preview.plugins.length],
        ["Apps", preview.apps.length],
        ["Agents", preview.agents.length],
        ["Skills", preview.skills.length],
        ["Commands", preview.commands.length],
        ["MCP", preview.mcp_servers.length],
      ]
    : [];

  const handlePreview = async () => {
    const trimmed = path.trim();
    if (!trimmed) return;
    setBusy("preview");
    setError(null);
    setResult(null);
    try {
      const next = await previewAgentPack(trimmed);
      setPreview(next);
      setSelectedAgentName(next.agents[0]?.name ?? "");
    } catch (e) {
      setPreview(null);
      setSelectedAgentName("");
      setError(e instanceof Error ? e.message : "Failed to preview pack");
    } finally {
      setBusy(null);
    }
  };

  const handleImport = async () => {
    if (!preview || !selectedAgentName) return;
    setBusy("import");
    setError(null);
    try {
      const next = await importAgentFromPack({
        path: preview.root,
        agentName: selectedAgentName,
      });
      setResult(next);
      onImported();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to import agent");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 md:flex-row">
        <Input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void handlePreview();
          }}
          placeholder={t.agentWorld.importAgentPackPlaceholder}
          className="h-8 rounded-lg bg-background/80 text-xs"
        />
        <Button
          disabled={!path.trim() || busy !== null}
          size="sm"
          variant="secondary"
          onClick={() => void handlePreview()}
        >
          {busy === "preview" && (
            <Loader2Icon className="h-4 w-4 animate-spin" />
          )}
          {t.agentWorld.previewAgentPack}
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/25 bg-destructive/8 px-3 py-2 text-xs text-destructive">
          <AlertCircleIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {preview && (
        <div className="space-y-3 rounded-lg border border-border/60 bg-background/70 p-3">
          <div className="flex flex-wrap gap-2">
            {counts.map(([label, count]) => (
              <Badge key={label} variant="secondary">
                {label} · {count}
              </Badge>
            ))}
          </div>
          {preview.warnings.length > 0 && (
            <div className="rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
              {preview.warnings.slice(0, 3).join("；")}
            </div>
          )}
          {preview.agents.length > 0 ? (
            <div className="grid gap-2 md:grid-cols-[1fr_auto]">
              <select
                value={selectedAgentName}
                onChange={(event) => setSelectedAgentName(event.target.value)}
                className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
              >
                {preview.agents.map((agent) => (
                  <option key={agent.id} value={agent.name}>
                    {agent.name}
                    {agent.description ? ` - ${agent.description}` : ""}
                  </option>
                ))}
              </select>
              <Button
                disabled={!selectedAgentName || busy !== null}
                onClick={() => void handleImport()}
              >
                {busy === "import" && (
                  <Loader2Icon className="h-4 w-4 animate-spin" />
                )}
                {t.agentWorld.importSelectedAgent}
              </Button>
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">
              {t.agentWorld.noImportableAgents}
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/8 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
          {t.agentWorld.importedAgent(result.agent_name, result.agent_path)}
        </div>
      )}
    </div>
  );
}

function AgentsTab({
  agents,
  filteredAgents,
  loading,
  activeCategory,
  categoryCounts,
  onCategoryChange,
  onSelectAgent,
  onInstallChange,
}: {
  agents: AgentWorldAgent[];
  filteredAgents: AgentWorldAgent[];
  loading: boolean;
  activeCategory: AgentCategoryFilter;
  categoryCounts: Map<AgentCategoryFilter, number>;
  onCategoryChange: (category: AgentCategoryFilter) => void;
  onSelectAgent: (agent: AgentWorldAgent) => void;
  onInstallChange: () => void;
}) {
  const { t } = useI18n();
  const [installingAll, setInstallingAll] = useState(false);
  const [confirmInstallAll, setConfirmInstallAll] = useState(false);
  const visibleAgents = useMemo(
    () =>
      filteredAgents.slice().sort((a, b) => {
        if (a.is_installed !== b.is_installed) {
          return a.is_installed ? -1 : 1;
        }
        const rankA = LOCAL_AGENT_RANK.get(a.id) ?? Number.MAX_SAFE_INTEGER;
        const rankB = LOCAL_AGENT_RANK.get(b.id) ?? Number.MAX_SAFE_INTEGER;
        if (rankA !== rankB) return rankA - rankB;
        return a.display_name.localeCompare(b.display_name);
      }),
    [filteredAgents],
  );
  const installedCount = useMemo(
    () => agents.filter((agent) => agent.is_installed).length,
    [agents],
  );
  const installableAgents = useMemo(
    () => visibleAgents.filter((agent) => !agent.is_installed),
    [visibleAgents],
  );
  const installableCount = agents.length - installedCount;

  useEffect(() => {
    setConfirmInstallAll(false);
  }, [activeCategory, installableAgents.length]);

  const handleInstallAll = async () => {
    if (installingAll || installableAgents.length === 0) return;
    if (!confirmInstallAll) {
      setConfirmInstallAll(true);
      return;
    }
    setInstallingAll(true);
    let installed = 0;
    let failed = 0;
    for (const agent of installableAgents) {
      try {
        await installAgent(agent.id);
        installed += 1;
      } catch (error) {
        failed += 1;
        swallow(error);
      }
    }
    setInstallingAll(false);
    setConfirmInstallAll(false);
    onInstallChange();
    if (installed > 0) {
      toast.success(
        failed > 0
          ? `已加入 ${installed} 个角色，${failed} 个失败`
          : `已加入 ${installed} 个角色`,
      );
    } else if (failed > 0) {
      toast.error("安装失败，请稍后重试");
    }
  };

  if (loading) {
    return (
      <div data-testid="agents-loading-skeleton" className="space-y-3">
        <div className="h-8 w-full animate-pulse rounded-lg bg-muted" />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="h-32 animate-pulse bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1 rounded-lg border border-border/60 bg-muted/12 px-3 py-2 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <BotIcon className="h-4 w-4 shrink-0 text-primary/75" />
          <div className="text-sm font-semibold">角色库</div>
        </div>
        <div className="text-xs text-muted-foreground">
          挑选可直接出场的岗位角色；每张卡片代表它的职责、语气和可调用能力。
        </div>
      </div>
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <div
            data-testid="agents-category-scroll"
            className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 pr-1 [scrollbar-width:none] [-webkit-overflow-scrolling:touch] [&::-webkit-scrollbar]:hidden"
          >
            {AGENT_CATEGORY_FILTERS.map((category) => {
              const CategoryIcon = CATEGORY_ICONS[category];
              const count = categoryCounts.get(category) ?? 0;
              const label =
                category === "all"
                  ? t.agentWorld.categories.all
                  : (t.agentWorld.categories[category] ?? category);
              return (
                <Button
                  key={category}
                  type="button"
                  variant={
                    activeCategory === category ? "secondary" : "outline"
                  }
                  size="sm"
                  onClick={() => onCategoryChange(category)}
                  className={cn(
                    "h-8 shrink-0 rounded-lg px-2.5 text-xs",
                    activeCategory === category &&
                      "border-primary/35 bg-primary/10 text-foreground",
                  )}
                >
                  <CategoryIcon className="mr-1.5 h-3.5 w-3.5" />
                  {label}
                  <span className="ml-1 text-[10px] text-muted-foreground">
                    {count}
                  </span>
                </Button>
              );
            })}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground md:justify-end">
          <span className="inline-flex h-8 items-center rounded-lg border border-border/50 bg-background/65 px-2.5">
            <span className="text-muted-foreground/80">已加入</span>
            <span className="ml-1 font-medium text-foreground">
              {installedCount}
            </span>
          </span>
          <span className="inline-flex h-8 items-center rounded-lg border border-border/50 bg-background/65 px-2.5">
            <span className="text-muted-foreground/80">可加入</span>
            <span className="ml-1 font-medium text-foreground">
              {Math.max(0, installableCount)}
            </span>
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-8 rounded-lg border border-border/50 bg-background/65 px-2.5 text-xs font-medium text-muted-foreground shadow-none hover:bg-muted/45 hover:text-foreground"
            disabled={installingAll || installableAgents.length === 0}
            onClick={() => void handleInstallAll()}
            title={
              confirmInstallAll
                ? `再次点击会加入当前筛选下的 ${installableAgents.length} 个角色`
                : "需要二次确认"
            }
          >
            {installingAll && (
              <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            )}
            {confirmInstallAll
              ? `确认加入 ${installableAgents.length} 个`
              : "批量加入"}
          </Button>
        </div>
      </div>

      {visibleAgents.length > 0 ? (
        <div
          data-testid="agents-card-grid"
          className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
        >
          {visibleAgents.map((agent) =>
            agent.is_installed ? (
              <AgentCard
                key={agent.id}
                agent={worldAgentToAgent(agent)}
                isDefault={
                  agent.is_official || BUILTIN_LOCAL_AGENT_IDS.has(agent.id)
                }
                onSelect={() => onSelectAgent(agent)}
              />
            ) : (
              <AgentWorldCard
                key={agent.id}
                agent={agent}
                onSelect={onSelectAgent}
                onInstallChange={onInstallChange}
              />
            ),
          )}
        </div>
      ) : (
        <div
          data-testid="agents-empty-state"
          className="flex flex-col items-center py-16"
        >
          <StoreIcon className="text-muted-foreground/30 mb-3 h-10 w-10" />
          <p className="text-muted-foreground text-sm">
            {t.agentWorld.noAgentsFound}
          </p>
        </div>
      )}
    </div>
  );
}

function DigitalTwinsTab({
  onCreate,
  onCreateRole,
  query,
}: {
  onCreate: () => void;
  onCreateRole: (role: DigitalTwinRoleTemplate) => void;
  query: string;
}) {
  const [activeIndustry, setActiveIndustry] =
    useState<DigitalTwinIndustry>("all");
  const industryCounts = useMemo(() => {
    const counts = new Map<DigitalTwinIndustry, number>([["all", 0]]);
    for (const group of DIGITAL_TWIN_ROLE_GROUPS) {
      counts.set(
        group.industry,
        (counts.get(group.industry) ?? 0) + group.roles.length,
      );
      counts.set("all", (counts.get("all") ?? 0) + group.roles.length);
    }
    return counts;
  }, []);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredRoleGroups = useMemo(() => {
    const groups =
      activeIndustry === "all"
        ? DIGITAL_TWIN_ROLE_GROUPS
        : DIGITAL_TWIN_ROLE_GROUPS.filter(
            (group) => group.industry === activeIndustry,
          );
    if (!normalizedQuery) return groups;
    return groups
      .map((group) => ({
        ...group,
        roles: group.roles.filter((role) =>
          [group.title, role.name, role.focus, role.compound ?? ""]
            .join(" ")
            .toLowerCase()
            .includes(normalizedQuery),
        ),
      }))
      .filter((group) => group.roles.length > 0);
  }, [activeIndustry, normalizedQuery]);
  const visibleRoleCount = filteredRoleGroups.reduce(
    (sum, group) => sum + group.roles.length,
    0,
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1 rounded-lg border border-border/60 bg-muted/12 px-3 py-2 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <FingerprintIcon className="h-4 w-4 shrink-0 text-primary/75" />
          <div className="text-sm font-semibold">数字分身</div>
        </div>
        <div className="text-xs text-muted-foreground">
          为真实岗位或个人建立可托付的角色档案：背景、口吻、资料来源和行动边界都会进入设定。
        </div>
      </div>

      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex gap-1.5 overflow-x-auto pb-1 pr-1">
            {DIGITAL_TWIN_INDUSTRY_FILTERS.map((industry) => (
              <Button
                key={industry}
                type="button"
                variant={activeIndustry === industry ? "secondary" : "outline"}
                size="sm"
                onClick={() => setActiveIndustry(industry)}
                className={cn(
                  "h-8 shrink-0 rounded-lg px-2.5 text-xs",
                  activeIndustry === industry &&
                    "border-primary/35 bg-primary/10 text-foreground",
                )}
              >
                <FingerprintIcon className="mr-1.5 h-3.5 w-3.5" />
                {DIGITAL_TWIN_INDUSTRY_LABELS[industry]}
                <span className="ml-1 text-[10px] text-muted-foreground">
                  {industryCounts.get(industry) ?? 0}
                </span>
              </Button>
            ))}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground md:justify-end">
          <span className="inline-flex h-8 items-center rounded-lg border border-border/50 bg-background/65 px-2.5">
            <span className="text-muted-foreground/80">模板</span>
            <span className="ml-1 font-medium text-foreground">
              {visibleRoleCount}
            </span>
          </span>
          <span className="inline-flex h-8 items-center rounded-lg border border-border/50 bg-background/65 px-2.5">
            <span className="text-muted-foreground/80">分身</span>
            <span className="ml-1 font-medium text-foreground">
              {DIGITAL_TWIN_PROFILES.length}
            </span>
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-8 rounded-lg border border-border/50 bg-background/65 px-2.5 text-xs font-medium text-muted-foreground shadow-none hover:bg-muted/45 hover:text-foreground"
            onClick={onCreate}
          >
            <PlusIcon className="mr-1.5 h-3.5 w-3.5" />
            新建分身
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {DIGITAL_TWIN_PROFILES.map((profile) => {
          const ProfileIcon = profile.icon;
          return (
            <Card
              key={profile.id}
              className="flex min-h-[96px] flex-col overflow-hidden rounded-lg border-border/60 bg-background/72 py-0 shadow-sm shadow-black/[0.02]"
            >
              <div className="flex flex-1 flex-col p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border text-xs font-semibold",
                        profile.accentClassName,
                      )}
                    >
                      {profile.initials}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">
                        {profile.name}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-muted-foreground">
                        {profile.role}
                      </div>
                    </div>
                  </div>
                  <Badge
                    variant="secondary"
                    className={cn(
                      "h-6 shrink-0 rounded-md border px-2 text-[10px] font-medium",
                      DIGITAL_TWIN_STATUS_STYLES[profile.status],
                    )}
                  >
                    {profile.statusLabel}
                  </Badge>
                </div>

                <p className="mt-1.5 line-clamp-1 text-xs leading-5 text-muted-foreground">
                  {profile.description}
                </p>

                <div className="mt-1.5 flex min-w-0 items-center gap-2 rounded-md border border-border/45 bg-muted/8 px-2 py-1 text-[11px] text-muted-foreground">
                  <ProfileIcon className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">
                    {profile.sources}
                  </span>
                  <span className="h-3 w-px shrink-0 bg-border/70" />
                  <span className="min-w-0 flex-1 truncate">
                    {profile.boundary}
                  </span>
                  <span className="h-3 w-px shrink-0 bg-border/70" />
                  <span className="hidden min-w-0 flex-1 truncate xl:block">
                    {profile.tone}
                  </span>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {filteredRoleGroups.length > 0 ? (
        <div className="space-y-3">
          {filteredRoleGroups.map((group) => (
            <section key={group.id} className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold text-foreground/85">
                  {group.title}
                </h3>
                <span className="text-[11px] text-muted-foreground">
                  {group.roles.length} 个
                </span>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                {group.roles.map((role) => (
                  <button
                    key={role.id}
                    type="button"
                    onClick={() => onCreateRole(role)}
                    className="group flex min-h-[132px] cursor-pointer flex-col overflow-hidden rounded-lg border border-border/60 bg-background/72 py-0 text-left shadow-sm shadow-black/[0.02] transition-colors duration-150 hover:border-primary/25 hover:bg-muted/20"
                  >
                    <span className="flex flex-1 flex-col p-3">
                      <span className="flex items-start justify-between gap-2">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border/60 bg-muted text-xs font-semibold text-muted-foreground">
                          {role.index}
                        </span>
                        <Badge
                          variant="secondary"
                          className="h-6 shrink-0 rounded-md px-2 text-[10px] font-medium"
                        >
                          {group.tier === "expert"
                            ? "专家"
                            : DIGITAL_TWIN_INDUSTRY_LABELS[group.industry]}
                        </Badge>
                      </span>
                      <span className="mt-2 truncate text-sm font-semibold leading-5">
                        {role.name}
                      </span>
                      {role.compound ? (
                        <span className="mt-1 line-clamp-1 text-[11px] text-muted-foreground">
                          {role.compound}
                        </span>
                      ) : (
                        <span className="mt-1 line-clamp-1 text-[11px] text-muted-foreground">
                          {group.title}
                        </span>
                      )}
                      <span className="mt-2 line-clamp-2 min-h-8 text-xs leading-4 text-muted-foreground">
                        {role.focus}
                      </span>
                    </span>
                    <span className="flex items-center justify-between border-t border-border/50 bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
                      <span>岗位模板</span>
                      <span className="text-primary/80 group-hover:text-primary">
                        建立分身
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center py-16">
          <StoreIcon className="text-muted-foreground/30 mb-3 h-10 w-10" />
          <p className="text-muted-foreground text-sm">没有匹配的岗位模板</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Unified Component
// ---------------------------------------------------------------------------

// 角色库(本地智能体库)暂时隐藏 —— 资产正迁往企业版 registry,本地仅保留 AOI 等
// 少量核心角色;企业版 tab 是新的浏览/安装入口。置 true 即可恢复角色库入口。
const SHOW_LOCAL_AGENT_LIBRARY = true;
// 数字分身模板已迁往企业版资产库,本地 tab 一并隐藏(前端常量待 Codex 的
// agent-world-data.ts WIP 落地后移除;后续经 SDK 从企业版消费)。
const SHOW_LOCAL_DIGITAL_TWINS = false;
// 企业版资产 tab 也隐藏:数字分身/financial 已搬企业版,但消费走「后续 SDK」,
// 现在 agents 页只展示本地角色库(9 个角色)。置 true 可恢复企业版 tab。
const SHOW_ENTERPRISE_ASSETS = false;

export function AgentWorldUnified() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  // State
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState(() => {
    // 仅角色库可见,默认且唯一入口。
    return "agents";
  });
  const [activeCategory, setActiveCategory] =
    useState<AgentCategoryFilter>("all");
  const [importOpen, setImportOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<AgentWorldAgent | null>(
    null,
  );

  // Data
  const [agents, setAgents] = useState<AgentWorldAgent[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch agents
  const fetchAgents = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listStoreAgents({
        sort_by: "downloads",
        page_size: 300,
      });
      setAgents(res.agents);
    } catch (e) {
      swallow(e);
      setAgents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAgents();
  }, [fetchAgents]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const tab = params.get("tab");
    // 仅角色库可见,任何 tab 参数都落回角色库。
    if (tab === "agents" || tab === "digital-twins" || tab === "enterprise") {
      setActiveTab("agents");
    }
    if (params.get("connect") === "local") {
      setConnectOpen(true);
    }
  }, [location.search]);

  // Filter agents
  const dedupedAgents = useMemo(() => dedupeAgentWorldAgents(agents), [agents]);

  const filteredAgents = useMemo(() => {
    let nextAgents = dedupedAgents;
    if (activeCategory !== "all") {
      nextAgents = nextAgents.filter(
        (agent) => agent.category === activeCategory,
      );
    }
    if (!searchQuery) return nextAgents;
    const query = searchQuery.toLowerCase();
    return nextAgents.filter(
      (a) =>
        a.display_name.toLowerCase().includes(query) ||
        a.description.toLowerCase().includes(query) ||
        a.author.toLowerCase().includes(query) ||
        a.tags.some((tag) => tag.toLowerCase().includes(query)),
    );
  }, [activeCategory, dedupedAgents, searchQuery]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<AgentCategoryFilter, number>([
      ["all", dedupedAgents.length],
    ]);
    for (const agent of dedupedAgents) {
      counts.set(agent.category, (counts.get(agent.category) ?? 0) + 1);
    }
    return counts;
  }, [dedupedAgents]);

  const handleSelectAgent = useCallback((agent: AgentWorldAgent) => {
    setSelectedAgent(agent);
  }, []);

  const handleInstallChange = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["agents"] });
    void fetchAgents();
  }, [fetchAgents, queryClient]);

  const handleCreateDigitalTwinRole = useCallback(
    (role: DigitalTwinRoleTemplate) => {
      const params = new URLSearchParams({
        template: "digital-twin",
        roleId: role.id,
        role: role.name,
        focus: role.focus,
      });
      if (role.compound) params.set("capability", role.compound);
      navigate(`/workspace/agents/new?${params.toString()}`);
    },
    [navigate],
  );

  return (
    <div className="relative flex size-full flex-col gap-2 px-2 pb-2 pt-2 md:px-3">
      <div className="relative flex flex-col gap-2 rounded-lg border border-border/60 bg-background/70 px-3 py-2 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <h1 className="truncate text-sm font-semibold">
            {t.agentWorld.title}
          </h1>
        </div>

        <div className="flex flex-1 flex-col gap-2 md:flex-row md:items-center md:justify-end">
          <div className="relative w-full md:max-w-[280px]">
            <SearchIcon className="text-muted-foreground absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2" />
            <Input
              data-testid="agents-search-input"
              placeholder={t.agentWorld.searchPlaceholder}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 rounded-lg border-border/60 bg-background/70 pl-8 text-xs"
            />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" className="h-8 rounded-lg shadow-none">
                <PlusIcon className="mr-1.5 h-3.5 w-3.5" />
                {t.agentWorld.addAgent}
                <ChevronDownIcon className="ml-1 h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem
                onSelect={() => navigate("/workspace/agents/new")}
              >
                <PlusIcon className="h-4 w-4" />
                {t.agentWorld.newAgent}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setImportOpen(true)}>
                <ImportIcon className="h-4 w-4" />
                {t.agentWorld.importAgentPack}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setConnectOpen(true)}>
                <BotIcon className="h-4 w-4" />
                接入本地伙伴
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Main Content */}
      <div className="workspace-panel relative flex-1 overflow-y-auto rounded-lg border border-border/60 bg-background/58 px-3 py-3 shadow-sm shadow-black/[0.02]">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="relative mb-3 h-auto gap-1.5 rounded-none bg-transparent p-0">
            {SHOW_LOCAL_AGENT_LIBRARY && (
              <TabsTrigger
                value="agents"
                className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
              >
                <BotIcon className="h-3.5 w-3.5" />
                角色库
              </TabsTrigger>
            )}
            {SHOW_LOCAL_DIGITAL_TWINS && (
              <TabsTrigger
                value="digital-twins"
                className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
              >
                <FingerprintIcon className="h-3.5 w-3.5" />
                数字分身
              </TabsTrigger>
            )}
            {SHOW_ENTERPRISE_ASSETS && (
              <TabsTrigger
                value="enterprise"
                className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
              >
                <Building2Icon className="h-3.5 w-3.5" />
                企业版
              </TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="agents" className="mt-0">
            <AgentsTab
              agents={dedupedAgents}
              filteredAgents={filteredAgents}
              loading={loading}
              activeCategory={activeCategory}
              categoryCounts={categoryCounts}
              onCategoryChange={setActiveCategory}
              onSelectAgent={handleSelectAgent}
              onInstallChange={handleInstallChange}
            />
          </TabsContent>

          <TabsContent value="digital-twins" className="mt-0">
            <DigitalTwinsTab
              onCreate={() =>
                navigate("/workspace/agents/new?template=digital-twin")
              }
              onCreateRole={handleCreateDigitalTwinRole}
              query={searchQuery}
            />
          </TabsContent>

          <TabsContent value="enterprise" className="mt-0">
            <EnterpriseAssetsTab query={searchQuery} />
          </TabsContent>
        </Tabs>
      </div>

      <AgentRoleProfileDialog
        agent={selectedAgent}
        open={Boolean(selectedAgent)}
        onInstallChange={handleInstallChange}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setSelectedAgent(null);
        }}
      />

      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="gap-3 p-4 sm:max-w-2xl">
          <DialogHeader className="pr-8">
            <DialogTitle className="flex items-center gap-2 text-base">
              <ImportIcon className="h-4 w-4 text-primary" />
              {t.agentWorld.importAgentPack}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {t.agentWorld.importAgentPackDesc}
            </DialogDescription>
          </DialogHeader>
          <AgentPackImportPanel
            onImported={() => {
              void queryClient.invalidateQueries({ queryKey: ["agents"] });
              void fetchAgents();
              setActiveTab("agents");
            }}
          />
        </DialogContent>
      </Dialog>
      <LocalAgentConnectDialog
        open={connectOpen}
        onOpenChange={setConnectOpen}
      />
    </div>
  );
}
