import { BotIcon, MonitorIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { DotProgress } from "../swarm/dot-progress";
import type { WorkBlock } from "../work-blocks";
import { statusText, workBlockTitle } from "../work-blocks";
import { blockIcon, compactDetail } from "../agent-workbench-utils";
import { StatusGlyph } from "../agent-workbench-pages";
import type { AgentTile } from "../agent-workbench-utils";
import {
  repairMojibakeText,
  agentProgressPercent,
} from "../agent-workbench-utils";
import {
  agentRunBadgeClass,
  agentRunDotClass,
  agentRunHue,
} from "../agent-run-status";
import { ComputerScopeSwitch } from "./computer-scope-switch";
import { AgentComputerStatusCard } from "./agent-computer-status-card";
import {
  agentStatusTextClass,
  dockAgentStatusLabel,
  workBlockLabelsFromI18n,
} from "./helpers";

export function SubagentProcessView({
  agent,
  blocks,
  currentBlockId,
  onOpenMain,
  onSelectBlock,
}: {
  agent: AgentTile;
  blocks: WorkBlock[];
  currentBlockId: string | null;
  onOpenMain: () => void;
  onSelectBlock: (blockId: string) => void;
}) {
  const { t } = useI18n();
  const workBlockLabels = workBlockLabelsFromI18n(t);
  const label = repairMojibakeText(agent.codename ?? agent.name ?? agent.label);
  const progress = agentProgressPercent(agent.status) / 100;
  const hue = agentRunHue(agent.status);
  const brief = repairMojibakeText(
    agent.prompt ?? agent.task ?? agent.lastThought ?? "",
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col">
        <ComputerScopeSwitch
          subLabel={`${t.agentWorkbench.kindAgent} ${agent.label}`}
          onOpenMain={onOpenMain}
        />
        <section className="border-b border-border-default bg-background/85">
          <div className="flex items-center justify-center border-b border-border-subtle px-3 py-2 text-sm font-medium text-muted-foreground">
            {t.agentWorkbenchPanel.agentClusterIndependentProcess}
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-[8rem_1fr]">
            <div className="border-b border-border-subtle pb-3 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-4">
              <div className="border-b border-border-default pb-1.5 font-mono text-sm font-semibold text-foreground">
                {agent.label}
              </div>
              <div className="mt-7 flex size-20 items-center justify-center rounded-sm border border-border bg-background text-4xl">
                {agent.avatar ? (
                  <span aria-hidden="true">{agent.avatar}</span>
                ) : (
                  <BotIcon className="size-10 text-foreground" />
                )}
              </div>
              <div className="mt-4 truncate text-sm font-semibold text-foreground">
                {label}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {repairMojibakeText(agent.role ?? "Subagent")}
              </div>
            </div>
            <div className="min-w-0">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-lg font-semibold text-foreground">
                    {label}
                  </div>
                  <div className="mt-1 truncate text-sm text-muted-foreground">
                    {repairMojibakeText(
                      agent.role ??
                        agent.taskLabel ??
                        t.agentWorkbenchPanel.subAgent,
                    )}
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
                    agentRunBadgeClass(agent.status),
                  )}
                >
                  <span
                    className={cn(
                      "size-2 rounded-full",
                      agentRunDotClass(agent.status),
                    )}
                  />
                  {dockAgentStatusLabel(agent.status, t)}
                </span>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <DotProgress
                  progress={progress}
                  hue={hue}
                  cols={18}
                  rows={3}
                  className={cn(agent.status === "running" && "animate-pulse")}
                />
                <span className="text-xs text-muted-foreground">
                  {t.agentWorkbenchPanel.processRecords(agent.eventCount)}
                </span>
                {agent.iterationCount !== undefined && (
                  <span className="text-xs text-muted-foreground">
                    {t.agentWorkbenchPanel.iterationRounds(
                      agent.iterationCount,
                    )}
                  </span>
                )}
              </div>
              <div className="mt-4 max-h-36 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-border-default bg-muted/20 px-3 py-2 text-sm leading-6 text-foreground">
                {brief || t.agentWorkbenchPanel.noTaskDescription}
              </div>
            </div>
          </div>
        </section>

        {blocks.length === 0 ? (
          <div className="flex min-h-32 items-center justify-center border-b border-border-subtle bg-muted/15 px-4 text-sm text-muted-foreground">
            {t.agentWorkbenchPanel.waitingForSubagentOutput}
          </div>
        ) : (
          <section className="border-b border-border-subtle bg-background/70">
            <div className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground">
              <MonitorIcon className="size-4" aria-hidden="true" />
              {t.agentWorkbenchPanel.processReplay}
              <span className="ml-auto text-xs font-normal">
                {t.agentWorkbench.stepCount(blocks.length)}
              </span>
            </div>
            <div className="divide-y divide-border/35">
              {blocks.map((block, index) => {
                const Icon = blockIcon(block.kind);
                const active = currentBlockId === block.id;
                const detail =
                  block.outputText ||
                  block.inputText ||
                  block.subtitle ||
                  workBlockTitle(block, workBlockLabels);
                return (
                  <button
                    key={block.id}
                    type="button"
                    onClick={() => onSelectBlock(block.id)}
                    className={cn(
                      "flex w-full items-start gap-2 border-l-2 px-3 py-2 text-left transition-colors",
                      active
                        ? "border-l-primary bg-muted/30"
                        : "border-l-transparent hover:bg-muted/25",
                    )}
                  >
                    <span className="mt-0.5 w-5 shrink-0 font-mono text-xs text-muted-foreground">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <StatusGlyph
                          status={block.status}
                          className="size-3.5"
                        />
                        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate text-xs font-semibold text-foreground">
                          {workBlockTitle(block, workBlockLabels)}
                        </span>
                        {block.subtitle && (
                          <span className="max-w-[38%] shrink-0 truncate text-xs text-muted-foreground">
                            {block.subtitle}
                          </span>
                        )}
                      </div>
                      {detail && (
                        <div className="mt-1 line-clamp-2 text-xs leading-4 text-muted-foreground">
                          {compactDetail(detail, 150)}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground/70">
                      {statusText(block.status, {
                        running: t.messageGrouping.liveProcessRunning,
                        waiting_approval: t.messageGrouping.liveProcessWaiting,
                        warning: t.messageGrouping.liveProcessDone,
                        error: t.messageGrouping.liveProcessError,
                        done: t.messageGrouping.liveProcessDone,
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}
        <AgentComputerStatusCard
          avatar={agent.avatar}
          label={label}
          status={dockAgentStatusLabel(agent.status, t)}
          statusClassName={agentStatusTextClass(agent.status)}
          title={agent.label}
        />
      </div>
    </div>
  );
}
