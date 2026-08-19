import { useState } from "react";
import { PuzzleIcon, SparklesIcon, StoreIcon, UsersIcon } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";

import { CapabilityMarketPanel } from "./capability-market-panel";
import { RegistryPluginsPanel } from "./registry-plugins-panel";
import { RegistrySkillsPanel } from "./registry-skills-panel";
import { WorkBuddyCloudStorePanel } from "./workbuddy-cloud-store-panel";

const SHOW_WORKBUDDY_CLOUD_STORE = true;

// 统一「商城」:把分散在 角色/插件/技能 三处的商城 + 连接器/插件 合并成一个入口。
// 分栏:专家(WorkBuddy 云端专家商城) | 连接器·插件(能力包) | 插件(公网 registry) | 技能(公网 registry)
export function UnifiedMarketplacePanel() {
  const { t } = useI18n();
  const [section, setSection] = useState<
    "experts" | "capabilities" | "plugins" | "skills"
  >("capabilities");

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        <StoreIcon className="h-4 w-4 text-primary" />
        <span className="font-medium">{t.agentWorldUnified.marketplaceTab}</span>
        <span className="text-xs text-muted-foreground">
          专家 / 连接器·插件 / 插件 / 技能 — 统一安装与管理
        </span>
      </div>

      <Tabs value={section} onValueChange={(v) => setSection(v as typeof section)}>
        <TabsList variant="line" className="mb-2 flex-wrap">
          <TabsTrigger value="capabilities" className="h-8 gap-1.5 px-3 text-xs">
            <SparklesIcon className="h-3.5 w-3.5" />
            连接器·插件
          </TabsTrigger>
          {SHOW_WORKBUDDY_CLOUD_STORE && (
            <TabsTrigger value="experts" className="h-8 gap-1.5 px-3 text-xs">
              <UsersIcon className="h-3.5 w-3.5" />
              专家
            </TabsTrigger>
          )}
          <TabsTrigger value="plugins" className="h-8 gap-1.5 px-3 text-xs">
            <PuzzleIcon className="h-3.5 w-3.5" />
            插件
          </TabsTrigger>
          <TabsTrigger value="skills" className="h-8 gap-1.5 px-3 text-xs">
            <SparklesIcon className="h-3.5 w-3.5" />
            技能
          </TabsTrigger>
        </TabsList>

        <TabsContent value="capabilities" className="mt-0">
          <CapabilityMarketPanel />
        </TabsContent>

        {SHOW_WORKBUDDY_CLOUD_STORE && (
          <TabsContent value="experts" className="mt-0">
            <WorkBuddyCloudStorePanel />
          </TabsContent>
        )}

        <TabsContent value="plugins" className="mt-0">
          <RegistryPluginsPanel />
        </TabsContent>

        <TabsContent value="skills" className="mt-0">
          <RegistrySkillsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
