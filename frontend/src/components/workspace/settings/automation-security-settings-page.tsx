import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import AutomationSettingsPage from "./automation-settings-page";
import SandboxSettingsPage from "./sandbox-settings-page";

/**
 * One destination for controls that affect what Octopus may execute and
 * where it may execute it. The two existing panels stay independent so their
 * behavior and persistence remain unchanged.
 */
export default function AutomationSecuritySettingsPage() {
  const [tab, setTab] = useState("automation");
  return (
    <Tabs value={tab} onValueChange={setTab} className="space-y-4">
      <TabsList variant="line" className="h-8 w-fit">
        <TabsTrigger value="automation" className="h-8 px-3 text-xs">自动化</TabsTrigger>
        <TabsTrigger value="sandbox" className="h-8 px-3 text-xs">沙箱与执行</TabsTrigger>
      </TabsList>
      <TabsContent value="automation" className="mt-0"><AutomationSettingsPage /></TabsContent>
      <TabsContent value="sandbox" className="mt-0"><SandboxSettingsPage /></TabsContent>
    </Tabs>
  );
}
