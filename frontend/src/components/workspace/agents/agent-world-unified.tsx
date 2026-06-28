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
import { useOpenCreatePluginChat } from "@/components/store/store-utils";

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

  const installedAgents = useMemo(
    () => visibleAgents.filter((a) => a.is_installed),
    [visibleAgents],
  );
  const marketplaceAgents = useMemo(
    () => visibleAgents.filter((a) => !a.is_installed),
    [visibleAgents],
  );

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
    <div className="space-y-5">
      {/* Filter bar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div
          data-testid="agents-category-scroll"
          className="flex flex-wrap gap-1.5"
        >
          {AGENT_CATEGORY_FILTERS.map((category) => {
            const CategoryIcon = CATEGORY_ICONS[category];
            const count = categoryCounts.get(category) ?? 0;
            const label =
              category === "all"
                ? t.agentWorld.categories.all
                : (t.agentWorld.categories[category] ?? category);
            const active = activeCategory === category;
            return (
              <Button
                key={category}
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onCategoryChange(category)}
                className={cn(
                  "h-8 shrink-0 gap-1 rounded-full px-3 text-xs transition-colors",
                  active
                    ? "bg-primary/10 text-foreground hover:bg-primary/15"
                    : "bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                <CategoryIcon className="h-3.5 w-3.5" />
                {label}
                <span
                  className={cn(
                    "ml-0.5 text-[10px]",
                    active ? "text-primary/70" : "text-muted-foreground/70",
                  )}
                >
                  {count}
                </span>
              </Button>
            );
          })}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <div className="flex items-center gap-3 rounded-full border border-border/50 bg-muted/30 px-3 py-1.5 text-xs">
            <span className="text-muted-foreground">
              {t.agentWorldUnified.installedLabel}
              <span className="ml-1 font-medium text-foreground">
                {installedCount}
              </span>
            </span>
            <span className="text-border/80">|</span>
            <span className="text-muted-foreground">
              {t.agentWorldUnified.installableLabel}
              <span className="ml-1 font-medium text-foreground">
                {Math.max(0, installableCount)}
              </span>
            </span>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 rounded-full px-3 text-xs shadow-none"
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
        <div className="space-y-6">
          {installedAgents.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <span className="text-xs font-semibold text-foreground">
                  {t.agentWorldUnified.installedLabel}
                </span>
                <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                  {installedAgents.length}
                </Badge>
              </div>
              <div
                data-testid="agents-installed-grid"
                className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
              >
                {installedAgents.map((agent) => (
                  <AgentCard
                    key={agent.id}
                    agent={worldAgentToAgent(agent)}
                    isDefault={agent.is_official || LOCAL_AGENT_IDS.has(agent.id)}
                    onSelect={() => onSelectAgent(agent)}
                  />
                ))}
              </div>
            </section>
          )}

          {marketplaceAgents.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <span className="text-xs font-semibold text-foreground">
                  {t.agentWorldUnified.installableLabel}
                </span>
                <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                  {marketplaceAgents.length}
                </Badge>
              </div>
              <div
                data-testid="agents-marketplace-grid"
                className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
              >
                {marketplaceAgents.map((agent) => (
                  <AgentWorldCard
                    key={agent.id}
                    agent={agent}
                    onSelect={onSelectAgent}
                    onInstallChange={onInstallChange}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      ) : (
        <div
          data-testid="agents-empty-state"
          className="flex flex-col items-center rounded-xl border border-dashed border-border/60 bg-muted/10 py-16"
        >
          <StoreIcon className="mb-3 h-10 w-10 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CheckCircle as CheckCircleIcon,
  XCircle as XCircleIcon,
  Settings2 as Settings2Icon,
} from "lucide-react";
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

function pluginSurfaceBadges(
  entry: PluginEntry,
  t: ReturnType<typeof useI18n>["t"],
): string[] {
  if (entry.source === "hub") {
    const labels = entry.plugin.capabilities
      .map((capability) => capability.type)
      .filter(Boolean)
      .map((type) => {
        if (type === "skill") return t.plugins.capabilitySkill;
        if (type === "channel") return t.plugins.capabilityChannel;
        if (type === "api") return t.plugins.capabilityApi;
        if (type === "config_ui") return t.plugins.capabilityConfig;
        return type;
      });
    return Array.from(new Set(labels)).slice(0, 4);
  }
  const surfaces = entry.plugin.smoke?.surfaces;
  const badges: string[] = [];
  if (surfaces?.mcp) badges.push("MCP");
  if (surfaces?.apps) badges.push("App");
  if (surfaces?.skills) badges.push(t.plugins.capabilitySkill);
  if (surfaces?.commands) badges.push(t.plugins.capabilityCommand);
  if (surfaces?.capabilities && !badges.includes("API")) {
    badges.push(t.plugins.capabilityCapability);
  }
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
    <UiDialog open={open} onOpenChange={onOpenChange}>
      <UiDialogContent className="max-w-md">
        <UiDialogHeader>
          <UiDialogTitle>
            {t.plugins.configTitle(plugin.name)}
          </UiDialogTitle>
          <UiDialogDescription>
            {t.plugins.configDescription(plugin.name)}
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
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
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
              {t.plugins.noConfig}
            </p>
          )}
        </div>

        <UiDialogFooter>
          <UiDialogClose asChild>
            <Button variant="outline">{t.common.cancel}</Button>
          </UiDialogClose>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t.common.loading : t.common.save}
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
      ? t.plugins.statusEnabled
      : t.plugins.statusDisabled;
  const surfaceBadges = pluginSurfaceBadges(entry, t);

  return (
    <div className="group flex min-w-0 items-center gap-3 rounded-xl border border-border/60 bg-card/70 px-3 py-3 shadow-sm transition-all hover:border-primary/25 hover:bg-card hover:shadow-md">
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
          <h3 className="truncate text-sm font-semibold leading-5 text-foreground">
            {plugin.name}
          </h3>
        </div>
        <p className="mt-0.5 line-clamp-1 text-xs leading-4 text-muted-foreground">
          {plugin.description}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {surfaceBadges.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {surfaceBadges.map((badge) => (
                <span
                  key={badge}
                  className="rounded-full border border-border/60 bg-muted/35 px-2 py-0.5 text-[10px] font-medium leading-4 text-muted-foreground"
                >
                  {badge}
                </span>
              ))}
            </div>
          )}
          {plugin.author && (
            <span className="text-[10px] text-muted-foreground/70">
              {plugin.author}
              {plugin.version ? ` · v${plugin.version}` : ""}
            </span>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {hasConfig && hubPlugin && (
          <button
            type="button"
            aria-label={t.plugins.configAria(plugin.name)}
            onClick={() => onConfigure(hubPlugin)}
            className="flex size-8 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Settings2Icon className="size-4" />
          </button>
        )}
        <span
          title={statusTitle}
          className={cn(
            "flex size-8 items-center justify-center rounded-lg transition-colors",
            plugin.error
              ? "bg-rose-500/10 text-rose-500"
              : plugin.enabled
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
                : "bg-muted/55 text-foreground hover:bg-muted",
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
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [hubPlugins, setHubPlugins] = useState<HubPluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [configTarget, setConfigTarget] = useState<HubPluginInfo | null>(null);
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
    const needle = searchQuery.trim().toLowerCase();
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
  }, [pluginAuthorFilter, pluginEntries, searchQuery, pluginStatusFilter]);

  const enabledCount = useMemo(
    () => pluginEntries.filter(({ plugin }) => plugin.enabled).length,
    [pluginEntries],
  );
  const disabledCount = pluginEntries.length - enabledCount;

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center rounded-xl border border-border/60 bg-muted/10">
        <PuzzleIcon className="size-8 animate-pulse text-primary/60" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Filter bar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={pluginAuthorFilter}
            onValueChange={setPluginAuthorFilter}
          >
            <SelectTrigger className="h-8 w-auto gap-2 rounded-full border-border/50 bg-muted/40 px-3 text-xs shadow-none hover:bg-muted/60">
              <SelectValue placeholder={t.plugins.allAuthors} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t.plugins.allAuthors}</SelectItem>
              {pluginAuthors.map((author) => (
                <SelectItem key={author} value={author}>
                  {author}
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
            <SelectTrigger className="h-8 w-auto gap-2 rounded-full border-border/50 bg-muted/40 px-3 text-xs shadow-none hover:bg-muted/60">
              <SelectValue placeholder={t.plugins.allStatuses} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t.plugins.allStatuses}</SelectItem>
              <SelectItem value="enabled">{t.plugins.statusEnabled}</SelectItem>
              <SelectItem value="disabled">{t.plugins.statusDisabled}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-3 rounded-full border border-border/50 bg-muted/30 px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">
            {t.plugins.statTotal}
            <span className="ml-1 font-medium text-foreground">
              {pluginEntries.length}
            </span>
          </span>
          <span className="text-border/80">|</span>
          <span className="text-muted-foreground">
            {t.plugins.statEnabled}
            <span className="ml-1 font-medium text-emerald-600 dark:text-emerald-400">
              {enabledCount}
            </span>
          </span>
          <span className="text-border/80">|</span>
          <span className="text-muted-foreground">
            {t.plugins.statusDisabled}
            <span className="ml-1 font-medium text-foreground">
              {disabledCount}
            </span>
          </span>
        </div>
      </div>

      {filteredPluginEntries.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredPluginEntries.map((entry) => (
            <PluginListItem
              key={`${entry.source}-${entry.plugin.id}`}
              entry={entry}
              onConfigure={setConfigTarget}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center rounded-xl border border-dashed border-border/60 bg-muted/10 py-16 text-center">
          <PuzzleIcon className="mb-3 size-10 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            {pluginEntries.length === 0
              ? t.plugins.emptyTitle
              : t.plugins.noMatchTitle}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/60">
            {pluginEntries.length === 0
              ? t.plugins.emptyHint
              : t.plugins.noMatchHint}
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
// Hub shows all available agents (installed + installable).
const LOCAL_LIBRARY_INSTALLED_ONLY = false;
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

  const hudSwitchAgents = useMemo(() => {
    const installed = dedupedAgents.filter((a) => a.is_installed);
    if (selectedAgent && !selectedAgent.is_installed) {
      return [selectedAgent, ...installed.filter((a) => a.id !== selectedAgent.id)];
    }
    return installed;
  }, [dedupedAgents, selectedAgent]);

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

  const openCreatePlugin = useOpenCreatePluginChat();

  const handleCreateSkill = useCallback(() => {
    navigate("/workspace/realtime/new?mode=skill");
  }, [navigate]);

  const hubMeta = useMemo(() => {
    switch (activeTab) {
      case "plugins":
        return {
          icon: PuzzleIcon,
          title: t.plugins.pageTitle,
          subtitle: t.plugins.pageSubtitle,
          searchPlaceholder: t.applicationRegistry.searchPlaceholder,
        };
      case "skills":
        return {
          icon: BoxesIcon,
          title: t.unifiedStore.skills.title,
          subtitle: t.unifiedStore.skills.localDesc,
          searchPlaceholder: t.unifiedStore.skills.searchPlaceholder,
        };
      case "enterprise":
        return {
          icon: Building2Icon,
          title: t.agentWorldUnified.enterprise,
          subtitle: "",
          searchPlaceholder: t.agentWorld.searchPlaceholder,
        };
      default:
        return {
          icon: BotIcon,
          title: t.agentWorld.title,
          subtitle: t.agentWorld.description,
          searchPlaceholder: t.agentWorld.searchPlaceholder,
        };
    }
  }, [activeTab, t]);

  const HubIcon = hubMeta.icon;

  return (
    <div className="relative flex size-full flex-col gap-3 px-3 pb-3 pt-3">
      {!hudOnly && (
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col gap-3">
          <header className="flex flex-col gap-3 rounded-xl border border-border/60 bg-card/60 px-4 py-3 shadow-sm">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border/50 bg-background shadow-sm">
                  <HubIcon className="h-4 w-4 text-primary" />
                </div>
                <div className="min-w-0">
                  <h1 className="truncate text-base font-semibold tracking-tight">
                    {hubMeta.title}
                  </h1>
                  {hubMeta.subtitle && (
                    <p className="truncate text-xs text-muted-foreground">
                      {hubMeta.subtitle}
                    </p>
                  )}
                </div>
              </div>

              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-end">
                <div className="relative w-full md:max-w-[260px]">
                  <SearchIcon className="text-muted-foreground absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2" />
                  <Input
                    data-testid="agents-search-input"
                    placeholder={hubMeta.searchPlaceholder}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="h-9 rounded-lg border-border/60 bg-background/70 pl-8 text-xs"
                  />
                </div>
                {activeTab === "agents" && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" className="h-9 rounded-lg shadow-none">
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
                )}
                {activeTab === "plugins" && (
                  <Button size="sm" className="h-9 rounded-lg shadow-none" onClick={openCreatePlugin}>
                    <PlusIcon className="mr-1.5 h-3.5 w-3.5" />
                    {t.applicationRegistry.createPlugin}
                  </Button>
                )}
                {activeTab === "skills" && (
                  <Button size="sm" className="h-9 rounded-lg shadow-none" onClick={handleCreateSkill}>
                    <PlusIcon className="mr-1.5 h-3.5 w-3.5" />
                    {t.settings.skills.createSkill}
                  </Button>
                )}
              </div>
            </div>

            <TabsList className="h-auto gap-1 rounded-full bg-muted/40 p-1">
              {SHOW_LOCAL_AGENT_LIBRARY && (
                <TabsTrigger
                  value="agents"
                  className="h-7 gap-1.5 rounded-full px-3 text-xs data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
                >
                  <BotIcon className="h-3.5 w-3.5" />
                  {t.agentWorldUnified.roleLibrary}
                </TabsTrigger>
              )}
              <TabsTrigger
                value="plugins"
                className="h-7 gap-1.5 rounded-full px-3 text-xs data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
              >
                <PuzzleIcon className="h-3.5 w-3.5" />
                {t.plugins.pageTitle}
              </TabsTrigger>
              <TabsTrigger
                value="skills"
                className="h-7 gap-1.5 rounded-full px-3 text-xs data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
              >
                <BoxesIcon className="h-3.5 w-3.5" />
                {t.unifiedStore.skills.title}
              </TabsTrigger>
              {SHOW_ENTERPRISE_ASSETS && (
                <TabsTrigger
                  value="enterprise"
                  className="h-7 gap-1.5 rounded-full px-3 text-xs data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
                >
                  <Building2Icon className="h-3.5 w-3.5" />
                  {t.agentWorldUnified.enterprise}
                </TabsTrigger>
              )}
            </TabsList>
          </header>

          {/* Main Content */}
          <div className="workspace-panel relative flex-1 overflow-y-auto rounded-xl border border-border/60 bg-card/40 px-4 py-4 shadow-sm">
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
                searchQuery={searchQuery}
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
          </div>
        </Tabs>
      )}

      <AgentRoleProfileDialog
        agent={selectedAgent}
        agents={hudOnly ? hudSwitchAgents : dedupedAgents}
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
