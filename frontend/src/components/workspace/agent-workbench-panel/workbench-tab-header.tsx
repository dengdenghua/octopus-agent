import { memo, useContext, type CSSProperties } from "react";
import { WorkbenchHeaderSlot } from "../workbench-header-slot";

import { CheckIcon, LayoutGridIcon, XIcon } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import type { AgentWorkbenchTabId } from "../agent-workbench-utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MainComputerStatusButton } from "./main-computer-status-button";
import type { AgentRunState } from "../agent-run-status";
import { Tooltip } from "../tooltip";
import { useElectronTitleBar } from "@/components/electron-title-bar";

export type WorkbenchTab = {
  id: AgentWorkbenchTabId;
  label: string;
  Icon: LucideIcon;
};

function WorkbenchTabHeaderImpl({
  mainButton,
  visibleTabs,
  workbenchTabs,
  closedTabs,
  effectiveActiveTab,
  onTabClick,
  onTabClose,
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
  onClose?: () => void;
  workspaceLabel?: string;
  showWorkspaceLabel?: boolean;
  mainRunStatusLabel?: string;
}) {
  const { t } = useI18n();
  const setHeaderSlot = useContext(WorkbenchHeaderSlot);
  const { controlsSide } = useElectronTitleBar();
  return (
    <header
      data-slot="workbench-tab-header"
      className="relative shrink-0 border-b border-border-default px-2.5 py-1.5"
      style={
        {
          paddingRight:
            controlsSide === "right"
              ? "calc(var(--window-controls-safe-inset, 138px) + 0.625rem)"
              : undefined,
          WebkitAppRegion: controlsSide === "right" ? "drag" : undefined,
        } as CSSProperties
      }
    >
      <div
        className="flex items-center gap-2.5"
        style={
          controlsSide === "right"
            ? ({ WebkitAppRegion: "no-drag" } as CSSProperties)
            : undefined
        }
      >
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
                  "group inline-flex h-8 max-w-[11rem] shrink-0 items-center border-b-2 border-transparent text-sm font-medium transition-colors",
                  active
                    ? "border-foreground/75 text-foreground"
                    : "text-muted-foreground hover:bg-muted/35 hover:text-foreground",
                )}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={active}
                  title={label}
                  onClick={() => onTabClick(id)}
                  className={cn(
                    "flex h-full min-w-0 items-center gap-1.5 pl-2.5",
                    id === "workspace" ? "pr-2.5" : "pr-1.5",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  <span className="truncate">{label}</span>
                </button>
                {id !== "workspace" ? (
                  <button
                    type="button"
                    aria-label={t.editorTabs.closeTabAria(label)}
                    title={t.editorTabs.closeTabAria(label)}
                    onClick={() => onTabClose(id)}
                    className="mr-1 flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground/65 opacity-0 transition-[color,background-color,opacity] hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <XIcon className="size-3" />
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
        <DropdownMenu>
          <Tooltip content={t.agentWorkbenchPanel.tabList}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
                aria-label={t.agentWorkbenchPanel.tabList}
              >
                <LayoutGridIcon className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="end" className="w-40">
            {workbenchTabs.map(({ id, label, Icon }) => {
              const visible = !closedTabs.has(id);
              return (
                <DropdownMenuItem
                  key={id}
                  className="gap-2"
                  onClick={() => (visible ? onTabClose(id) : onTabClick(id))}
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate">{label}</span>
                  {visible && <CheckIcon className="size-3.5 text-primary" />}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
        {setHeaderSlot && (
          <div ref={setHeaderSlot} className="flex shrink-0 items-center" />
        )}
        {onClose ? (
          <Tooltip content={t.collab.workbench.closeTitle}>
            <button
              type="button"
              onClick={onClose}
              className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
              aria-label={t.collab.workbench.closeTitle}
            >
              <XIcon className="size-4" />
            </button>
          </Tooltip>
        ) : null}
      </div>
    </header>
  );
}

export const WorkbenchTabHeader = memo(WorkbenchTabHeaderImpl);
