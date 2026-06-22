import {
  ClipboardListIcon,
  FolderIcon,
  MonitorIcon,
  UsersIcon,
  XIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { FileTree } from "@/components/workspace/file-tree";
import { WorkDirSelector } from "@/components/workspace/workdir-selector";
import type { Team } from "@/core/teams";
import { cn } from "@/lib/utils";

import { TeamRoster } from "./team-roster";
import { TeamTasksPanel } from "./team-tasks-panel";

export type TeamWorkbenchTabId = "tasks" | "workspace" | "members";

interface TeamWorkbenchPanelProps {
  activeTab: TeamWorkbenchTabId;
  onSelectTab: (tab: TeamWorkbenchTabId) => void;
  onClose?: () => void;
  roomId: string | null | undefined;
  team: Team | null;
  workDir: string;
  onWorkDirChange: (path: string) => void;
  currentParticipantId?: string;
  canManageTasks?: boolean;
  onMention?: (name: string) => void;
  className?: string;
}

const TABS: Array<{
  id: TeamWorkbenchTabId;
  label: string;
  Icon: typeof ClipboardListIcon;
}> = [
  { id: "members", label: "群成员", Icon: UsersIcon },
  { id: "tasks", label: "待办 plan", Icon: ClipboardListIcon },
  { id: "workspace", label: "工作区", Icon: FolderIcon },
];

export function TeamWorkbenchPanel({
  activeTab,
  onSelectTab,
  onClose,
  roomId,
  team,
  workDir,
  onWorkDirChange,
  currentParticipantId,
  canManageTasks = true,
  onMention,
  className,
}: TeamWorkbenchPanelProps) {
  return (
    <div
      data-testid="team-workbench-panel"
      className={cn(
        "flex size-full min-h-0 flex-col bg-[color:color-mix(in_oklch,var(--muted)_46%,var(--background))]",
        className,
      )}
    >
      <header className="relative shrink-0 border-b border-border/60 bg-background/95 px-2 pt-2 sm:px-3">
        <div className="flex min-w-0 items-end gap-1.5 sm:gap-2">
          <div className="mb-1.5 hidden h-8 shrink-0 items-center gap-2 rounded-lg border border-border/60 bg-background/85 px-2 text-xs font-medium text-muted-foreground shadow-sm min-[520px]:flex">
            <MonitorIcon className="size-4" />
            <span>Team 工作台</span>
          </div>
          <div
            data-testid="team-workbench-tabs"
            role="tablist"
            aria-label="Team 工作台"
            className="flex min-w-0 flex-1 items-end gap-0.5 overflow-x-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {TABS.map(({ id, label, Icon }) => {
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  type="button"
                  data-testid={`team-workbench-tab-${id}`}
                  role="tab"
                  aria-selected={active}
                  onClick={() => onSelectTab(id)}
                  className={cn(
                    "inline-flex h-9 max-w-[9rem] shrink-0 items-center gap-1 rounded-lg border border-transparent px-2 text-xs font-medium transition-all sm:max-w-[11rem] sm:gap-1.5 sm:px-3 sm:text-sm",
                    active
                      ? "-mb-px h-10 rounded-b-none border-border/70 border-b-background bg-background text-foreground shadow-sm"
                      : "mb-1 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )}
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-primary" : "text-muted-foreground/80",
                    )}
                  />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </div>
          {onClose && (
            <Button
              variant="ghost"
              size="icon"
              className="mb-1 size-8 shrink-0 rounded-lg border border-transparent text-muted-foreground hover:border-border/60 hover:bg-muted/60 hover:text-foreground"
              onClick={onClose}
              title="关闭工作台"
            >
              <XIcon className="size-4" />
            </Button>
          )}
        </div>
        {activeTab === "workspace" && (
          <WorkspacePathBar
            workDir={workDir}
            onWorkDirChange={onWorkDirChange}
          />
        )}
      </header>

      <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70">
        {activeTab === "tasks" ? (
          <TeamTasksPanel
            roomId={roomId}
            team={team}
            canManageTasks={canManageTasks}
          />
        ) : activeTab === "workspace" ? (
          <WorkspacePage workDir={workDir} />
        ) : (
          <TeamRoster
            team={team}
            currentParticipantId={currentParticipantId}
            onMention={onMention}
          />
        )}
      </main>
    </div>
  );
}

function WorkspacePathBar({
  workDir,
  onWorkDirChange,
}: {
  workDir: string;
  onWorkDirChange: (path: string) => void;
}) {
  return (
    <div className="mt-2 flex items-center gap-2 border-t border-border/45 py-2">
      <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-border/60 bg-muted/25 px-2.5 py-1.5">
        <FolderIcon className="size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-medium text-muted-foreground">
            当前工作区
          </div>
          <div className="truncate font-mono text-[11px] text-foreground">
            {workDir || "未选择目录"}
          </div>
        </div>
      </div>
      <WorkDirSelector
        workDir={workDir}
        onWorkDirChange={onWorkDirChange}
        className="shrink-0"
      />
    </div>
  );
}

function WorkspacePage({ workDir }: { workDir: string }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 p-1">
        <FileTree workDir={workDir} className="h-full" />
      </div>
    </div>
  );
}
