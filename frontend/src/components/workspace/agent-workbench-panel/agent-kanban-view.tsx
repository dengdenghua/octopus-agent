import { memo, useMemo, useState } from "react";

import {
  BotIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  MonitorIcon,
} from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import type { OutlineRound } from "@/core/threads/progress-outline";
import type { VisibilityStep } from "@/core/realtime/items";
import type { WorkBlock } from "../work-blocks";
import { pickCurrentWorkBlock } from "../work-blocks";
import type {
  AgentTile,
  AgentWorkbenchTabId,
  DiffEntry,
} from "../agent-workbench-utils";
import { repairMojibakeText } from "../agent-workbench-utils";
import type { AgentPhase } from "../agent-phases";
import type { AgentRunState } from "../agent-run-status";
import { agentRunDotClass } from "../agent-run-status";
import type { AgentWorkbenchProcessEventSnapshot } from "../agent-workbench-events";
import { AgentCreationCard, AgentSummaryPage } from "../agent-workbench-pages";
import { useAgentWorkbenchI18n } from "../use-agent-workbench-i18n";
import type { ScreenFrameSnapshot } from "../agent-workbench-snapshot";
import type { LiveToolEvent } from "../live-tool-timeline";
import { ActivityTraceView } from "./activity-trace-view";
import { RosterComputerPlaceholder } from "./roster-computer-placeholder";
import { SubagentProcessView } from "./subagent-process-view";
import {
  type WorkbenchRosterSeat,
  rosterSeatRoleLabel,
  mainPhaseStatusLabel,
  dockAgentStatusLabel,
} from "./helpers";

type AgentKanbanUserInput = {
  text: string;
  uploadedFiles: Array<{ filename: string; path: string }>;
  attachments: Array<{ filename: string }>;
} | null;

