import {
  CheckIcon,
  CoinsIcon,
  LogOutIcon,
  MessageCircleIcon,
  PlusIcon,
  SettingsIcon,
  ShieldCheckIcon,
  Trash2Icon,
  UsersRoundIcon,
  UserCircleIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { swallow } from "@/core/utils/log";
import { ACTIVE_AGENT_KEY, ROUTE_LOCKS } from "@/core/agents/active";
import { eventBus, emitAgentChanged, emitOpenSettings } from "@/core/events";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAgents } from "@/core/agents";
import type { Agent } from "@/core/agents";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  createTeam,
  deleteTeam as deleteTeamRoom,
  dispatchTeamUpdated,
  fetchTeams,
  migrateLegacyTeamsIfNeeded,
  readPreferredTeamId,
  writePreferredTeam,
  type Team as SidebarTeam,
} from "@/core/teams";
import { useMoliliLink } from "@/core/molili";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/utils";

// ─── Helpers ─────────────────────────────────────────────────────

function readActiveAgentName(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_AGENT_KEY);
  } catch (e) {
    swallow(e);
    return null;
  }
}

function isPlaceholderUsername(username?: string | null): boolean {
  const value = username?.trim().toLowerCase();
  return !value || value === "anonymous" || value === "__anonymous__";
}

function getAccountDisplayName(user: {
  mobile?: string;
  email?: string;
  username?: string;
  actor_id?: string;
}): string {
  return (
    user.mobile ||
    user.email ||
    (!isPlaceholderUsername(user.username) ? user.username : "") ||
    user.actor_id ||
    ""
  );
}

/** Resolve ``Agent.avatar_url`` to an absolute URL the browser can load. */
function resolveAvatarUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return withAgentAvatarVersion(url);
  }
  return withAgentAvatarVersion(`${getBackendBaseURL()}${url}`);
}

// ─── Avatar components ───────────────────────────────────────────

export function AgentAvatar({
  agent,
  className,
}: {
  agent: Agent | undefined;
  className?: string;
}) {
  const avatar = resolveAvatarUrl(agent?.avatar_url);
  const emoji = agent?.icon?.trim() || "";
  const initial = (agent?.display_name || agent?.name || "?")
    .trim()
    .charAt(0)
    .toUpperCase();
  return (
    <span
      className={cn(
        "flex size-6 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border/60 bg-muted text-[13px] leading-none",
        !emoji && !avatar && "font-semibold text-muted-foreground text-[11px]",
        className,
      )}
    >
      {avatar ? (
        <img
          src={avatar}
          alt={agent?.display_name || agent?.name || ""}
          className="size-full object-cover"
          loading="lazy"
        />
      ) : emoji ? (
        emoji
      ) : (
        initial
      )}
    </span>
  );
}

export function StackedMembers({
  members,
  agentByName,
  max = 3,
}: {
  members: SidebarTeam["members"];
  agentByName: Map<string, Agent>;
  max?: number;
}) {
  const list = members ?? [];
  const shown = list.slice(0, max);
  const extra = list.length - shown.length;
  return (
    <span className="flex shrink-0 items-center">
      {shown.map((m, i) => {
        const agent = agentByName.get(m.name);
        const avatar = resolveAvatarUrl(agent?.avatar_url);
        const emoji = agent?.icon?.trim() || "";
        const initial = (m.display_name || m.name || "?")
          .charAt(0)
          .toUpperCase();
        return (
          <span
            key={m.name}
            style={{ marginLeft: i === 0 ? 0 : -8 }}
            className="flex size-6 items-center justify-center overflow-hidden rounded-md border border-border/60 bg-muted text-[13px] leading-none ring-1 ring-background"
          >
            {avatar ? (
              <img
                src={avatar}
                alt={m.display_name || m.name}
                className="size-full object-cover"
                loading="lazy"
              />
            ) : emoji ? (
              emoji
            ) : (
              <span className="text-[10px] font-semibold text-muted-foreground">
                {initial}
              </span>
            )}
          </span>
        );
      })}
      {extra > 0 && (
        <span
          style={{ marginLeft: -8 }}
          className="flex size-6 items-center justify-center rounded-md border border-border/60 bg-background text-[10px] font-semibold text-muted-foreground ring-1 ring-background"
        >
          +{extra}
        </span>
      )}
    </span>
  );
}

