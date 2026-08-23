import { ActivityIcon, DnaIcon, ShieldCheckIcon } from "lucide-react";
import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DualHelixEvolutionPanel } from "@/components/workspace/dual-helix-evolution-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

const EvolutionGovernancePanel = lazy(() =>
  import("@/components/workspace/evolution-governance-panel").then(
    (module) => ({
      default: module.EvolutionGovernancePanel,
    }),
  ),
);

function SectionLoading() {
  return (
    <div className="space-y-3" role="status" aria-label="加载自进化模块">
      <div className="h-24 animate-pulse rounded-xl border bg-muted/30" />
      <div className="h-72 animate-pulse rounded-xl border bg-muted/20" />
    </div>
  );
}

type EvolutionSection = "overview" | "evidence" | "governance";

function normalizeSection(value: string | null): EvolutionSection {
  return value === "evidence" || value === "governance" ? value : "overview";
}

export default function EvolutionPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const section = normalizeSection(searchParams.get("section"));
  const changeSection = (next: string) => {
    const params = new URLSearchParams(searchParams);
    if (next === "overview") params.delete("section");
    else params.set("section", next);
    setSearchParams(params, { replace: true });
  };

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="pt-0">
        <div className="flex h-full min-h-0 w-full flex-col bg-card">
          <header className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-muted px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">
                {t.evolutionDashboard.title}
              </div>
              <div className="truncate text-xs text-muted-foreground">
                从真实任务中学习，并在验证、安全和可回退的前提下应用改进。
              </div>
            </div>
            <Tabs value={section} onValueChange={changeSection}>
              <TabsList className="h-9 rounded-lg border border-border bg-background/70 p-0.5">
                <TabsTrigger
                  value="overview"
                  className="h-8 gap-1.5 px-3 text-xs"
                >
                  <DnaIcon className="size-3.5" />
                  进化总览
                </TabsTrigger>
                <TabsTrigger
                  value="evidence"
                  className="h-8 gap-1.5 px-3 text-xs"
                >
                  <ActivityIcon className="size-3.5" />
                  实验证据
                </TabsTrigger>
                <TabsTrigger
                  value="governance"
                  className="h-8 gap-1.5 px-3 text-xs"
                >
                  <ShieldCheckIcon className="size-3.5" />
                  安全治理
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </header>

          <div className="min-h-0 flex-1 overflow-auto bg-card p-3">
            <Tabs value={section} onValueChange={changeSection}>
              <TabsContent value="overview" className="mt-0">
                <DualHelixEvolutionPanel view="overview" />
              </TabsContent>
              <TabsContent value="evidence" className="mt-0">
                <DualHelixEvolutionPanel view="evidence" />
              </TabsContent>
              <TabsContent value="governance" className="mt-0">
                <Suspense fallback={<SectionLoading />}>
                  <EvolutionGovernancePanel />
                </Suspense>
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
