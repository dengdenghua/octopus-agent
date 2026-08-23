import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIcon,
  GaugeIcon,
  Settings2Icon,
  ShieldCheckIcon,
} from "lucide-react";
import { lazy, Suspense } from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getDualHelixShadowStatus,
  setDualHelixShadowEnabled,
} from "@/core/evolution/api";

const shadowQueryKey = ["evolution", "dual-helix", "shadow"] as const;

const EvolutionControlPanel = lazy(() =>
  import("./evolution-control-panel").then((module) => ({
    default: module.EvolutionControlPanel,
  })),
);
const EvolutionSettingsPage = lazy(
  () => import("./settings/evolution-settings-page"),
);
const ReflexMonitorContent = lazy(() =>
  import("@/app/workspace/reflex/page").then((module) => ({
    default: module.ReflexMonitorContent,
  })),
);

function GovernancePanelLoading() {
  return (
    <div
      className="h-72 animate-pulse rounded-xl border bg-muted/25"
      role="status"
      aria-label="加载治理模块"
    />
  );
}

export function EvolutionGovernancePanel() {
  const queryClient = useQueryClient();
  const shadow = useQuery({
    queryKey: shadowQueryKey,
    queryFn: getDualHelixShadowStatus,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const setShadow = useMutation({
    mutationFn: setDualHelixShadowEnabled,
    onSuccess: (value) => queryClient.setQueryData(shadowQueryKey, value),
  });

  return (
    <section className="space-y-4" aria-label="安全治理">
      <div className="grid gap-3 lg:grid-cols-3">
        <article className="rounded-xl border border-border bg-card p-4 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-success/10 text-success">
                <ShieldCheckIcon className="size-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">影子复核保护</h2>
                <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
                  仅在对话中手动点击 DNA
                  复核按钮时运行另一引擎；工作区使用隔离副本和只读权限。
                </p>
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              variant={shadow.data?.enabled ? "secondary" : "outline"}
              disabled={setShadow.isPending || !shadow.data?.ok}
              onClick={() => setShadow.mutate(!shadow.data?.enabled)}
            >
              {shadow.data?.enabled ? "保护已开启" : "开启保护"}
            </Button>
          </div>
          <div className="mt-3 rounded-lg bg-muted/45 px-3 py-2 text-[11px] text-muted-foreground">
            {shadow.data?.enabled
              ? "已授权手动影子复核；开启状态本身不会调用模型。"
              : "当前关闭，不会触发另一引擎，也不会产生额外费用。"}
          </div>
        </article>

        <article className="rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <ActivityIcon className="size-4 text-primary" />
            治理边界
          </div>
          <div className="mt-3 space-y-2 text-xs text-muted-foreground">
            <div className="flex justify-between">
              <span>影子执行</span>
              <span>手动触发</span>
            </div>
            <div className="flex justify-between">
              <span>工作区权限</span>
              <span>只读副本</span>
            </div>
            <div className="flex justify-between">
              <span>候选发布</span>
              <span>灰度后晋升</span>
            </div>
          </div>
        </article>
      </div>

      <Tabs defaultValue="control" className="space-y-3">
        <TabsList className="h-9 w-fit rounded-lg">
          <TabsTrigger value="control" className="h-8 gap-1.5 px-3 text-xs">
            <GaugeIcon className="size-3.5" />
            策略与预算
          </TabsTrigger>
          <TabsTrigger value="reflex" className="h-8 gap-1.5 px-3 text-xs">
            <ActivityIcon className="size-3.5" />
            规则与响应
          </TabsTrigger>
          <TabsTrigger value="runtime" className="h-8 gap-1.5 px-3 text-xs">
            <Settings2Icon className="size-3.5" />
            运行与设置
          </TabsTrigger>
        </TabsList>
        <TabsContent
          value="control"
          className="mt-0 rounded-xl border bg-card p-3"
        >
          <Suspense fallback={<GovernancePanelLoading />}>
            <EvolutionControlPanel />
          </Suspense>
        </TabsContent>
        <TabsContent value="reflex" className="mt-0">
          <Suspense fallback={<GovernancePanelLoading />}>
            <ReflexMonitorContent />
          </Suspense>
        </TabsContent>
        <TabsContent
          value="runtime"
          className="mt-0 rounded-xl border bg-card p-3"
        >
          <Suspense fallback={<GovernancePanelLoading />}>
            <EvolutionSettingsPage />
          </Suspense>
        </TabsContent>
      </Tabs>
    </section>
  );
}