// ─── AgentFooter ─────────────────────────────────────────────────

export function AgentFooter() {
  const { agents } = useAgents();
  const { user, isGuest, logout } = useAuth();
  const _navigate = useNavigate();
  const { pathname, search } = useLocation();
  const moliliLink = useMoliliLink();
  const { t } = useI18n();
  const credits = moliliLink.data?.credits?.surplusCredits;
  const [activeName, setActiveName] = useState<string | null>(() =>
    readActiveAgentName(),
  );

  const [authProviders, setAuthProviders] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    import("@/core/auth/api").then(({ getAuthProviders }) =>
      getAuthProviders().then((list) => {
        if (!cancelled) setAuthProviders(list);
      }),
    );
    return () => {
      cancelled = true;
    };
  }, []);
  const moliliEnabled = authProviders.includes("molili");

  const lock = ROUTE_LOCKS.find((r) => pathname.startsWith(r.prefix));
  const surfaceParam = new URLSearchParams(search).get("surface");
  const agentLibrarySurface = surfaceParam === "company" ? "company" : "chat";
  const agentLibraryHref = (tab?: string) => {
    const params = new URLSearchParams({
      hud: "1",
      surface: agentLibrarySurface,
    });
    if (tab) params.set("tab", tab);
    return `/workspace/agents?${params.toString()}`;
  };
  const footerAgents = useMemo(() => {
    return agents;
  }, [agents]);
  const effectiveName = lock?.agent ?? activeName ?? "general";

  const active: Agent | undefined =
    (effectiveName && footerAgents.find((a) => a.name === effectiveName)) ||
    footerAgents[0];

  const lockedAgent: Agent | undefined =
    lock && !agents.find((a) => a.name === lock.agent)
      ? {
          name: lock.agent,
          display_name:
            lock.agent === "admin" ? t.sidebar.adminAgentName : lock.agent,
          description: "",
          icon: lock.agent === "admin" ? "🛡️" : undefined,
          avatar_url: `/api/agents/${lock.agent}/avatar`,
          model: null,
          tool_groups: [],
        }
      : undefined;

  const selectAgent = (name: string) => {
    setActiveName(name);
    emitAgentChanged(name);
    _navigate(`/workspace/agents/${encodeURIComponent(name)}/chats/new`);
  };

  const displayAgent = lockedAgent ?? active;
  const accountName = user ? getAccountDisplayName(user) : "";

  return (
    <div className="flex items-center gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={Boolean(lock)}>
          <button
            type="button"
            disabled={Boolean(lock)}
            title={
              lock
                ? t.sidebar.lockedAgentTooltip(
                    displayAgent?.display_name || displayAgent?.name || "",
                  )
                : displayAgent?.description || t.sidebar.switchAgentLabel
            }
            className={cn(
              "group/agent flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left",
              "opacity-85 transition-[opacity,background-color] duration-150",
              "hover:opacity-100 hover:bg-muted/50 outline-none",
              "group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0",
            )}
          >
            <AgentAvatar agent={displayAgent} />
            <span className="min-w-0 flex-1 truncate text-xs font-medium leading-tight group-data-[collapsible=icon]:hidden">
              {displayAgent?.display_name || displayAgent?.name || "Octopus"}
            </span>
            {lock ? (
              <span
                className="shrink-0 text-2xs uppercase tracking-wider text-muted-foreground/60 group-data-[collapsible=icon]:hidden"
                aria-hidden
              >
                🔒
              </span>
            ) : (
              <span className="shrink-0 text-muted-foreground/60 group-hover/agent:text-muted-foreground group-data-[collapsible=icon]:hidden">
                <svg
                  viewBox="0 0 24 24"
                  className="size-3"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <polyline points="6 15 12 9 18 15" />
                </svg>
              </span>
            )}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="top"
          align="start"
          sideOffset={6}
          className="w-72 rounded-xl border-border/70 p-1.5 shadow-xl shadow-black/10"
        >
          <DropdownMenuLabel className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            {t.sidebar.switchAgentLabel}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {footerAgents.length === 0 ? (
            <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
              {t.sidebar.noAgents}
            </div>
          ) : (
            footerAgents.map((a) => {
              const isActive = a.name === active?.name;
              return (
                <DropdownMenuItem
                  key={a.name}
                  onSelect={() => selectAgent(a.name)}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs",
                    "opacity-85 transition-colors focus:bg-muted/60 focus:text-foreground focus:opacity-100",
                    isActive && "bg-muted/35 opacity-100",
                  )}
                >
                  <AgentAvatar
                    agent={a}
                    className="size-8 rounded-lg text-[11px]"
                  />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate font-medium leading-none">
                      {a.display_name || a.name}
                    </span>
                    <span className="truncate text-[10px] font-normal leading-tight text-muted-foreground">
                      {isActive ? t.sidebar.currentAgent : a.description || t.sidebar.soloChat}
                    </span>
                  </span>
                  {isActive && (
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                      <CheckIcon className="size-3" />
                    </span>
                  )}
                </DropdownMenuItem>
              );
            })
          )}
          <DropdownMenuSeparator />
          {displayAgent ? (
            <>
              <DropdownMenuItem
                onSelect={() => _navigate(agentLibraryHref())}
                className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-muted-foreground focus:bg-muted/60 focus:text-foreground"
              >
                <UsersRoundIcon className="size-4 shrink-0" />
                <span>{t.sidebar.switchAgent}</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          ) : null}
          {isGuest && moliliEnabled ? (
            <DropdownMenuItem
              onSelect={() => {
                _navigate("/login");
              }}
              className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs opacity-80 focus:bg-muted/60 focus:opacity-100"
            >
              <ShieldCheckIcon className="size-4 shrink-0 text-muted-foreground" />
              <span>{t.sidebar.loginMolili}</span>
            </DropdownMenuItem>
          ) : isGuest ? null : (
            <>
              <div className="flex items-center gap-2 px-2.5 py-2 text-xs text-muted-foreground">
                <UserCircleIcon className="size-4 shrink-0 opacity-70" />
                <span className="min-w-0 flex-1 truncate">{accountName}</span>
              </div>
              <DropdownMenuItem
                onSelect={() => emitOpenSettings("account")}
                className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs focus:bg-muted/60"
              >
                <CoinsIcon className="size-4 shrink-0 opacity-70" />
                <span className="min-w-0 flex-1 truncate">
                  {t.sidebar.remainingCredits}
                </span>
                <span className="shrink-0 text-[11px] font-mono text-foreground/80">
                  {typeof credits === "number" ? credits.toLocaleString() : "—"}
                </span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => void logout()}
                className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs focus:bg-muted/60"
              >
                <LogOutIcon className="size-4 shrink-0 opacity-70" />
                <span>{t.sidebar.logout}</span>
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <button
        type="button"
        title={t.sidebar.settingsTooltip}
        onClick={() => emitOpenSettings()}
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground",
          "opacity-70 transition-[opacity,background-color,color] duration-150",
          "hover:bg-muted hover:text-foreground hover:opacity-100",
          "group-data-[collapsible=icon]:hidden",
        )}
      >
        <SettingsIcon className="size-4" />
      </button>
    </div>
  );
}

