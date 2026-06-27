/* Implementation note. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  BoxesIcon,
  BotIcon,
  Building2Icon,
  ChevronDownIcon,
  ImportIcon,
  Loader2Icon,
  PlusIcon,
  PuzzleIcon,
  SearchIcon,
  StoreIcon,
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
import { ACTIVE_AGENT_KEY } from "@/core/agents/active";
import { emitAgentChanged } from "@/core/events";
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
import type { AgentWorldAgent } from "@/core/agents/types";

import { AgentCard } from "./agent-card";
import { AgentRoleProfileDialog } from "./agent-role-profile-dialog";
import { AgentWorldCard } from "./agent-world-card";
import { LocalAgentConnectDialog } from "./local-agent-connect-dialog";
import { LocalSkillDirectoryPanel } from "@/components/store/unified-store";
import { SkillPacksTab } from "@/components/workspace/agents/skill-packs-tab";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Types + data + helpers extracted to agent-world-data.ts
import {
  AGENT_CATEGORY_FILTERS,
  CATEGORY_ICONS,
  LOCAL_AGENT_IDS,
  LOCAL_AGENT_RANK,
  localAgentToWorldAgent as _localAgentToWorldAgent,
  worldAgentToAgent,
  type AgentCategoryFilter,
} from "./agent-world-data";

const ECHO_CHARACTER_DISPLAY_NAMES = new Set([
  "eve",
  "kane",
  "leon",
  "luna",
  "mira voss",
  "noah",
  "raven",
  "shion",
  "zero",
]);

function normalizeAgentNameKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function agentWorldIdentityKey(agent: AgentWorldAgent): string {
  const profile = agent.character_profile as
    | { name?: unknown; codename?: unknown }
    | null
    | undefined;
  const profileName =
    typeof profile?.name === "string" ? normalizeAgentNameKey(profile.name) : "";
  if (profileName) return profileName;

  const displayName = agent.display_name || agent.name || agent.id;
  const slashBaseName = displayName.split(/\s*\/\s*/)[0] ?? "";
  const slashBaseKey = normalizeAgentNameKey(slashBaseName);
  if (
    displayName.includes("/") &&
    ECHO_CHARACTER_DISPLAY_NAMES.has(slashBaseKey)
  ) {
    return slashBaseKey;
  }

  return normalizeAgentNameKey(displayName);
}

function scoreAgentForDisplay(agent: AgentWorldAgent): number {
  let score = 0;
  if (agent.is_installed) score += 1_000_000_000;
  if (LOCAL_AGENT_IDS.has(agent.id)) score += 100_000_000;
  if (agent.is_official) score += 10_000_000;
  if (agent.is_featured) score += 1_000_000;
  score += Math.max(0, agent.downloads ?? 0);
  score += Math.max(0, agent.rating_count ?? 0) * 10;
  score += Math.round(Math.max(0, agent.rating ?? 0) * 100);
  return score;
}

export function dedupeAgentWorldAgents(
  agents: AgentWorldAgent[],
): AgentWorldAgent[] {
  const byName = new Map<string, AgentWorldAgent>();
  for (const agent of agents) {
    const key = agentWorldIdentityKey(agent);
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
          ? t.agentWorldUnified.installSuccessWithFailure(installed, failed)
          : t.agentWorldUnified.installSuccess(installed),
      );
    } else if (failed > 0) {
      toast.error(t.agentWorldUnified.installFailed);
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
          <div className="text-sm font-semibold">
            {t.agentWorldUnified.roleLibrary}
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          {t.agentWorldUnified.roleLibraryDescription}
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
            <span className="text-muted-foreground/80">
              {t.agentWorldUnified.installedLabel}
            </span>
            <span className="ml-1 font-medium text-foreground">
              {installedCount}
            </span>
          </span>
          <span className="inline-flex h-8 items-center rounded-lg border border-border/50 bg-background/65 px-2.5">
            <span className="text-muted-foreground/80">
              {t.agentWorldUnified.installableLabel}
            </span>
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
                ? t.agentWorldUnified.installAllConfirmTitle(
                    installableAgents.length,
                  )
                : t.agentWorldUnified.installAllConfirmHint
            }
          >
            {installingAll && (
              <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            )}
            {confirmInstallAll
              ? t.agentWorldUnified.installAllConfirmButton(
                  installableAgents.length,
                )
              : t.agentWorldUnified.installAllButton}
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
                isDefault={agent.is_official || LOCAL_AGENT_IDS.has(agent.id)}
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

// ---------------------------------------------------------------------------
// Plugins Tab (extracted from plugins page, embedded into Hub)
// ---------------------------------------------------------------------------

import {
  listPlugins,
  hubListPlugins,
  hubGetPluginConfig,
  hubUpdatePluginConfig,
} from "@/core/plugins/api";
import type { PluginInfo, HubPluginInfo } from "@/core/plugins/types";
import { getBackendBaseURL } from "@/core/config";
import { Input as UiInput } from "@/components/ui/input";
import { Label as UiLabel } from "@/components/ui/label";
import {
  Dialog as UiDialog,
  DialogClose as UiDialogClose,
  DialogContent as UiDialogContent,
  DialogDescription as UiDialogDescription,
  DialogFooter as UiDialogFooter,
  DialogHeader as UiDialogHeader,
  DialogTitle as UiDialogTitle,
} from "@/components/ui/dialog";
import {
  CheckCircle as CheckCircleIcon,
  XCircle as XCircleIcon,
  Settings2 as Settings2Icon,
} from "lucide-react";
import { useOpenCreatePluginChat } from "@/components/store/store-utils";

