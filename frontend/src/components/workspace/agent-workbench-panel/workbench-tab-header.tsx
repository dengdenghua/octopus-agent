import {
  CheckIcon,
  LayoutGridIcon,
  LocateFixedIcon,
  PanelRightCloseIcon,
  XIcon,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { emitLocateAgentWorkbenchEvent } from "../agent-workbench-events";
import type { AgentWorkbenchTabId } from "../agent-workbench-utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MainComputerStatusButton } from "./main-computer-status-button";
import type { AgentRunState } from "../agent-run-status";

export type WorkbenchTab = {
  id: AgentWorkbenchTabId;
  label: string;
  Icon: LucideIcon;
};

export function WorkbenchTabHeader({
  mainButton,
  visibleTabs,
  workbenchTabs,
  closedTabs,
  effectiveActiveTab,
  onTabClick,
  onTabClose,
  locatableTranscriptEventId,
  onClose,
  workspaceLabel,
  showWorkspaceLabel,
  mainRunStatusLabel,
}: {
  mainButton: {
    active: boolean;
    label: string;
    onClick: () => void;
    runState: AgentRunState;
    title: string;
  };
  visibleTabs: WorkbenchTab[];
  workbenchTabs: WorkbenchTab[];
  closedTabs: Set<AgentWorkbenchTabId>;
  effectiveActiveTab: AgentWorkbenchTabId;
  onTabClick: (tabId: AgentWorkbenchTabId) => void;
  onTabClose: (tabId: AgentWorkbenchTabId) => void;
  locatableTranscriptEventId: string;
  onClose?: () => void;
  workspaceLabel?: string;
  showWorkspaceLabel?: boolean;
  mainRunStatusLabel?: string;
}) {
  const { t } = useI18n();
  return (
    <header className="relative shrink-0 border-b border-border-default px-3 py-2.5">
      <div className="flex items-center gap-2.5">
        <MainComputerStatusButton
          active={mainButton.active}
          label={mainButton.label}
          onClick={mainButton.onClick}
          runState={mainButton.runState}
          title={mainButton.title}
        />
        {showWorkspaceLabel && visibleTabs.length === 0 ? (
          <div className="min-w-0 flex-1 px-0.5">
            <div
              className="truncate text-xs font-medium text-foreground/85"
              title={workspaceLabel ?? ""}
            >
              {workspaceLabel}
            </div>
            {mainRunStatusLabel ? (
              <div className="mt-0.5 truncate text-xs text-muted-foreground/65">
                {mainRunStatusLabel}
              </div>
            ) : null}
          </div>
        ) : null}
        <div
          role="tablist"
          aria-label={t.agentWorkbench.agentComputer}
          className={cn(
            "min-w-0 items-center gap-1 overflow-x-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            visibleTabs.length === 0 && showWorkspaceLabel
              ? "hidden"
              : "flex flex-1",
          )}
        >
          {visibleTabs.map(({ id, label, Icon }) => {
            const active = id === effectiveActiveTab;
            return (
              <div
                key={id}
                className={cn(
                  "group inline-flex h-8 max-w-[11rem] shrink-0 items-center gap-1.5 border border-transparent text-sm font-medium shadow-none transition-colors",
                  active
                    ? "border-border-subtle text-foreground"
                    : "text-muted-foreground hover:border-border-subtle hover:bg-background/45 hover:text-foreground",
                )}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={active}
                  title={label}
                  onClick={() => onTabClick(id)}
                  className="flex h-full min-w-0 items-center gap-1.5 pl-2.5"
                >
                  <Icon className="size-4 shrink-0" />
                  <span className="truncate">{label}</span>
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onTabClose(id);
                  }}
                  className={cn(
                    "mr-0.5 flex size-8 shrink-0 items-center justify-center rounded-md transition-colors",
                    active
                      ? "text-muted-foreground/70 hover:bg-muted hover:text-foreground focus-visible:bg-muted"
                      : "text-muted-foreground/0 group-hover:text-muted-foreground/70 hover:!bg-muted hover:!text-foreground focus-visible:text-muted-foreground/70 focus-visible:bg-muted",
                  )}
                  aria-label={t.editorTabs.closeTabAria(label)}
                  title={t.editorTabs.closeTabAria(label)}
                >
                  <XIcon className="size-3" />
                </button>
              </div>
            );
          })}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
              title={t.agentWorkbenchPanel.tabList}
              aria-label={t.agentWorkbenchPanel.tabList}
            >
              <LayoutGridIcon className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            {workbenchTabs.map(({ id, label, Icon }) => {
              const visible = !closedTabs.has(id);
              return (
                <DropdownMenuItem
                  key={id}
                  className="gap-2"
                  onClick={() =>
                    visible ? onTabClose(id) : onTabClick(id)
                  }
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate">{label}</span>
                  {visible && <CheckIcon className="size-3.5 text-primary" />}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
        {locatableTranscriptEventId ? (
          <button
            type="button"
            className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
            title={t.agentWorkbenchPanel.locateTranscriptEvent}
            aria-label={t.agentWorkbenchPanel.locateTranscriptEvent}
            onClick={() =>
              emitLocateAgentWorkbenchEvent({
                eventId: locatableTranscriptEventId,
              })
            }
          >
            <LocateFixedIcon className="size-3.5" />
          </button>
        ) : null}
        {onClose ? (
          <button
            type="button"
            className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
            title={t.agentWorkbenchPanel.collapseWorkbench}
            aria-label={t.agentWorkbenchPanel.collapseWorkbench}
            onClick={onClose}
          >
            <PanelRightCloseIcon className="size-3.5" />
          </button>
        ) : null}
      </div>
    </header>
  );
}
