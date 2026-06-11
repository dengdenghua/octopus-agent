import { useEffect, useState } from "react";
import {
  Globe2,
  Package,
  Puzzle,
  Wrench,
} from "lucide-react";

import { AgentWorldUnified } from "@/components/workspace/agents/agent-world-unified";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { type StoreTab } from "./store-utils";
import { ApplicationRegistryPanel } from "./application-registry-panel";
import { LocalSkillDirectoryPanel } from "./local-skill-directory-panel";

// ── Re-exports for backward compatibility ──────────────────────────────
export { LocalSkillDirectoryPanel } from "./local-skill-directory-panel";
export { BrowserPluginPanel } from "./browser-plugin-panel";
export {
  type StoreTab,
  type LocalSkill,
  type PluginRegistryItem,
  type SkillCategory,
  LOCAL_SKILL_CATEGORIES,
  APP_CATEGORIES,
  APP_CATEGORY_LABELS,
  StoreErrorState,
  pluginImageUrl,
  appIconUrl,
  useLocalSkillCategoryLabel,
  searchableSkillText,
  classifyLocalSkill,
  sourceLabel,
  searchableAppText,
  normalizePluginLookupKey,
  pluginLookupKeys,
  appPluginLookupKeys,
  searchablePluginBundleText,
  searchablePluginItemText,
  classifyPluginItem,
  openCreatePluginChat,
} from "./store-utils";

// ── Skill Store Panel (thin wrapper) ───────────────────────────────────

function SkillStorePanel() {
  const { t } = useI18n();

  return (
    <div className="workspace-panel ui-density-panel min-h-[560px] rounded-2xl border border-border/60 shadow-sm shadow-black/[0.02]">
      <div className="flex flex-col gap-3 border-b border-border/60 pb-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <Puzzle className="size-4 text-primary" />
          <h3 className="text-sm font-semibold">{t.unifiedStore.skills.title}</h3>
        </div>
      </div>
      <LocalSkillDirectoryPanel />
    </div>
  );
}

// ── Unified Store ──────────────────────────────────────────────────────

export function UnifiedStore({
  initialTab = "agents",
  compact = false,
}: {
  initialTab?: StoreTab;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<StoreTab>(initialTab);

  return (
    <div
      className={cn(
        "relative flex min-h-0 flex-1 flex-col overflow-hidden bg-background",
        compact ? "h-full" : "size-full",
      )}
    >
      <Tabs value={tab} onValueChange={(value) => setTab(value as StoreTab)} className="min-h-0 flex-1 gap-0">
        <div className="relative shrink-0 border-b border-border/60 bg-background/90 px-3 py-3 backdrop-blur">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Capability Store
              </div>
              <h1 className="mt-1 text-xl font-semibold tracking-tight">
                选择要装进工作区的能力
              </h1>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                Agent 负责角色，插件负责外部连接，技能负责具体做法。先选类型，再用搜索收敛。
              </p>
            </div>
            <TabsList className="grid h-auto w-full grid-cols-3 rounded-lg border border-border/70 bg-muted/35 p-0.5 sm:w-[24rem]">
              <TabsTrigger value="agents" className="gap-1.5 rounded-sm px-3 data-[state=active]:border data-[state=active]:border-primary/35 data-[state=active]:shadow-[0_0_14px_hsl(var(--primary)/0.12)]">
                <Globe2 className="size-4" />
                {t.unifiedStore.tabs.agents}
              </TabsTrigger>
              <TabsTrigger value="plugins" className="gap-1.5 rounded-sm px-3 data-[state=active]:border data-[state=active]:border-primary/35 data-[state=active]:shadow-[0_0_14px_hsl(var(--primary)/0.12)]">
                <Package className="size-4" />
                {t.unifiedStore.tabs.plugins}
              </TabsTrigger>
              <TabsTrigger value="skills" className="gap-1.5 rounded-sm px-3 data-[state=active]:border data-[state=active]:border-primary/35 data-[state=active]:shadow-[0_0_14px_hsl(var(--primary)/0.12)]">
                <Wrench className="size-4" />
                {t.unifiedStore.tabs.skills}
              </TabsTrigger>
            </TabsList>
          </div>
        </div>

        <div className="ui-density-page relative min-h-0 flex-1 overflow-y-auto">
          <TabsContent value="plugins" className="m-0">
            <div className="workspace-panel ui-density-panel min-h-[520px] rounded-2xl border border-border/60 shadow-sm shadow-black/[0.02]">
              <ApplicationRegistryPanel />
            </div>
          </TabsContent>
          <TabsContent value="skills" className="m-0">
            <SkillStorePanel />
          </TabsContent>
          <TabsContent value="agents" className="m-0">
            <div className="relative min-h-[520px] overflow-hidden">
              <AgentWorldUnified />
            </div>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

// ── Unified Store Overlay ──────────────────────────────────────────────

export function UnifiedStoreOverlay({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onOpenChange, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-background/72 backdrop-blur-xl">
      <div className="flex h-full flex-col overflow-hidden">
        <div className="absolute right-4 top-4 z-10">
          <Button
            aria-label={t.unifiedStore.closeAria}
            size="icon"
            variant="ghost"
            onClick={() => onOpenChange(false)}
          >
            X
          </Button>
        </div>
        <UnifiedStore compact />
      </div>
    </div>
  );
}
