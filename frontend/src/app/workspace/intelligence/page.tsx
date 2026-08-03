import { useState } from "react";
import { MessageCirclePlusIcon, PlusIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  AutomationConfiguredTab,
} from "@/components/workspace/automation/automation-configured-tab";
import {
  AutomationHistoryTab,
} from "@/components/workspace/automation/automation-history-tab";
import {
  AutomationTemplatesTab,
} from "@/components/workspace/automation/automation-templates-tab";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";

export default function IntelligencePage() {
  const [activeTab, setActiveTab] = useState("templates");

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="pt-0">
        <div className="flex h-full min-h-0 w-full flex-col bg-background">
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-muted/24 px-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">自动化</div>
              <div className="truncate text-xs text-muted-foreground">
                配置任务、查看执行历史与管理模板
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                className="h-7 bg-card/80 px-2.5 text-xs"
              >
                <PlusIcon className="mr-1.5 size-3.5" />
                手动新建
              </Button>
              <Button
                size="sm"
                className="h-7 px-2.5 text-xs"
              >
                <MessageCirclePlusIcon className="mr-1.5 size-3.5" />
                在对话中创建
              </Button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-auto bg-background p-3">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList variant="line" className="mb-3 h-8 w-fit">
                <TabsTrigger value="configured" className="h-8 px-3 text-xs data-[state=active]:text-primary after:bg-primary">
                  已配置
                </TabsTrigger>
                <TabsTrigger value="history" className="h-8 px-3 text-xs data-[state=active]:text-primary after:bg-primary">
                  执行历史
                </TabsTrigger>
                <TabsTrigger value="templates" className="h-8 px-3 text-xs data-[state=active]:text-primary after:bg-primary">
                  任务模板
                </TabsTrigger>
              </TabsList>

              <TabsContent value="configured" className="mt-0">
                <AutomationConfiguredTab />
              </TabsContent>

              <TabsContent value="history" className="mt-0">
                <AutomationHistoryTab />
              </TabsContent>

              <TabsContent value="templates" className="mt-0">
                <AutomationTemplatesTab />
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
