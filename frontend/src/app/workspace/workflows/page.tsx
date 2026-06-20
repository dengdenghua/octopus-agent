import { Link } from "react-router-dom";
import {
  ArrowRightIcon,
  BrainCircuitIcon,
  CalendarClockIcon,
  ClipboardListIcon,
  WorkflowIcon,
  WrenchIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";

export default function WorkflowsPage() {
  const alternatives = [
    {
      title: "实时任务",
      desc: "把流程直接描述给 Agent，边执行边沉淀步骤和结果。",
      href: "/workspace/realtime/new",
      icon: ClipboardListIcon,
      label: "开始",
    },
    {
      title: "技能库",
      desc: "把稳定动作整理成可复用技能，后续在任务中直接调用。",
      href: "/workspace/skills",
      icon: BrainCircuitIcon,
      label: "查看技能",
    },
    {
      title: "自动化",
      desc: "用订阅和定时任务承接周期性流程，先跑起来再固化。",
      href: "/workspace/intelligence",
      icon: CalendarClockIcon,
      label: "去自动化",
    },
    {
      title: "Reflex",
      desc: "维护触发规则、回复策略和轻量流程分派。",
      href: "/workspace/reflex",
      icon: WorkflowIcon,
      label: "打开规则",
    },
  ];

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="items-stretch">
        <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-4 py-10">
          <section className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
            <div className="grid gap-0 lg:grid-cols-[minmax(0,0.9fr)_minmax(360px,1.1fr)]">
              <div className="border-b border-border/50 bg-muted/20 p-6 lg:border-b-0 lg:border-r">
                <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <WorkflowIcon className="size-5" />
                </div>
                <div className="mt-5 inline-flex items-center gap-1.5 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                  <WrenchIcon className="size-3.5" />
                  编辑器维护中
                </div>
                <h1 className="mt-3 text-2xl font-semibold tracking-tight">
                  工作流编辑器暂不可用
                </h1>
                <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                  当前后端没有提供 workflow-editor 接口。为了避免保存、
                  运行或导入时失败，这里暂时关闭编辑器入口。
                </p>
                <div className="mt-6 flex flex-wrap gap-2">
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

              <div className="grid gap-3 p-4 sm:grid-cols-2">
                {alternatives.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.title}
                      to={item.href}
                      className="group flex min-h-[132px] flex-col rounded-lg border border-border/55 bg-background/70 p-4 transition-colors hover:border-primary/25 hover:bg-background"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <span className="flex size-9 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary">
                          <Icon className="size-4" />
                        </span>
                        <span className="text-xs font-medium text-muted-foreground transition-colors group-hover:text-primary">
                          {item.label}
                        </span>
                      </div>
                      <div className="mt-4 text-sm font-semibold">
                        {item.title}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {item.desc}
                      </p>
                    </Link>
                  );
                })}
              </div>
            </div>
          </section>

          <section className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border border-border/55 bg-card/65 p-4">
              <div className="text-xs font-medium text-muted-foreground">
                推荐过渡方案
              </div>
              <div className="mt-2 text-sm font-semibold">
                先用实时任务跑流程
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                成功路径会在消息、工具轨迹和技能里逐步沉淀。
              </p>
            </div>
            <div className="rounded-lg border border-border/55 bg-card/65 p-4">
              <div className="text-xs font-medium text-muted-foreground">
                可复用资产
              </div>
              <div className="mt-2 text-sm font-semibold">
                稳定动作进入技能库
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                比编辑器更轻，适合现在的插件和技能生态。
              </p>
            </div>
            <div className="rounded-lg border border-border/55 bg-card/65 p-4">
              <div className="text-xs font-medium text-muted-foreground">
                后续恢复
              </div>
              <div className="mt-2 text-sm font-semibold">
                接口可用后再开放编辑
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                避免用户进入半成品编辑器后保存失败。
              </p>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
