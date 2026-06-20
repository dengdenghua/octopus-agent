import { BotIcon, ChevronsUpDownIcon, UsersIcon } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useMemo, useState, useEffect, useCallback } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useAgents } from "@/core/agents";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import type { Agent } from "@/core/agents/types";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  deleteTeam as deleteTeamRoom,
  dispatchTeamUpdated,
  fetchTeams,
  migrateLegacyTeamsIfNeeded,
  readPreferredTeamId,
  writePreferredTeam,
  type Team,
} from "@/core/teams";

import { TeamSelector } from "./team-selector";

function AgentAvatar({
  agent,
  size = 24,
}: {
  agent: Agent | null;
  size?: number;
}) {
  const [imgError, setImgError] = useState(false);

  // Generate initials from agent name
  const initials = useMemo(() => {
    const name = agent?.display_name ?? agent?.name ?? "?";
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }, [agent]);

  // If no avatar URL or image failed to load, show fallback
  if (!agent?.avatar_url || imgError) {
    return (
      <span
        className="flex items-center justify-center rounded-lg bg-gradient-to-br from-violet-500/25 to-purple-500/20 text-violet-700 dark:text-violet-300 text-xs font-semibold ring-1 ring-violet-500/10"
        style={{ width: size, height: size }}
        title={agent?.display_name ?? agent?.name}
      >
        {initials}
      </span>
    );
  }

  // Construct avatar URL. In dev, getBackendBaseURL() returns "" meaning
  // "use a relative path so the Vite proxy forwards to the gateway".
  // In prod, it returns the configured backend origin. Falling back to a
  // hardcoded port bypasses the proxy and hits the wrong service.
  let avatarUrl: string;
  if (agent.avatar_url.startsWith("http")) {
    avatarUrl = agent.avatar_url;
  } else {
    avatarUrl = `${getBackendBaseURL()}${agent.avatar_url}`;
  }
  avatarUrl = withAgentAvatarVersion(avatarUrl);

  return (
    <img
      src={avatarUrl}
      alt={agent?.display_name ?? agent?.name}
      className="rounded-lg object-cover ring-1 ring-violet-500/10 [image-rendering:pixelated]"
      style={{ width: size, height: size }}
      onError={() => setImgError(true)}
    />
  );
}

