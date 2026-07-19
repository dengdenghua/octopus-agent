import { lazy, Suspense, useState } from "react";
import { CalendarClockIcon, Loader2Icon, RadarIcon } from "lucide-react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { IntelligencePanel } from "@/components/workspace/intelligence-panel";
import { useI18n } from "@/core/i18n/hooks";

const CronSettingsPage = lazy(() =>
  import("@/components/workspace/settings/cron-settings-page").then((m) => ({
    default: m.CronSettingsPage,
  })),
);

export default function IntelligencePage() {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("subscriptions");
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="ui-density-stack mx-auto flex w-full max-w-6xl flex-col py-2">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="grid h-auto w-full max-w-md grid-cols-2 rounded-lg p-1">
              <TabsTrigger
                value="subscriptions"
                className="h-8 gap-1.5 px-3 text-xs"
              >
                <RadarIcon className="size-3.5" />
                {t.intelligence.subscriptionsHeader}
              </TabsTrigger>
              <TabsTrigger
                value="schedules"
                className="h-8 gap-1.5 px-3 text-xs"
              >
                <CalendarClockIcon className="size-3.5" />
                {t.taskBoard.schedules}
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <div className="workspace-panel ui-density-panel rounded-[1.75rem]">
            {activeTab === "subscriptions" ? (
              <IntelligencePanel />
            ) : (
              <Suspense
                fallback={
                  <div className="flex min-h-64 items-center justify-center">
                    <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
                  </div>
                }
              >
                <CronSettingsPage />
              </Suspense>
            )}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
