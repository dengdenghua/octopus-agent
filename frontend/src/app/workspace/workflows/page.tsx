import { Link } from "react-router-dom";
import { ArrowRightIcon, WorkflowIcon, WrenchIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";

export default function WorkflowsPage() {
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="items-stretch">
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-10">
          <section className="rounded-lg border border-border/70 bg-background p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <WorkflowIcon className="size-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="mb-2 inline-flex items-center gap-1.5 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                  <WrenchIcon className="size-3.5" />
                  维护中
                </div>
                <h1 className="text-xl font-semibold tracking-tight">
                  工作流编辑器暂不可用
                </h1>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  当前后端没有提供 workflow-editor
                  接口。为了避免保存、运行或导入时失败，
                  这里暂时关闭编辑器入口。你仍然可以在实时任务中描述流程，或使用技能页管理可复用能力。
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  <Button asChild>
                    <Link to="/workspace/realtime/new">
                      新建实时任务
                      <ArrowRightIcon className="size-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link to="/workspace/skills">查看技能</Link>
                  </Button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
