import { useState } from "react";
import {
  BrainIcon,
  DatabaseIcon,
  FileTextIcon,
  NetworkIcon,
} from "lucide-react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { KnowledgeGraphPanel } from "@/components/workspace/knowledge-graph-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

function MemoryTab() {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center gap-3 py-12 text-center">
      <BrainIcon className="size-8 text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">记忆管理 · 即将上线</p>
    </div>
  );
}

function WikiTab() {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center gap-3 py-12 text-center">
      <FileTextIcon className="size-8 text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">Wiki 文档 · 即将上线</p>
    </div>
  );
}

function FilesTab() {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center gap-3 py-12 text-center">
      <DatabaseIcon className="size-8 text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">文件管理 · 即将上线</p>
    </div>
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

          <div className="workspace-panel ui-density-panel rounded-[1.75rem]">
            {activeTab === "graph" && <KnowledgeGraphPanel />}
            {activeTab === "memory" && <MemoryTab />}
            {activeTab === "wiki" && <WikiTab />}
            {activeTab === "files" && <FilesTab />}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
