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
import { AgentAvatar } from "@/components/workspace/sidebar-footer";
import TeamRoleModelsPanel from "@/components/workspace/team-role-models-panel";
import {
  dedupeAgentsByName,
  useAgents,
  useLocalCliAgents,
  useMobileDevices,
} from "@/core/agents";
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
  const { agents: builtinAgents } = useAgents();
  const { cliAgents } = useLocalCliAgents();
  const { mobileAgents } = useMobileDevices();
  // Detected local CLIs + connected phones join the picker as members.
  const userAgents = useMemo(
    () => dedupeAgentsByName([...mobileAgents, ...cliAgents, ...builtinAgents]),
    [mobileAgents, cliAgents, builtinAgents],
  );
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

  const leader = useMemo(
    () => selected.find((agent) => agent.name === leaderId) ?? null,
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
      <DialogContent className="flex max-h-[min(760px,calc(100vh-2rem))] w-[min(980px,calc(100vw-2rem))] flex-col overflow-hidden p-0 sm:max-w-[980px]">
        <DialogHeader className="border-b px-5 py-4">
          <div className="flex min-w-0 items-start justify-between gap-5 pr-8">
            <div className="min-w-0">
              <DialogTitle className="text-base font-semibold">
                {t.createTeamDialog.title}
              </DialogTitle>
              <DialogDescription className="mt-1 text-sm text-muted-foreground">
                {t.createTeamDialog.description}
              </DialogDescription>
            </div>
            <div className="hidden shrink-0 items-center gap-2 text-[11px] text-muted-foreground md:flex">
              <span className="rounded-md border bg-muted/25 px-2 py-1">
                {t.createTeamDialog.memberCounter(selected.length, MAX_MEMBERS)}
              </span>
              <span className="max-w-32 truncate rounded-md border bg-muted/25 px-2 py-1">
                {t.createTeamDialog.leaderLabel}:{" "}
                {leader
                  ? leader.display_name || leader.name
                  : t.createTeamDialog.leaderUnset}
              </span>
            </div>
          </div>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 md:grid-cols-[minmax(0,1.08fr)_minmax(320px,0.92fr)]">
          <section className="flex min-h-0 flex-col border-r">
            <div className="space-y-3 border-b px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {t.createTeamDialog.selectMembersTitle}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {t.createTeamDialog.allAgents(userAgents.length)}
                  </p>
                </div>
                {selected.length >= MAX_MEMBERS && (
                  <span className="shrink-0 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-700 dark:text-amber-300">
                    {t.createTeamDialog.memberLimitReached}
                  </span>
                )}
              </div>
              <div className="relative">
                <SearchIcon className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-9 rounded-lg border-border/60 bg-muted/25 pl-9 text-sm"
                  placeholder={t.createTeamDialog.searchAgentsPlaceholder}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
              <div className="space-y-1">
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
                        "group flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                        isSelected
                          ? "bg-primary/5 text-muted-foreground"
                          : "hover:bg-accent disabled:opacity-35 disabled:hover:bg-transparent",
                      )}
                    >
                      <AgentAvatar
                        agent={agent}
                        className="size-9 rounded-lg text-[15px]"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <p className="truncate text-sm font-medium">
                            {displayName}
                          </p>
                          {isSelected && (
                            <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                              {t.createTeamDialog.selectedBadge}
                            </span>
                          )}
                        </div>
                        <p className="line-clamp-1 text-xs text-muted-foreground">
                          {agent.description}
                        </p>
                      </div>
                      <div
                        className={cn(
                          "flex size-7 shrink-0 items-center justify-center rounded-lg border transition-colors",
                          isSelected
                            ? "border-primary/20 bg-primary/10"
                            : "border-border/60 bg-background group-hover:border-primary/30 group-hover:bg-primary/10",
                        )}
                      >
                        {isSelected ? (
                          <CheckIcon className="size-3.5 text-primary" />
                        ) : (
                          <PlusIcon className="size-3.5 text-muted-foreground group-hover:text-primary" />
                        )}
                      </div>
                    </button>
                  );
                })}
                {filtered.length === 0 && (
                  <div className="flex min-h-36 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                    {t.createTeamDialog.noMatches}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="flex min-h-0 flex-col bg-muted/15">
            <div className="space-y-3 border-b px-4 py-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  {t.createTeamDialog.teamNameLabel}
                </label>
                <Input
                  placeholder={t.createTeamDialog.teamNamePlaceholder}
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  className="h-9 rounded-lg bg-background text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border bg-background/70 px-3 py-2">
                  <p className="text-muted-foreground">
                    {t.createTeamDialog.membersLabel}
                  </p>
                  <p className="mt-1 text-base font-semibold">
                    {selected.length}/{MAX_MEMBERS}
                  </p>
                </div>
                <div className="rounded-lg border bg-background/70 px-3 py-2">
                  <p className="text-muted-foreground">
                    {t.createTeamDialog.leaderLabel}
                  </p>
                  <p className="mt-1 truncate text-sm font-semibold">
                    {leader
                      ? leader.display_name || leader.name
                      : t.createTeamDialog.leaderUnset}
                  </p>
                </div>
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <p className="text-sm font-medium">
                  {t.createTeamDialog.selected(selected.length, MAX_MEMBERS)}
                </p>
                {selected.length > 0 && (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => {
                      setSelected([]);
                      setLeaderId(null);
                    }}
                  >
                    {t.createTeamDialog.clearSelected}
                  </button>
                )}
              </div>

              {selected.length === 0 ? (
                <div className="mx-4 flex flex-1 items-center justify-center rounded-lg border border-dashed bg-background/50 px-6 text-center">
                  <div className="max-w-48 text-sm text-muted-foreground">
                    <div className="mx-auto mb-3 flex size-9 items-center justify-center rounded-lg bg-muted">
                      <PlusIcon className="size-4" />
                    </div>
                    <p>{t.createTeamDialog.emptyHintL1}</p>
                    <p>{t.createTeamDialog.emptyHintL2}</p>
                  </div>
                </div>
              ) : (
                <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
                  <div className="space-y-1.5">
                    {selected.map((agent, idx) => {
                      const displayName = agent.display_name ?? agent.name;
                      const isLeader = leaderId === agent.name;
                      return (
                        <div
                          key={agent.name}
                          className={cn(
                            "flex items-center gap-2 rounded-lg border bg-background px-2.5 py-2",
                            isLeader && "border-primary/35 bg-primary/5",
                          )}
                        >
                          <span className="w-4 text-center text-[10px] text-muted-foreground">
                            {idx + 1}
                          </span>
                          <AgentAvatar
                            agent={agent}
                            className="size-7 rounded-lg"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-medium">
                              {displayName}
                            </p>
                            {isLeader && (
                              <p className="text-[10px] text-primary">
                                {t.createTeamDialog.currentTl}
                              </p>
                            )}
                          </div>
                          <button
                            type="button"
                            className={cn(
                              "shrink-0 rounded-md px-2 py-1 text-[10px] transition-colors",
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
                            className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                            onClick={() => removeAgent(agent.name)}
                          >
                            <XIcon className="size-3" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Team config · per-role model tiering (cheap vs primary, cost control) */}
        <div className="border-t bg-background px-5 py-2.5">
          <TeamRoleModelsPanel />
        </div>

        <DialogFooter className="gap-2 border-t px-5 py-3">
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
            className="bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {t.createTeamDialog.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
