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
import { useI18n } from "@/core/i18n/hooks";

export default function WorkflowsPage() {
  const { t } = useI18n();
  const alternatives = [
    {
      title: t.workflows.altRealtimeTitle,
      desc: t.workflows.altRealtimeDesc,
      href: "/workspace/realtime/new",
      icon: ClipboardListIcon,
      label: t.workflows.altRealtimeLabel,
    },
    {
      title: t.workflows.altSkillsTitle,
      desc: t.workflows.altSkillsDesc,
      href: "/workspace/skills",
      icon: BrainCircuitIcon,
      label: t.workflows.altSkillsLabel,
    },
    {
      title: t.workflows.altAutomationTitle,
      desc: t.workflows.altAutomationDesc,
      href: "/workspace/intelligence",
      icon: CalendarClockIcon,
      label: t.workflows.altAutomationLabel,
    },
    {
      title: t.workflows.altReflexTitle,
      desc: t.workflows.altReflexDesc,
      href: "/workspace/reflex",
      icon: WorkflowIcon,
      label: t.workflows.altReflexLabel,
    },
  ];

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="items-stretch">
        <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-4 py-10">
          <section className="overflow-hidden rounded-lg border border-border-default bg-card shadow-[var(--shadow-xs)]">
            <div className="grid gap-0 lg:grid-cols-[minmax(0,0.9fr)_minmax(360px,1.1fr)]">
              <div className="border-b border-border-default bg-muted/20 p-6 lg:border-b-0 lg:border-r">
                <div className="flex size-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <WorkflowIcon className="size-5" />
                </div>
                <div className="mt-5 inline-flex items-center gap-1.5 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                  <WrenchIcon className="size-3.5" />
                  {t.workflows.maintenanceBadge}
                </div>
                <h1 className="mt-3 text-2xl font-semibold tracking-tight">
                  {t.workflows.title}
                </h1>
                <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                  {t.workflows.description}
                </p>
                <div className="mt-6 flex flex-wrap gap-2">
                  <Button asChild>
                    <Link to="/workspace/realtime/new">
                      {t.workflows.newRealtimeTask}
                      <ArrowRightIcon className="size-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link to="/workspace/skills">
                      {t.workflows.viewSkills}
                    </Link>
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
                      className="group flex min-h-[132px] flex-col rounded-lg border border-border-default bg-background/70 p-4 transition-colors hover:border-primary/25 hover:bg-background"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <span className="flex size-9 items-center justify-center bg-muted text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary">
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
            <div className="rounded-lg border border-border-default bg-card/65 p-4">
              <div className="text-xs font-medium text-muted-foreground">
                {t.workflows.cardTransitionLabel}
              </div>
              <div className="mt-2 text-sm font-semibold">
                {t.workflows.cardTransitionTitle}
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {t.workflows.cardTransitionDesc}
              </p>
            </div>
            <div className="rounded-lg border border-border-default bg-card/65 p-4">
              <div className="text-xs font-medium text-muted-foreground">
                {t.workflows.cardAssetsLabel}
              </div>
              <div className="mt-2 text-sm font-semibold">
                {t.workflows.cardAssetsTitle}
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {t.workflows.cardAssetsDesc}
              </p>
            </div>
            <div className="rounded-lg border border-border-default bg-card/65 p-4">
              <div className="text-xs font-medium text-muted-foreground">
                {t.workflows.cardLaterLabel}
              </div>
              <div className="mt-2 text-sm font-semibold">
                {t.workflows.cardLaterTitle}
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {t.workflows.cardLaterDesc}
              </p>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
