import AutomationSettingsPage from "./automation-settings-page";
import SandboxSettingsPage from "./sandbox-settings-page";

/**
 * One destination for controls that affect what Octopus may execute and
 * where it may execute it. The two existing panels stay independent so their
 * behavior and persistence remain unchanged.
 */
export default function AutomationSecuritySettingsPage() {
  return (
    <div className="flex flex-col gap-8">
      <AutomationSettingsPage />
      <SandboxSettingsPage />
    </div>
  );
}
