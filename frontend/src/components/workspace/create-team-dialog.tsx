import { CheckIcon, PlusIcon, SearchIcon, XIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import TeamRoleModelsPanel from "@/components/workspace/team-role-models-panel";
import { useAgents } from "@/core/agents";
import type { Agent } from "@/core/agents/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const MAX_MEMBERS = 10;

export interface TeamConfig {
  name: string;
  members: Agent[];
  leaderId: string | null;
}

export function CreateTeamDialog({
  open,
  onOpenChange,
  onCreateTeam,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreateTeam: (config: TeamConfig) => void;
}) {
  const { t } = useI18n();
  const { agents: userAgents } = useAgents();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Agent[]>([]);
  const [teamName, setTeamName] = useState("");
  const [leaderId, setLeaderId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!search.trim()) return userAgents;
    const q = search.toLowerCase();
    return userAgents.filter(
      (a) =>
        (a.display_name ?? a.name).toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q),
    );
  }, [userAgents, search]);

  const selectedSet = useMemo(
    () => new Set(selected.map((a) => a.name)),
    [selected],
  );

  const addAgent = useCallback(
    (agent: Agent) => {
      if (selected.length >= MAX_MEMBERS) return;
      if (selectedSet.has(agent.name)) return;
      setSelected((prev) => [...prev, agent]);
      if (!leaderId) setLeaderId(agent.name);
    },
    [selected, selectedSet, leaderId],
  );

  const removeAgent = useCallback(
    (name: string) => {
      setSelected((prev) => prev.filter((a) => a.name !== name));
      if (leaderId === name) {
        setLeaderId(selected.find((a) => a.name !== name)?.name ?? null);
      }
    },
    [leaderId, selected],
  );

  const handleCreate = () => {
    if (!teamName.trim() || selected.length === 0) return;
    onCreateTeam({ name: teamName.trim(), members: selected, leaderId });
    setSearch("");
    setSelected([]);
    setTeamName("");
    setLeaderId(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="p-0 overflow-hidden"
        style={{ maxWidth: "900px", width: "900px" }}
      >
        <DialogHeader className="px-6 pt-5 pb-3">
          <DialogTitle className="text-lg font-semibold">
            {t.createTeamDialog.title}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {t.createTeamDialog.description}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-5 gap-0" style={{ height: "440px" }}>
          {/* Left: Agent picker (3 cols) */}
          <div className="col-span-3 flex flex-col border-r">
            <div className="px-4 pt-3 pb-2">
              <div className="relative">
                <SearchIcon className="text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5" />
                <Input
                  className="pl-8 h-8 bg-muted/40 border-0 text-sm"
                  placeholder={t.common.search}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="px-4 pb-1">
              <p className="text-muted-foreground text-[10px] font-medium uppercase tracking-wider">
                {t.createTeamDialog.allAgents(userAgents.length)}
              </p>
            </div>
            <div className="flex flex-col gap-0.5 overflow-y-auto px-3 flex-1">
              {filtered.map((agent) => {
                const isSelected = selectedSet.has(agent.name);
                const displayName = agent.display_name ?? agent.name;
                return (
                  <button
                    key={agent.name}
                    type="button"
                    disabled={
                      isSelected ||
                      (!isSelected && selected.length >= MAX_MEMBERS)
                    }
                    onClick={() => addAgent(agent)}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-all group",
                      isSelected
                        ? "bg-primary/5 opacity-60"
                        : "hover:bg-accent disabled:opacity-30 disabled:hover:bg-transparent",
                    )}
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border/60 bg-muted text-[15px] leading-none">
                      {agent.icon?.trim() || (
                        <span className="text-xs font-semibold text-muted-foreground">
                          {displayName.charAt(0)}
                        </span>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {displayName}
                      </p>
                      <p className="text-muted-foreground truncate text-[11px] leading-tight">
                        {agent.description}
                      </p>
                    </div>
                    {isSelected ? (
                      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <CheckIcon className="text-primary size-3" />
                      </div>
                    ) : (
                      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-lg bg-muted/50 group-hover:bg-primary/10 transition-colors">
                        <PlusIcon className="text-muted-foreground group-hover:text-primary size-3" />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Right: Selected members (2 cols) */}
          <div className="col-span-2 flex flex-col bg-muted/20">
            <div className="px-4 pt-3 pb-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {t.createTeamDialog.selected(selected.length, MAX_MEMBERS)}
              </p>
            </div>
            {selected.length === 0 ? (
              <div className="flex-1 flex items-center justify-center px-4">
                <p className="text-muted-foreground text-center text-xs leading-relaxed">
                  {t.createTeamDialog.emptyHintL1}
                  <br />
                  {t.createTeamDialog.emptyHintL2}
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-1 overflow-y-auto px-3 flex-1">
                {selected.map((agent, idx) => {
                  const displayName = agent.display_name ?? agent.name;
                  const isLeader = leaderId === agent.name;
                  return (
                    <div
                      key={agent.name}
                      className={cn(
                        "flex items-center gap-2 rounded-lg bg-background px-2.5 py-1.5 border",
                        isLeader && "border-primary/30 bg-primary/5",
                      )}
                    >
                      <span className="text-muted-foreground text-[10px] w-3 text-center">
                        {idx + 1}
                      </span>
                      <div className="flex h-6 w-6 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border/60 bg-muted text-[13px] leading-none">
                        {agent.icon?.trim() || (
                          <span className="text-[10px] font-semibold text-muted-foreground">
                            {displayName.charAt(0)}
                          </span>
                        )}
                      </div>
                      <span className="min-w-0 flex-1 truncate text-xs font-medium">
                        {displayName}
                      </span>
                      <button
                        type="button"
                        className={cn(
                          "shrink-0 text-[10px] px-1.5 py-0.5 rounded-lg transition-colors",
                          isLeader
                            ? "bg-primary text-primary-foreground font-medium"
                            : "text-muted-foreground hover:text-primary hover:bg-primary/10",
                        )}
                        onClick={() => setLeaderId(agent.name)}
                        title={
                          isLeader
                            ? t.createTeamDialog.currentTl
                            : t.createTeamDialog.setAsTl
                        }
                      >
                        TL
                      </button>
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-destructive shrink-0 p-0.5 rounded hover:bg-destructive/10 transition-colors"
                        onClick={() => removeAgent(agent.name)}
                      >
                        <XIcon className="size-3" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="px-4 py-3 border-t mt-auto">
              <label className="text-muted-foreground text-[10px] font-medium uppercase tracking-wider mb-1.5 block">
                {t.createTeamDialog.teamNameLabel}
              </label>
              <Input
                placeholder={t.createTeamDialog.teamNamePlaceholder}
                value={teamName}
                onChange={(e) => setTeamName(e.target.value)}
                className="h-8 text-sm bg-background"
              />
            </div>
          </div>
        </div>

        {/* Team config · per-role model tiering (cheap vs primary, cost control) */}
        <div className="border-t px-6 py-2">
          <TeamRoleModelsPanel />
        </div>

        <DialogFooter className="px-6 py-3 border-t gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            {t.createTeamDialog.cancel}
          </Button>
          <Button
            size="sm"
            disabled={!teamName.trim() || selected.length === 0}
            onClick={handleCreate}
            className="bg-primary hover:bg-primary/90 text-primary-foreground"
          >
            {t.createTeamDialog.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
