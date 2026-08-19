import { useState } from "react";
import { PuzzleIcon, SparklesIcon, StoreIcon, UsersIcon } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";

import { CapabilityMarketPanel } from "./capability-market-panel";
import { RegistryPluginsPanel } from "./registry-plugins-panel";
import { RegistrySkillsPanel } from "./registry-skills-panel";
import { WorkBuddyCloudStorePanel } from "./workbuddy-cloud-store-panel";

const SHOW_WORKBUDDY_CLOUD_STORE = true;

// 统一「商城」:所有外部能力(WorkBuddy MCP 服务、Codex 插件、注册表插件)统一叫插件。
// 分栏:插件(能力包 + 注册表) | 技能 | 专家
export function UnifiedMarketplacePanel() {
  const { t } = useI18n();
  const [section, setSection] = useState<"plugins" | "skills" | "experts">(
    "plugins",
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        <StoreIcon className="h-4 w-4 text-primary" />
        <span className="font-medium">{t.agentWorldUnified.marketplaceTab}</span>
        <span className="text-xs text-muted-foreground">
          插件 / 技能 / 专家 — 统一安装与管理
        </span>
      </div>

      <Tabs value={section} onValueChange={(v) => setSection(v as typeof section)}>
        <TabsList variant="line" className="mb-2 flex-wrap">
          <TabsTrigger value="plugins" className="h-8 gap-1.5 px-3 text-xs">
            <PuzzleIcon className="h-3.5 w-3.5" />
            插件
          </TabsTrigger>
          <TabsTrigger value="skills" className="h-8 gap-1.5 px-3 text-xs">
            <SparklesIcon className="h-3.5 w-3.5" />
            技能
          </TabsTrigger>
          {SHOW_WORKBUDDY_CLOUD_STORE && (
            <TabsTrigger value="experts" className="h-8 gap-1.5 px-3 text-xs">
              <UsersIcon className="h-3.5 w-3.5" />
              专家
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="plugins" className="mt-0 flex flex-col gap-4">
          <CapabilityMarketPanel />
          <div className="flex items-center gap-2 border-t border-border-default pt-3">
            <PuzzleIcon className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">
              公网注册表插件(Codex 插件生态)
            </span>
          </div>
          <RegistryPluginsPanel />
        </TabsContent>

        <TabsContent value="skills" className="mt-0">
          <RegistrySkillsPanel />
        </TabsContent>

        {SHOW_WORKBUDDY_CLOUD_STORE && (
          <TabsContent value="experts" className="mt-0">
            <WorkBuddyCloudStorePanel />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