/* Implementation note. */
export function WorkspaceNavMenu() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [currentTeam, setCurrentTeam] = useState<Team | null>(null);
  const [_showCreateTeam, setShowCreateTeam] = useState(false);
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();
  const { pathname } = useLocation();
  const isTeamMode = pathname?.includes("/workspace/team") ?? false;

  // Extract agent_name from URL: /workspace/agents/[agent_name]/chats/...
  const currentAgentName = useMemo(() => {
    const match = /\/workspace\/agents\/([^/]+)/.exec(pathname ?? "");
    return match?.[1] ?? null;
  }, [pathname]);

  const { agents: userAgents } = useAgents();

  // Resolve the currently active agent.
  const activeAgent = useMemo(() => {
    if (currentAgentName) {
      return (
        userAgents.find((a) => a.name === currentAgentName) ??
        userAgents[0] ??
        null
      );
    }
    return userAgents[0] ?? null;
  }, [userAgents, currentAgentName]);

  const refreshTeams = useCallback(async () => {
    try {
      const remote = await migrateLegacyTeamsIfNeeded(await fetchTeams());
      setTeams(remote);
      const preferred = readPreferredTeamId();
      const next =
        (preferred ? remote.find((team) => team.id === preferred) : null) ??
        remote[0] ??
        null;
      setCurrentTeam(next);
      writePreferredTeam(next);
    } catch (error) {
      console.warn("[team] failed to load team rooms", error);
    }
  }, []);

  // Load persistent team rooms from the backend. localStorage is kept
  // only as a preferred-team pointer and a one-time legacy migration
  // source.
  useEffect(() => {
    void refreshTeams();
    const handleTeamsChanged = () => void refreshTeams();
    window.addEventListener("octopus:teams-changed", handleTeamsChanged);
    window.addEventListener("octopus:team-updated", handleTeamsChanged);
    window.addEventListener("octopus:teams-refresh", handleTeamsChanged);
    return () => {
      window.removeEventListener("octopus:teams-changed", handleTeamsChanged);
      window.removeEventListener("octopus:team-updated", handleTeamsChanged);
      window.removeEventListener("octopus:teams-refresh", handleTeamsChanged);
    };
  }, [refreshTeams]);

  // Handle team selection
  const handleTeamSelect = useCallback((team: Team) => {
    setCurrentTeam(team);
    writePreferredTeam(team);
    window.dispatchEvent(
      new CustomEvent("octopus:select-team", { detail: team }),
    );
    dispatchTeamUpdated(team);
  }, []);

  const handleDeleteTeam = useCallback(
    async (teamId: string) => {
      try {
        await deleteTeamRoom(teamId);
        const nextTeams = teams.filter((team) => team.id !== teamId);
        const nextCurrent =
          currentTeam?.id === teamId
            ? (nextTeams[0] ?? null)
            : currentTeam &&
                nextTeams.some((team) => team.id === currentTeam.id)
              ? currentTeam
              : null;
        setTeams(nextTeams);
        setCurrentTeam(nextCurrent);
        writePreferredTeam(nextCurrent);
        dispatchTeamUpdated(nextCurrent);
        window.dispatchEvent(new Event("octopus:teams-refresh"));
      } catch (error) {
        console.warn("[team] failed to delete team room", error);
      }
    },
    [currentTeam, teams],
  );

  // Handle create team
  const handleCreateTeam = useCallback(() => {
    setShowCreateTeam(true);
    window.dispatchEvent(new CustomEvent("octopus:create-team"));
  }, []);

  // Dispatch event to open settings
  const _handleOpenSettings = useCallback(() => {
    window.dispatchEvent(new Event("octopus:open-settings"));
  }, []);

  return (
    <SidebarMenu className="w-full">
      {isTeamMode ? (
        <>
          {/* Team mode: Team Selector + Settings (side by side) */}
          <SidebarMenuItem className="group-data-[collapsible=icon]:px-0 px-1.5">
            {isSidebarOpen ? (
              <div className="flex items-center gap-1 py-0">
                <TeamSelector
                  teams={teams}
                  currentTeam={currentTeam}
                  onSelectTeam={handleTeamSelect}
                  onCreateTeam={handleCreateTeam}
                  onDeleteTeam={(teamId) => void handleDeleteTeam(teamId)}
                />
              </div>
            ) : (
              <Link to="/workspace/team">
                <SidebarMenuButton
                  tooltip="Team"
                  className="group-data-[collapsible=icon]:px-0"
                >
                  <UsersIcon className="size-4" />
                </SidebarMenuButton>
              </Link>
            )}
          </SidebarMenuItem>
        </>
      ) : (
        <>
          {/* Normal mode: Agent Selector */}
          <SidebarMenuItem className="group-data-[collapsible=icon]:px-0 px-1.5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  className="w-full justify-between group-data-[collapsible=icon]:px-0"
                  tooltip={activeAgent?.display_name ?? t.sidebar.selectAgent}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <AgentAvatar agent={activeAgent} size={20} />
                    <span className="truncate">
                      {activeAgent?.display_name ?? t.sidebar.selectAgent}
                    </span>
                  </div>
                  <ChevronsUpDownIcon className="ml-2 size-3.5 shrink-0 text-muted-foreground" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56" side="right">
                <DropdownMenuLabel>{t.sidebar.selectAgent}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {userAgents.map((agent) => (
                  <DropdownMenuItem
                    key={agent.name}
                    asChild
                    className="cursor-pointer"
                  >
                    <Link
                      to={`/workspace/agents/${agent.name}/chats/new`}
                      className="flex items-center gap-2"
                    >
                      <AgentAvatar agent={agent} size={18} />
                      <span className="truncate">{agent.display_name}</span>
                      {agent.name === activeAgent?.name && (
                        <BotIcon className="ml-auto size-3 text-primary" />
                      )}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </>
      )}
    </SidebarMenu>
  );
}
