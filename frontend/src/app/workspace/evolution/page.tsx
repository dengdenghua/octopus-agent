import { ActivityIcon, DnaIcon, GaugeIcon, SparklesIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EvolutionControlPanel } from "@/components/workspace/evolution-control-panel";
import EvolutionDashboard from "@/components/workspace/evolution-dashboard";
import EvolutionSettingsPage from "@/components/workspace/settings/evolution-settings-page";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function EvolutionPage() {
  const { t } = useI18n();
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="px-4 pb-4">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
          <section className="workspace-panel rounded-[1.75rem] px-6 py-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div className="flex min-w-0 items-start gap-4 sm:items-center">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-sm">
                  <DnaIcon className="size-5" />
                </div>
                <div className="min-w-0">
                  <h1 className="text-2xl font-bold tracking-tight">
                    {t.evolutionDashboard.title}
                  </h1>
                  <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                    汇总近期学习、能力变化与下一步优化方向。
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2 md:justify-end">
                <Button
                  asChild
                  variant="outline"
                  size="sm"
                  className="h-8 whitespace-nowrap"
                >
                  <Link to="/workspace/reflex">
                    <ActivityIcon className="mr-2 size-4" />
                    反射规则
                  </Link>
                </Button>
                <Button
                  type="button"
                  variant={showAdvanced ? "secondary" : "outline"}
                  size="sm"
                  className="h-8 whitespace-nowrap"
                  onClick={() => setShowAdvanced((value) => !value)}
                >
                  <GaugeIcon className="mr-2 size-4" />
                  {showAdvanced ? "收起监控" : "运行监控"}
                </Button>
              </div>
            </div>
          </section>

          <div className="workspace-panel rounded-[1.75rem] px-5 py-5">
            <EvolutionDashboard />
          </div>

          {showAdvanced && (
            <section className="workspace-panel rounded-[1.75rem] px-5 py-5">
              <div className="mb-4 flex flex-col gap-1">
                <h2 className="text-base font-semibold">运行监控</h2>
                <p className="text-xs text-muted-foreground">
                  查看预算、熔断、候选技能、模型提案、协议漂移和运行状态。
                </p>
              </div>
              <Tabs defaultValue="control" className="flex flex-col gap-4">
                <TabsList className="h-9 w-fit rounded-lg">
                  <TabsTrigger
                    value="control"
                    className="h-8 gap-1.5 px-3 text-xs"
                  >
                    <GaugeIcon className="size-3.5" />
                    {t.evolutionControl.panelTitle}
                  </TabsTrigger>
                  <TabsTrigger
                    value="status"
                    className="h-8 gap-1.5 px-3 text-xs"
                  >
                    <SparklesIcon className="size-3.5" />
                    {t.settings.sections.evolution}
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="control" className="mt-0">
                  <EvolutionControlPanel />
                </TabsContent>
                <TabsContent value="status" className="mt-0">
                  <EvolutionSettingsPage />
                </TabsContent>
              </Tabs>
            </section>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