type PluginEntry =
  | { plugin: HubPluginInfo; source: "hub" }
  | { plugin: PluginInfo; source: "legacy" };
type PluginStatusFilter = "all" | "enabled" | "disabled";

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
    <UiDialog open={open} onOpenChange={onOpenChange}>
      <UiDialogContent className="max-w-md">
        <UiDialogHeader>
          <UiDialogTitle>{plugin.name} 配置</UiDialogTitle>
          <UiDialogDescription>
            配置 {plugin.name} 插件的运行参数
          </UiDialogDescription>
        </UiDialogHeader>

        <div className="space-y-4 py-2">
          {properties && Object.keys(properties).length > 0 ? (
            Object.entries(properties).map(([key, prop]) => (
              <div key={key} className="space-y-1">
                <UiLabel htmlFor={`cfg-${key}`}>{prop.title || key}</UiLabel>
                {prop.description && (
                  <p className="text-xs text-muted-foreground">
                    {prop.description}
                  </p>
                )}
                <UiInput
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

        <UiDialogFooter>
          <UiDialogClose asChild>
            <Button variant="outline">取消</Button>
          </UiDialogClose>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : "保存"}
          </Button>
        </UiDialogFooter>
      </UiDialogContent>
    </UiDialog>
  );
}

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
          <PuzzleIcon
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
            <Settings2Icon className="size-4" />
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
            <XCircleIcon className="size-5" />
          ) : plugin.enabled ? (
            <CheckCircleIcon className="size-5" />
          ) : (
            <PlusIcon className="size-5" />
          )}
        </span>
      </div>
    </div>
  );
}

