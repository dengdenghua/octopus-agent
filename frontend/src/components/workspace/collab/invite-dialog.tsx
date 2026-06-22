import { useEffect, useMemo, useState } from "react";
import {
  BotIcon,
  CheckIcon,
  CopyIcon,
  EyeIcon,
  LinkIcon,
  Loader2Icon,
  PlusIcon,
  SearchIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAgents, useLocalCliAgents } from "@/core/agents";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import type { Agent } from "@/core/agents/types";
import { copyTextToClipboard } from "@/core/clipboard";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  createTeamInvite,
  updateTeam,
  type Team,
  type TeamParticipantRole,
} from "@/core/teams";
import { cn } from "@/lib/utils";

interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roomId: string;
  threadId?: string | null;
  team?: Team | null;
  onTeamChange?: (team: Team) => void;
}

function appendInviteThread(path: string, threadId?: string | null) {
  const normalizedThreadId = threadId?.trim();
  if (!normalizedThreadId || normalizedThreadId === "new") return path;

  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}thread=${encodeURIComponent(normalizedThreadId)}`;
}

function agentDisplayName(agent: Agent) {
  return agent.display_name?.trim() || agent.name;
}

function resolveAgentAvatar(agent: Agent) {
  if (!agent.avatar_url) return null;
  const src = withAgentAvatarVersion(agent.avatar_url);
  return src.startsWith("http") ? src : `${getBackendBaseURL()}${src}`;
}

export function InviteDialog({
  open,
  onOpenChange,
  roomId,
  threadId,
  team,
  onTeamChange,
}: InviteDialogProps) {
  const { t } = useI18n();
  const { agents: builtinAgents, isLoading: agentsLoading } = useAgents();
  const { cliAgents } = useLocalCliAgents();
  // Detected local CLIs (Claude Code / Codex / …) sit alongside built-in
  // agents in the picker, so 拉群 can pull them in like any other member.
  const agents = useMemo(
    () => [...cliAgents, ...builtinAgents],
    [cliAgents, builtinAgents],
  );
  const [copied, setCopied] = useState(false);
  const [inviteLink, setInviteLink] = useState("");
  const [loading, setLoading] = useState(false);
  const [inviteRole, setInviteRole] = useState<TeamParticipantRole>("member");
  const [agentQuery, setAgentQuery] = useState("");
  const [addingAgentIds, setAddingAgentIds] = useState<Set<string>>(
    () => new Set(),
  );

  const teamMemberNames = useMemo(
    () => new Set((team?.members ?? []).map((member) => member.name)),
    [team?.members],
  );

  const filteredAgents = useMemo(() => {
    const query = agentQuery.trim().toLowerCase();
    if (!query) return agents;
    return agents.filter((agent) =>
      [agent.name, agent.display_name ?? "", agent.description]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [agentQuery, agents]);

  const addableFilteredAgents = useMemo(
    () => filteredAgents.filter((agent) => !teamMemberNames.has(agent.name)),
    [filteredAgents, teamMemberNames],
  );

  useEffect(() => {
    let cancelled = false;
    if (!open || !roomId) return;
    setLoading(true);
    void createTeamInvite(roomId, { role: inviteRole })
      .then((invite) => {
        if (cancelled) return;
        const path = appendInviteThread(
          invite.invite_hash_path || invite.invite_path,
          threadId,
        );
        setInviteLink(`${window.location.origin}${path}`);
      })
      .catch(() => {
        if (!cancelled) toast.error(t.collab.copyFailed);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [inviteRole, open, roomId, threadId, t.collab.copyFailed]);

  const handleCopy = async () => {
    if (!inviteLink) return;
    try {
      await copyTextToClipboard(inviteLink);
      setCopied(true);
      toast.success(t.collab.linkCopied);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t.collab.copyFailed);
    }
  };

  const handleAddAgents = async (nextAgents: Agent[]) => {
    if (!team) return;
    const additions = nextAgents.filter(
      (agent) => !teamMemberNames.has(agent.name),
    );
    if (additions.length === 0) return;

    setAddingAgentIds(new Set(additions.map((agent) => agent.name)));
    try {
      const members = [...team.members, ...additions];
      const updated = await updateTeam(team.id, {
        id: team.id,
        name: team.name,
        members,
        leaderId: team.leaderId ?? members[0]?.name ?? null,
      });
      onTeamChange?.(updated);
      toast.success(`已添加 ${additions.length} 个 Agent`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "添加 Agent 失败");
    } finally {
      setAddingAgentIds(new Set());
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="px-6 pb-3 pt-5">
          <DialogTitle>{t.collab.inviteDialogTitle}</DialogTitle>
          <DialogDescription>{t.collab.inviteDialogDesc}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 px-6 pb-5 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
          <section className="min-w-0 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setInviteRole("member")}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left transition-colors",
                  inviteRole === "member"
                    ? "border-primary/40 bg-primary/10 text-foreground"
                    : "border-border bg-muted/20 text-muted-foreground hover:bg-muted/40",
                )}
              >
                <span className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <ShieldCheckIcon className="size-4" />
                  成员
                </span>
                <span className="block text-xs text-muted-foreground">
                  可发起 AI 任务和参与协作
                </span>
              </button>
              <button
                type="button"
                onClick={() => setInviteRole("viewer")}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left transition-colors",
                  inviteRole === "viewer"
                    ? "border-primary/40 bg-primary/10 text-foreground"
                    : "border-border bg-muted/20 text-muted-foreground hover:bg-muted/40",
                )}
              >
                <span className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <EyeIcon className="size-4" />
                  旁观
                </span>
                <span className="block text-xs text-muted-foreground">
                  可看进展和留言，不启动任务
                </span>
              </button>
            </div>

            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                <LinkIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={loading ? t.collab.generatingLink : inviteLink}
                  readOnly
                  className="pl-9"
                />
              </div>
              <Button
                onClick={handleCopy}
                variant="outline"
                disabled={!inviteLink || loading}
              >
                {copied ? (
                  <CheckIcon className="size-4" />
                ) : (
                  <CopyIcon className="size-4" />
                )}
              </Button>
            </div>
          </section>

          <section className="min-w-0 rounded-lg border border-border/60 bg-muted/10">
            <div className="border-b border-border/50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <BotIcon className="size-4 text-primary" />
                    添加 Agent
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    已有 {team?.members.length ?? 0} 个 · 可选 {agents.length}{" "}
                    个
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 shrink-0 rounded-lg px-2.5 text-xs"
                  disabled={!team || addableFilteredAgents.length === 0}
                  onClick={() => void handleAddAgents(addableFilteredAgents)}
                >
                  <PlusIcon className="mr-1 size-3.5" />
                  添加当前筛选
                </Button>
              </div>

              <div className="relative mt-2">
                <SearchIcon className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={agentQuery}
                  onChange={(event) => setAgentQuery(event.target.value)}
                  placeholder="搜索 Agent 或角色"
                  className="h-8 rounded-lg border-border/60 bg-background/70 pl-8 text-xs"
                />
              </div>
            </div>

            <div className="max-h-[280px] overflow-y-auto p-2">
              {agentsLoading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                  <Loader2Icon className="size-4 animate-spin" />
                  加载 Agent 中...
                </div>
              ) : filteredAgents.length === 0 ? (
                <div className="py-10 text-center text-sm text-muted-foreground">
                  没有匹配的 Agent
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredAgents.map((agent) => {
                    const displayName = agentDisplayName(agent);
                    const inTeam = teamMemberNames.has(agent.name);
                    const isAdding = addingAgentIds.has(agent.name);
                    const avatarSrc = resolveAgentAvatar(agent);
                    return (
                      <div
                        key={agent.name}
                        className={cn(
                          "flex items-center gap-2 rounded-lg px-2 py-1.5",
                          inTeam ? "bg-muted/35" : "hover:bg-muted/40",
                        )}
                      >
                        <div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border/60 bg-background text-xs font-semibold text-muted-foreground">
                          {avatarSrc ? (
                            <img
                              src={avatarSrc}
                              alt={displayName}
                              className="size-full object-cover"
                            />
                          ) : agent.icon?.trim() ? (
                            agent.icon
                          ) : (
                            displayName.charAt(0)
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex min-w-0 items-center gap-1.5">
                            <span className="truncate text-sm font-medium">
                              {displayName}
                            </span>
                          </div>
                          <div className="truncate text-[11px] text-muted-foreground">
                            {agent.description || agent.name}
                          </div>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant={inTeam ? "ghost" : "outline"}
                          className="h-7 shrink-0 rounded-lg px-2 text-xs"
                          disabled={!team || inTeam || isAdding}
                          onClick={() => void handleAddAgents([agent])}
                        >
                          {isAdding ? (
                            <Loader2Icon className="size-3.5 animate-spin" />
                          ) : inTeam ? (
                            "已在 Team"
                          ) : (
                            "添加"
                          )}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
