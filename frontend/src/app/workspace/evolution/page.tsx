import { ActivityIcon, GaugeIcon, SparklesIcon } from "lucide-react";
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
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function EvolutionPage() {
  const { t } = useI18n();
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="pt-0">
        <div className="flex h-full min-h-0 w-full flex-col bg-card">
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-muted px-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">
                {t.evolutionDashboard.title}
              </div>
              <div className="truncate text-xs text-muted-foreground">
                {t.evolutionDashboard.pageDescription}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                asChild
                variant="outline"
                size="sm"
                className="h-7 whitespace-nowrap px-2.5 text-xs"
              >
                <Link to="/workspace/reflex">
                  <ActivityIcon className="mr-1.5 size-3.5" />
                  {t.evolutionDashboard.reflexRules}
                </Link>
              </Button>
              <Button
                type="button"
                variant={showAdvanced ? "secondary" : "outline"}
                size="sm"
                className="h-7 whitespace-nowrap px-2.5 text-xs"
                onClick={() => setShowAdvanced((value) => !value)}
                aria-expanded={showAdvanced}
                aria-controls="evolution-runtime-monitor"
              >
                <GaugeIcon className="mr-1.5 size-3.5" />
                {showAdvanced
                  ? t.evolutionDashboard.hideRuntimeMonitor
                  : t.evolutionDashboard.showRuntimeMonitor}
              </Button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-auto bg-card p-3">
            <EvolutionDashboard />

            {showAdvanced && (
              <section
                id="evolution-runtime-monitor"
                className="mt-3 scroll-mt-4 rounded-md border border-border bg-card p-3"
              >
                <div className="mb-3 flex flex-col gap-1">
                  <h2 className="text-sm font-semibold">
                    {t.evolutionDashboard.showRuntimeMonitor}
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    {t.evolutionDashboard.runtimeMonitorDescription}
                  </p>
                </div>
                <Tabs defaultValue="control" className="flex flex-col gap-3">
                  <TabsList className="h-8 w-fit rounded-md">
                    <TabsTrigger
                      value="control"
                      className="h-7 gap-1.5 px-2.5 text-xs"
                    >
                      <GaugeIcon className="size-3.5" />
                      {t.evolutionControl.panelTitle}
                    </TabsTrigger>
                    <TabsTrigger
                      value="status"
                      className="h-7 gap-1.5 px-2.5 text-xs"
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
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