function PluginsTabContent({ searchQuery }: { searchQuery: string }) {
  const { t } = useI18n();
  const openCreatePluginChat = useOpenCreatePluginChat();
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [hubPlugins, setHubPlugins] = useState<HubPluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [configTarget, setConfigTarget] = useState<HubPluginInfo | null>(null);
  const [pluginQuery, setPluginQuery] = useState("");
  const [pluginAuthorFilter, setPluginAuthorFilter] = useState("all");
  const [pluginStatusFilter, setPluginStatusFilter] =
    useState<PluginStatusFilter>("all");

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

  // Sync external search (from Hub header) into plugin query
  useEffect(() => {
    if (searchQuery) setPluginQuery(searchQuery);
  }, [searchQuery]);

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

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <PuzzleIcon className="size-8 animate-pulse text-purple-500" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full lg:max-w-[320px]">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <UiInput
            aria-label="搜索插件"
            className="h-9 rounded-lg border-border/60 bg-background pl-9 text-xs"
            placeholder="搜索插件"
            value={pluginQuery}
            onChange={(event) => setPluginQuery(event.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="按作者筛选插件"
            className="h-9 shrink-0 rounded-lg border border-transparent bg-muted/60 px-3 text-xs font-medium outline-none transition-colors hover:bg-muted focus:border-primary/40"
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
            className="h-9 shrink-0 rounded-lg border border-transparent bg-muted/60 px-3 text-xs font-medium outline-none transition-colors hover:bg-muted focus:border-primary/40"
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
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-lg px-3 text-xs"
            onClick={openCreatePluginChat}
          >
            <PlusIcon className="mr-1.5 size-3.5" />
            创建
          </Button>
        </div>
      </div>

      {filteredPluginEntries.length > 0 ? (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-3">
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
          <PuzzleIcon className="mx-auto mb-3 size-10 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            {pluginEntries.length === 0
              ? t.plugins.emptyTitle
              : "没有匹配的插件"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/60">
            {pluginEntries.length === 0
              ? t.plugins.emptyHint
              : "换个关键词或筛选条件试试"}
          </p>
        </div>
      )}

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

// ---------------------------------------------------------------------------
// Main Unified Component
// ---------------------------------------------------------------------------

// Hub keeps the local, ready-to-run agents on this page. Enterprise assets can
// be re-enabled as a separate tab when that registry is connected.
const SHOW_LOCAL_AGENT_LIBRARY = true;
// Enterprise assets tab is hidden on the consumer surface for now.
const SHOW_ENTERPRISE_ASSETS = false;
// Hub only shows locally joined agents; marketplace templates stay in install flows.
const LOCAL_LIBRARY_INSTALLED_ONLY = true;
const HIDDEN_LOCAL_AGENT_IDS = new Set(["admin", "desktop_operator"]);

export function AgentWorldUnified() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  // State
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState(() => {
    const params = new URLSearchParams(location.search);
    const tab = params.get("tab");
    if (tab === "plugins") return "plugins";
    if (tab === "skills") return "skills";
    return "agents";
  });
  const [skillView, setSkillView] = useState<"directory" | "packs">("directory");
  const [activeCategory, setActiveCategory] =
    useState<AgentCategoryFilter>("all");
  const [importOpen, setImportOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<AgentWorldAgent | null>(
    null,
  );
  const hudOnly = new URLSearchParams(location.search).get("hud") === "1";

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
    if (tab === "plugins") {
      setActiveTab("plugins");
    } else if (tab === "skills" || tab === "packs" || tab === "skill-packs") {
      setActiveTab("skills");
      setSkillView(tab === "skill-packs" ? "packs" : "directory");
    } else if (tab === "agents" || tab === "enterprise") {
      setActiveTab("agents");
    }
    if (params.get("connect") === "local") {
      setConnectOpen(true);
    }
  }, [location.search]);

  // Filter agents
  const dedupedAgents = useMemo(() => {
    const visibleAgents = agents.filter(
      (agent) => !HIDDEN_LOCAL_AGENT_IDS.has(agent.id),
    );
    const deduped = dedupeAgentWorldAgents(visibleAgents);
    return LOCAL_LIBRARY_INSTALLED_ONLY
      ? deduped.filter((a) => a.is_installed)
      : deduped;
  }, [agents]);

  useEffect(() => {
    if (!hudOnly || selectedAgent || dedupedAgents.length === 0) return;
    let activeName = "";
    try {
      activeName = window.localStorage.getItem(ACTIVE_AGENT_KEY) ?? "";
    } catch (e) {
      swallow(e, "storage");
    }
    const nextAgent =
      dedupedAgents.find((agent) => agent.name === activeName) ??
      dedupedAgents[0] ??
      null;
    setSelectedAgent(nextAgent);
  }, [dedupedAgents, hudOnly, selectedAgent]);

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
  const handleSwitchAgent = useCallback((agent: AgentWorldAgent) => {
    setSelectedAgent(agent);
    emitAgentChanged(agent.name);
  }, []);

  const handleInstallChange = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["agents"] });
    void fetchAgents();
  }, [fetchAgents, queryClient]);

  const chatRouteForAgent = useCallback((agent: AgentWorldAgent | null) => {
    const name = agent?.name?.trim();
    return name
      ? `/workspace/agents/${encodeURIComponent(name)}/chats/new`
      : "/workspace/realtime/new";
  }, []);

  return (
    <div className="relative flex size-full flex-col gap-2 px-2 pb-2 pt-2 md:px-3">
      {!hudOnly && (
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
                  {t.agentWorldUnified.connectLocalPartner}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      )}

      {/* Main Content */}
      {!hudOnly && (
        <div className="workspace-panel relative flex-1 overflow-y-auto rounded-lg border border-border/60 bg-background/58 px-3 py-3 shadow-sm shadow-black/[0.02]">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="relative mb-3 h-auto gap-1.5 rounded-none bg-transparent p-0">
              {SHOW_LOCAL_AGENT_LIBRARY && (
                <TabsTrigger
                  value="agents"
                  className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
                >
                  <BotIcon className="h-3.5 w-3.5" />
                  {t.agentWorldUnified.roleLibrary}
                </TabsTrigger>
              )}
              <TabsTrigger
                value="plugins"
                className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
              >
                <PuzzleIcon className="h-3.5 w-3.5" />
                {t.plugins.pageTitle}
              </TabsTrigger>
              <TabsTrigger
                value="skills"
                className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
              >
                <BoxesIcon className="h-3.5 w-3.5" />
                {t.plugins.tabSkillMarket}
              </TabsTrigger>
              {SHOW_ENTERPRISE_ASSETS && (
                <TabsTrigger
                  value="enterprise"
                  className="h-8 flex-none rounded-lg border border-border/50 bg-muted/20 px-3 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-muted/45"
                >
                  <Building2Icon className="h-3.5 w-3.5" />
                  {t.agentWorldUnified.enterprise}
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

            <TabsContent value="plugins" className="mt-0">
              <PluginsTabContent searchQuery={searchQuery} />
            </TabsContent>

            <TabsContent value="skills" className="mt-0">
              <LocalSkillDirectoryPanel
                allButtonPosition="end"
                onDirectorySelect={() => setSkillView("directory")}
                onSkillPacksSelect={() => setSkillView("packs")}
                skillPacksContent={<SkillPacksTab variant="embedded" />}
                skillPacksSelected={skillView === "packs"}
              />
            </TabsContent>

            <TabsContent value="enterprise" className="mt-0">
              <EnterpriseAssetsTab query={searchQuery} />
            </TabsContent>
          </Tabs>
        </div>
      )}

      <AgentRoleProfileDialog
        agent={selectedAgent}
        agents={dedupedAgents}
        open={Boolean(selectedAgent)}
        onInstallChange={handleInstallChange}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            const returnRoute = hudOnly ? chatRouteForAgent(selectedAgent) : "";
            setSelectedAgent(null);
            if (hudOnly) navigate(returnRoute);
          }
        }}
        onSelectAgent={handleSwitchAgent}
        onCreateAgent={() => navigate("/workspace/agents/new?return=hud")}
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
