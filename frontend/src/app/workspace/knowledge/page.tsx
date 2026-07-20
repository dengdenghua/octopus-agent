import { useState } from "react";
import {
  BrainIcon,
  DatabaseIcon,
  FileTextIcon,
  type LucideIcon,
  NetworkIcon,
} from "lucide-react";

import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CapabilityQualityStrip } from "@/components/workspace/capability-quality-strip";
import { KnowledgeGraphPanel } from "@/components/workspace/knowledge-graph-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

function ComingSoonTab({
  icon: Icon,
  title,
}: {
  icon: LucideIcon;
  title: string;
}) {
  return (
    <Empty className="min-h-64">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icon />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>即将上线</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export default function KnowledgePage() {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("graph");
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="ui-density-stack mx-auto flex w-full max-w-6xl flex-col py-2">
          <CapabilityQualityStrip surface="knowledge" />
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="grid h-auto w-full max-w-lg grid-cols-4 rounded-lg p-1">
              <TabsTrigger value="graph" className="h-8 gap-1.5 px-3 text-xs">
                <NetworkIcon className="size-3.5" />
                {t.knowledgeGraph.graph}
              </TabsTrigger>
              <TabsTrigger value="memory" className="h-8 gap-1.5 px-3 text-xs">
                <BrainIcon className="size-3.5" />
                {t.evolutionDashboard.memories}
              </TabsTrigger>
              <TabsTrigger value="wiki" className="h-8 gap-1.5 px-3 text-xs">
                <FileTextIcon className="size-3.5" />
                Wiki
              </TabsTrigger>
              <TabsTrigger value="files" className="h-8 gap-1.5 px-3 text-xs">
                <DatabaseIcon className="size-3.5" />
                Files
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <div className="workspace-panel ui-density-panel">
            {activeTab === "graph" && <KnowledgeGraphPanel />}
            {activeTab === "memory" && (
              <ComingSoonTab icon={BrainIcon} title="记忆管理" />
            )}
            {activeTab === "wiki" && (
              <ComingSoonTab icon={FileTextIcon} title="Wiki 文档" />
            )}
            {activeTab === "files" && (
              <ComingSoonTab icon={DatabaseIcon} title="文件管理" />
            )}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