// ─── TeamFooter ──────────────────────────────────────────────────

export function TeamFooter() {
  const { agents } = useAgents();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [activeName, setActiveName] = useState<string | null>(() =>
    readActiveAgentName(),
  );
  const [teams, setTeams] = useState<SidebarTeam[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(() =>
    readPreferredTeamId(),
  );

  const refreshTeams = useCallback(async () => {
    try {
      const remote = await migrateLegacyTeamsIfNeeded(await fetchTeams());
      setTeams(remote);
      const preferred = readPreferredTeamId();
      const nextId =
        preferred && remote.some((team) => team.id === preferred)
          ? preferred
          : null;
      const nextTeam = nextId
        ? (remote.find((team) => team.id === nextId) ?? null)
        : null;
      setCurrentId(nextId);
      writePreferredTeam(nextTeam);
    } catch (error) {
      console.warn("[team] failed to refresh team rooms", error);
    }
  }, []);

  useEffect(() => {
    void refreshTeams();
    const refresh = () => void refreshTeams();
    window.addEventListener("storage", refresh);
    window.addEventListener("octopus:team-updated", refresh);
    window.addEventListener("octopus:teams-changed", refresh);
    window.addEventListener("octopus:teams-refresh", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("octopus:team-updated", refresh);
      window.removeEventListener("octopus:teams-changed", refresh);
      window.removeEventListener("octopus:teams-refresh", refresh);
    };
  }, [refreshTeams]);

  const current = currentId
    ? (teams.find((t) => t.id === currentId) ?? null)
    : null;
  const activeAgent =
    agents.find((agent) => agent.name === activeName) ??
    agents.find((agent) => agent.name === current?.leaderId) ??
    agents[0];

  const agentByName = useMemo(() => {
    const map = new Map<string, Agent>();
    for (const a of agents) map.set(a.name, a);
    return map;
  }, [agents]);

  const selectTeam = (team: SidebarTeam) => {
    setCurrentId(team.id);
    writePreferredTeam(team);
    window.dispatchEvent(
      new CustomEvent("octopus:select-team", { detail: team }),
    );
    dispatchTeamUpdated(team);
    navigate("/workspace/team/new");
  };

  const selectSoloAgent = async (agent: Agent) => {
    const existing = teams.find(
      (team) =>
        team.members.length === 1 && team.members[0]?.name === agent.name,
    );
    const soloTeam =
      existing ??
      (await createTeam({
        name: agent.display_name || agent.name,
        members: [agent],
        leaderId: agent.name,
      }));
    setTeams((prev) => [
      soloTeam,
      ...prev.filter((team) => team.id !== soloTeam.id),
    ]);
    setCurrentId(soloTeam.id);
    writePreferredTeam(soloTeam);
    dispatchTeamUpdated(soloTeam);
    setActiveName(agent.name);
    emitAgentChanged(agent.name);
    navigate("/workspace/team/new");
  };

  const deleteTeam = async (team: SidebarTeam) => {
    try {
      await deleteTeamRoom(team.id);
      const next = teams.filter((t) => t.id !== team.id);
      const nextCurrent =
        currentId === team.id
          ? (next[0] ?? null)
          : (next.find((item) => item.id === currentId) ?? null);
      setTeams(next);
      setCurrentId(nextCurrent?.id ?? null);
      writePreferredTeam(nextCurrent);
      dispatchTeamUpdated(nextCurrent);
      eventBus.emit("teams:refresh");
    } catch (error) {
      console.warn("[team] failed to delete team room", error);
    }
  };

  const openCreate = () => eventBus.emit("team:create");

  return (
    <div className="flex items-center gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            title={current?.name || t.sidebar.selectTeam}
            className={cn(
              "group/team flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left",
              "opacity-85 transition-[opacity,background-color] duration-150",
              "hover:opacity-100 hover:bg-muted/50 outline-none",
              "group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0",
            )}
          >
            {current ? (
              <StackedMembers
                members={current.members}
                agentByName={agentByName}
              />
            ) : (
              <AgentAvatar agent={activeAgent} />
            )}
            <span className="min-w-0 flex-1 truncate text-xs font-medium leading-tight group-data-[collapsible=icon]:hidden">
              {current?.name ||
                activeAgent?.display_name ||
                activeAgent?.name ||
                t.sidebar.selectTeam}
            </span>
            <span className="shrink-0 text-muted-foreground/60 group-hover/team:text-muted-foreground group-data-[collapsible=icon]:hidden">
              <svg
                viewBox="0 0 24 24"
                className="size-3"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <polyline points="6 15 12 9 18 15" />
              </svg>
            </span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="top"
          align="start"
          sideOffset={6}
          className="max-h-[72vh] w-72 overflow-y-auto p-1"
        >
          <DropdownMenuLabel className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            {t.sidebar.soloTasks}
          </DropdownMenuLabel>
          {agents.length === 0 ? (
            <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
              {t.sidebar.noAgents}
            </div>
          ) : (
            agents.map((agent) => {
              const isActive = agent.name === activeAgent?.name && !current;
              return (
                <DropdownMenuItem
                  key={agent.name}
                  onSelect={() => void selectSoloAgent(agent)}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs",
                    isActive && "bg-muted/40",
                  )}
                >
                  <AgentAvatar agent={agent} className="size-7 rounded-lg" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium leading-tight">
                      {agent.display_name || agent.name}
                    </span>
                    <span className="line-clamp-1 text-[10px] leading-tight text-muted-foreground/70">
                      {agent.description || t.sidebar.oneOnOneTask}
                    </span>
                  </span>
                  {isActive ? (
                    <CheckIcon className="size-3.5 shrink-0 text-primary" />
                  ) : (
                    <MessageCircleIcon className="size-3.5 shrink-0 text-muted-foreground/55" />
                  )}
                </DropdownMenuItem>
              );
            })
          )}
          <DropdownMenuSeparator className="my-1" />
          <DropdownMenuLabel className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            {t.sidebar.groupTasks}
          </DropdownMenuLabel>
          {teams.length === 0 ? (
            <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
              {t.sidebar.noTeams}
            </div>
          ) : (
            teams.map((team) => {
              const isActive = team.id === current?.id;
              return (
                <div
                  key={team.id}
                  className={cn(
                    "group/row flex items-center gap-2 rounded-md px-2 py-1.5",
                    "hover:bg-muted/50 transition-colors",
                    isActive && "bg-muted/40",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => selectTeam(team)}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <StackedMembers
                      members={team.members}
                      agentByName={agentByName}
                      max={1}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium leading-tight">
                        {team.name}
                      </div>
                      <div className="text-[10px] text-muted-foreground/70 leading-tight">
                        {t.sidebar.teamMembers(team.members?.length ?? 0)}
                      </div>
                    </div>
                  </button>
                  {isActive && (
                    <span
                      aria-hidden
                      className="size-1.5 shrink-0 rounded-full bg-emerald-500"
                    />
                  )}
                  <button
                    type="button"
                    onClick={() => deleteTeam(team)}
                    title={t.sidebar.deleteTeam}
                    className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover/row:opacity-100"
                  >
                    <Trash2Icon className="size-3.5" />
                  </button>
                </div>
              );
            })
          )}
          <DropdownMenuSeparator className="my-1" />
          <DropdownMenuItem
            onSelect={openCreate}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-foreground/85 focus:bg-muted/50 focus:text-foreground"
          >
            <PlusIcon className="size-3.5" />
            {t.sidebar.newTeam}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <button
        type="button"
        title={t.sidebar.settingsTooltip}
        onClick={() => window.dispatchEvent(new Event("octopus:open-settings"))}
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground",
          "opacity-70 transition-[opacity,background-color,color] duration-150",
          "hover:bg-muted hover:text-foreground hover:opacity-100",
          "group-data-[collapsible=icon]:hidden",
        )}
      >
        <SettingsIcon className="size-4" />
      </button>
    </div>
  );
}