function AgentKanbanViewImpl({
  effectiveActivityView,
  hasIndependentTrace,
  hasComputerActivity,
  selectedRosterSeat,
  selectedAgent,
  creationFocusAgent,
  phases,
  blocks,
  agentTiles,
  visibleDiffEntries,
  rosterBlocks,
  screenBlocks,
  screenFrame,
  focusedProcessEvent,
  focusedEventId,
  progressOutline,
  userInput,
  mainPhases,
  mainRunState,
  screenProgress,
  mainAgentName,
  currentPhaseTitle: currentPhaseTitleText,
  terminalState,
  contextTokens,
  maxContextTokens,
  isCompressingContext,
  onCompressContext,
  visibilityEvents,
  setActivityView,
  onSelectTab,
  onOpenArtifact,
  openMainProcess,
  openSubagentProcess,
  setSelectedBlockId,
  setManualBlockSelection,
}: {
  effectiveActivityView: "summary" | "trace" | "screen";
  hasIndependentTrace: boolean;
  hasComputerActivity: boolean;
  selectedRosterSeat: WorkbenchRosterSeat | null;
  selectedAgent: AgentTile | null;
  creationFocusAgent: AgentTile | undefined;
  phases: AgentPhase[];
  blocks: WorkBlock[];
  agentTiles: AgentTile[];
  visibleDiffEntries: DiffEntry[];
  rosterBlocks: WorkBlock[];
  screenBlocks: WorkBlock[];
  screenFrame: ScreenFrameSnapshot;
  focusedProcessEvent: AgentWorkbenchProcessEventSnapshot | null;
  focusedEventId: string | null | undefined;
  progressOutline: OutlineRound[] | undefined;
  userInput: AgentKanbanUserInput;
  mainPhases: AgentPhase[];
  mainRunState: AgentRunState;
  screenProgress: { current: number; total: number };
  mainAgentName: string | null | undefined;
  currentPhaseTitle: string;
  terminalState: "interrupted" | "failed" | null;
  contextTokens?: number;
  maxContextTokens?: number;
  isCompressingContext?: boolean;
  onCompressContext?: () => void | Promise<void>;
  visibilityEvents: LiveToolEvent[];
  setActivityView: (view: "summary" | "trace" | "screen") => void;
  onSelectTab: ((tab: AgentWorkbenchTabId) => void) | undefined;
  onOpenArtifact: ((path: string) => void) | undefined;
  openMainProcess: () => void;
  openSubagentProcess: (agentId: string) => void;
  setSelectedBlockId: (id: string | null) => void;
  setManualBlockSelection: (val: boolean) => void;
}) {
  const { t } = useI18n();
  const { agentStatusLabel, agentStatusClass } = useAgentWorkbenchI18n();

  // Visibility (capability routing / delegation / skill-catalog) decisions.
  // Deliberately de-emphasised: collapsed by default, small text,
  // transparent background. Latest visibility item wins.
  const lastVisibilityEvent =
    visibilityEvents[visibilityEvents.length - 1] ?? null;
  const visibilitySteps = useMemo<VisibilityStep[]>(() => {
    const raw = lastVisibilityEvent?.input?.steps;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (step): step is VisibilityStep =>
        !!step &&
        typeof step === "object" &&
        typeof (step as VisibilityStep).decision_point === "string" &&
        typeof (step as VisibilityStep).conclusion === "string" &&
        typeof (step as VisibilityStep).basis === "string",
    );
  }, [lastVisibilityEvent]);
  const [visibilityOpen, setVisibilityOpen] = useState(false);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Keep the workbench focused: computer replay only becomes a peer view
          when there is a real browser or independent-agent process to show. */}
      <div className="flex items-center gap-4 border-b border-border-subtle px-5 py-2">
        {[
          { id: "summary" as const, label: t.agentWorkbenchPanel.summaryLabel },
          ...(hasIndependentTrace
            ? [
                {
                  id: "trace" as const,
                  label: t.agentWorkbench.activityTrace,
                },
              ]
            : []),
          ...(hasComputerActivity
            ? [
                {
                  id: "screen" as const,
                  label: t.agentWorkbench.computerView,
                },
              ]
            : []),
        ].map((view) => (
          <button
            key={view.id}
            type="button"
            onClick={() => setActivityView(view.id)}
            className={cn(
              "border-b border-transparent pb-1 text-xs font-medium transition-colors",
              effectiveActivityView === view.id
                ? "border-foreground/70 text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {view.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground font-mono">
          {selectedRosterSeat
            ? selectedRosterSeat.name
            : (selectedAgent?.label ??
              mainAgentName ??
              t.agentWorkbenchPanel.mainComputer)}
        </span>
      </div>

      {/* View content */}
      {effectiveActivityView === "summary" ? (
        creationFocusAgent ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/70 p-3">
            <div className="mx-auto w-full max-w-xl">
              <AgentCreationCard
                agent={creationFocusAgent}
                agentStatusClass={agentStatusClass}
                agentStatusLabel={agentStatusLabel}
              />
            </div>
          </div>
        ) : (
          <AgentSummaryPage
            phases={phases}
            diffEntries={visibleDiffEntries}
            agentTiles={agentTiles}
            blocks={blocks}
            focusedProcessEvent={focusedProcessEvent}
            focusedEventId={focusedEventId}
            progressOutline={progressOutline}
            userInput={userInput}
            terminalState={terminalState}
            contextTokens={contextTokens}
            maxContextTokens={maxContextTokens}
            isCompressingContext={isCompressingContext}
            onCompressContext={onCompressContext}
            onSelectTab={onSelectTab}
            onOpenArtifact={onOpenArtifact}
          />
        )
      ) : effectiveActivityView === "trace" ? (
        selectedRosterSeat ? (
          rosterBlocks.length > 0 ? (
            <ActivityTraceView
              blocks={rosterBlocks}
              currentBlockId={pickCurrentWorkBlock(rosterBlocks)?.id ?? null}
              emptyText={t.agentWorkbenchPanel.waitingForSubagentOutput}
              subtitle={rosterSeatRoleLabel(selectedRosterSeat, t)}
              title={selectedRosterSeat.name}
              onSelectBlock={(blockId) => {
                setSelectedBlockId(blockId);
                setManualBlockSelection(true);
              }}
            />
          ) : (
            <RosterComputerPlaceholder
              seat={selectedRosterSeat}
              onOpenMain={openMainProcess}
            />
          )
        ) : (
          <ActivityTraceView
            blocks={screenBlocks}
            currentBlockId={screenFrame.block?.id ?? null}
            emptyText={
              selectedAgent
                ? t.agentWorkbenchPanel.waitingForSubagentOutput
                : t.agentWorkbench.traceFeedEmpty
            }
            subtitle={
              selectedAgent
                ? repairMojibakeText(
                    selectedAgent.role ??
                      selectedAgent.taskLabel ??
                      selectedAgent.task,
                  )
                : currentPhaseTitleText
            }
            title={
              selectedAgent
                ? `${selectedAgent.label} · ${repairMojibakeText(
                    selectedAgent.codename ??
                      selectedAgent.name ??
                      selectedAgent.label,
                  )}`
                : t.agentWorkbenchPanel.mainComputer
            }
            onSelectBlock={(blockId) => {
              setSelectedBlockId(blockId);
              setManualBlockSelection(true);
            }}
          />
        )
      ) : (
        <div className="flex min-h-0 flex-1 flex-col bg-background/35">
          {/* Header: agent identity + progress (hidden for roster seats — the placeholder shows identity inline) */}
          {!selectedRosterSeat && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border-subtle px-5 py-2.5">
              <MonitorIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
                <span
                  className={cn(
                    "inline-block size-1.5 rounded-full",
                    selectedAgent
                      ? agentRunDotClass(selectedAgent.status)
                      : agentRunDotClass(mainRunState),
                  )}
                />
                {selectedAgent
                  ? `${selectedAgent.label} · ${repairMojibakeText(
                      selectedAgent.codename ?? selectedAgent.name,
                    )}`
                  : mainPhaseStatusLabel(mainPhases, t)}
              </span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                {t.agentWorkbench.stepCount(
                  screenProgress.total || phases.length,
                )}
              </span>
            </div>
          )}

          {/* Tool call timeline */}
          {selectedRosterSeat ? (
            rosterBlocks.length > 0 ? (
              <ActivityTraceView
                blocks={rosterBlocks}
                currentBlockId={pickCurrentWorkBlock(rosterBlocks)?.id ?? null}
                emptyText={t.agentWorkbenchPanel.waitingForSubagentOutput}
                subtitle={rosterSeatRoleLabel(selectedRosterSeat, t)}
                title={selectedRosterSeat.name}
                onSelectBlock={(blockId) => {
                  setSelectedBlockId(blockId);
                  setManualBlockSelection(true);
                }}
              />
            ) : (
              <RosterComputerPlaceholder
                seat={selectedRosterSeat}
                onOpenMain={openMainProcess}
              />
            )
          ) : selectedAgent ? (
            <SubagentProcessView
              agent={selectedAgent}
              blocks={screenBlocks}
              currentBlockId={screenFrame.block?.id ?? null}
              onOpenMain={openMainProcess}
              onSelectBlock={(blockId) => {
                setSelectedBlockId(blockId);
                setManualBlockSelection(true);
              }}
            />
          ) : agentTiles.length > 0 ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/35">
              <div className="mx-auto w-full max-w-2xl px-5 py-4">
                <div className="mb-3 text-center">
                  <MonitorIcon className="mx-auto mb-2 size-8 text-muted-foreground/50" />
                  <p className="text-sm font-medium text-foreground">
                    {t.agentWorkbenchPanel.computerViewSubtitle}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t.agentWorkbenchPanel.computerViewSelectHint}
                  </p>
                </div>
                <div className="space-y-2">
                  {agentTiles.map((agent) => {
                    const agentLabel = repairMojibakeText(
                      agent.codename ?? agent.name ?? agent.label,
                    );
                    return (
                      <button
                        key={agent.id}
                        type="button"
                        onClick={() => openSubagentProcess(agent.id)}
                        className={cn(
                          "group flex w-full items-center gap-3 rounded-lg border border-border-default bg-background/80 px-4 py-3 text-left transition-colors hover:border-border hover:bg-muted/30",
                        )}
                      >
                        <div className="flex size-10 shrink-0 items-center justify-center rounded-md border border-border-default bg-muted/30 text-xl">
                          {agent.avatar ? (
                            <span aria-hidden="true">{agent.avatar}</span>
                          ) : (
                            <BotIcon className="size-5 text-muted-foreground" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-semibold text-foreground">
                              {agent.label}
                            </span>
                            <span
                              className={cn(
                                "inline-flex size-1.5 shrink-0 rounded-full",
                                agentRunDotClass(agent.status),
                              )}
                            />
                            <span className="text-xs text-muted-foreground">
                              {dockAgentStatusLabel(agent.status, t)}
                            </span>
                          </div>
                          <div className="mt-0.5 truncate text-xs text-muted-foreground">
                            {agent.role
                              ? repairMojibakeText(agent.role)
                              : agentLabel}
                          </div>
                          {agent.task && (
                            <div className="mt-1 truncate text-xs text-muted-foreground/70">
                              {repairMojibakeText(agent.task)}
                            </div>
                          )}
                        </div>
                        <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground" />
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center bg-muted/30 px-6 text-center">
              <div className="relative mb-3.5">
                <div className="relative flex size-12 items-center justify-center rounded-lg border border-border bg-card">
                  <MonitorIcon
                    className="size-5 text-muted-foreground/50"
                    strokeWidth={1.5}
                  />
                </div>
              </div>
              <p className="text-sm font-medium text-muted-foreground/80">
                {t.agentWorkbenchPanel.computerViewEmpty}
              </p>
              <p className="mt-1.5 max-w-xs text-xs leading-relaxed text-muted-foreground/55">
                {t.agentWorkbenchPanel.computerViewEmptyDesc}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Visibility decisions — de-emphasised surface: collapsed by default,
          small text, transparent background. Latest visibility item wins. */}
      {lastVisibilityEvent && visibilitySteps.length > 0 ? (
        <div className="shrink-0 border-t border-border-subtle bg-background/35">
          <button
            type="button"
            onClick={() => setVisibilityOpen((open) => !open)}
            className="flex w-full items-center gap-1.5 px-5 py-1.5 text-left transition-colors hover:bg-muted/30"
            aria-expanded={visibilityOpen}
          >
            {visibilityOpen ? (
              <ChevronDownIcon className="size-3 shrink-0 text-muted-foreground/60" />
            ) : (
              <ChevronRightIcon className="size-3 shrink-0 text-muted-foreground/60" />
            )}
            <span className="text-[11px] font-medium text-muted-foreground">
              {t.agentWorkbenchPanel.visibilityPanelTitle}
            </span>
            <span className="rounded-full bg-muted/60 px-1.5 text-[10px] tabular-nums text-muted-foreground/65">
              {visibilitySteps.length}
            </span>
          </button>
          {visibilityOpen && (
            <div className="space-y-1.5 px-5 pb-2.5">
              {visibilitySteps.map((step, index) => (
                <div
                  key={`${step.decision_point}:${index}`}
                  className="rounded-md border border-border-subtle bg-background/40 px-2 py-1.5"
                >
                  <span className="text-[10px] font-medium text-muted-foreground/60">
                    {t.agentWorkbenchPanel.visibilityStep} {index + 1}
                  </span>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-foreground/75">
                    {step.conclusion}
                  </p>
                  <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground/60">
                    {step.basis}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

export const AgentKanbanView = memo(AgentKanbanViewImpl);
