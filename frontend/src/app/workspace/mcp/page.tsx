import { PlugZapIcon, ServerIcon } from "lucide-react";

import { CapabilityQualityStrip } from "@/components/workspace/capability-quality-strip";
import { McpSettingsPage } from "@/components/workspace/settings/mcp-settings-page";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function McpPage() {
  const { t } = useI18n();
  return (
    <WorkspaceContainer>
      <WorkspaceBody>
        <div className="ui-density-stack mx-auto flex w-full max-w-(--container-width-md) flex-col py-2">
          <CapabilityQualityStrip surface="integrations" />
          <section className="workspace-panel ui-density-panel flex flex-col gap-4">
            <div className="space-y-1">
              <div className="text-muted-foreground text-xs font-medium uppercase tracking-[0.18em]">
                {t.mcpCenter.integrations}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-2xl font-semibold tracking-tight">
                <div className="page-header-icon flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary/15 to-primary/5">
                  <ServerIcon className="size-4.5 text-primary" />
                </div>
                {t.mcpCenter.connectionCenter}
              </div>
              <p className="text-muted-foreground max-w-2xl text-sm leading-6">
                {t.mcpCenter.connectionCenterDesc}
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="workspace-panel-subtle ui-density-panel rounded-lg bg-gradient-to-br from-primary/5 to-transparent transition-colors">
                <div className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <div className="flex size-5 items-center justify-center rounded bg-primary/10">
                    <PlugZapIcon className="size-3 text-primary" />
                  </div>
                  {t.mcpCenter.toolExtension}
                </div>
                <p className="text-muted-foreground text-sm leading-6">
                  {t.mcpCenter.toolExtensionDesc}
                </p>
              </div>
              <div className="workspace-panel-subtle ui-density-panel rounded-lg bg-gradient-to-br from-blue-500/5 to-transparent transition-colors">
                <div className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <div className="flex size-5 items-center justify-center rounded bg-blue-500/10">
                    <ServerIcon className="size-3 text-blue-500" />
                  </div>
                  {t.mcpCenter.configGovernance}
                </div>
                <p className="text-muted-foreground text-sm leading-6">
                  {t.mcpCenter.configGovernanceDesc}
                </p>
              </div>
            </div>
          </section>
          <div className="workspace-panel ui-density-panel">
            <McpSettingsPage />
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
