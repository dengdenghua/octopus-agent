
import { PlusIcon, ChevronDownIcon, UsersIcon, Trash2Icon } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { getBackendBaseURL } from "@/core/config";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import type { Team } from "@/core/teams";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export type { Team };

interface TeamSelectorProps {
  teams: Team[];
  currentTeam: Team | null;
  onSelectTeam: (team: Team) => void;
  onCreateTeam: () => void;
  onDeleteTeam?: (teamId: string) => void;
}

export function TeamSelector({
  teams,
  currentTeam,
  onSelectTeam,
  onCreateTeam,
  onDeleteTeam,
}: TeamSelectorProps) {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const getStackedAvatars = (team: Team, max = 3) => (
    <div className="flex -space-x-1.5">
      {team.members.slice(0, max).map((member, idx) => (
        <div
          key={member.name}
          className="relative flex h-5 w-5 items-center justify-center overflow-hidden rounded-lg border-2 border-background bg-gradient-to-br from-primary/20 to-primary/5"
          style={{ zIndex: max - idx }}
        >
          {member.avatar_url ? (
            <img
              src={`${getBackendBaseURL()}${withAgentAvatarVersion(member.avatar_url)}`}
              alt={member.display_name ?? member.name}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="text-[8px] font-semibold text-primary">
              {(member.display_name ?? member.name).charAt(0)}
            </span>
          )}
        </div>
      ))}
      {team.members.length > max && (
        <div className="relative flex h-5 w-5 items-center justify-center rounded-lg border-2 border-background bg-muted text-[8px] font-medium text-muted-foreground">
          +{team.members.length - max}
        </div>
      )}
    </div>
  );

  const getTeamAvatar = (team: Team) => {
    const firstMember = team.members[0];
    if (!firstMember) return null;
    if (firstMember.avatar_url) {
      return (
        <img
          src={`${getBackendBaseURL()}${withAgentAvatarVersion(firstMember.avatar_url)}`}
          alt={team.name}
          className="h-full w-full object-cover"
        />
      );
    }
    return (
      <span className="bg-gradient-to-br from-primary/20 to-primary/5 flex h-full w-full items-center justify-center text-xs font-semibold text-primary">
        {firstMember.display_name?.charAt(0) ?? firstMember.name.charAt(0)}
      </span>
    );
  };

  return (
    <div className="relative flex-1 min-w-0" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-all text-left",
          isOpen
            ? "bg-accent border-accent shadow-sm"
            : "border-border hover:bg-accent/50 hover:border-accent/50"
        )}
      >
        {currentTeam && currentTeam.name ? (
          <>
            {getStackedAvatars(currentTeam)}
            <span className="text-xs font-medium truncate flex-1">
              {currentTeam.name}
            </span>
          </>
        ) : (
          <>
            <div className="flex h-5 w-5 items-center justify-center rounded-lg bg-muted">
              <UsersIcon className="size-3 text-muted-foreground" />
            </div>
            <span className="text-xs text-muted-foreground truncate flex-1">{t.teamSelector.selectTeam}</span>
          </>
        )}
        <ChevronDownIcon
          className={cn(
            "size-3 text-muted-foreground transition-transform shrink-0",
            isOpen && "rotate-180"
          )}
        />
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 right-0 mb-1 rounded-lg border bg-popover shadow-xl z-50 animate-in fade-in-0 slide-in-from-bottom-1 duration-150">
          <div className="max-h-[240px] overflow-y-auto py-1">
            {teams.length === 0 ? (
              <div className="text-muted-foreground py-6 text-center text-xs">
                {t.teamSelector.noTeams}
              </div>
            ) : (
              teams.map((team) => (
                <div
                  key={team.id}
                  className={cn(
                    "group flex items-center gap-2 px-2 py-1.5 transition-colors hover:bg-accent",
                    currentTeam?.id === team.id && "bg-accent/60"
                  )}
                >
                  <button
                    onClick={() => {
                      onSelectTeam(team);
                      setIsOpen(false);
                    }}
                    className="flex flex-1 items-center gap-2 text-left min-w-0"
                  >
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-lg">
                      {getTeamAvatar(team)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium truncate">{team.name}</p>
                      <p className="text-muted-foreground text-[10px]">
                        {t.teamSelector.memberCount(team.members.length)}
                      </p>
                    </div>
                    {currentTeam?.id === team.id && (
                      <div className="size-1.5 rounded-lg bg-green-500 shrink-0" />
                    )}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(t.teamSelector.confirmDisband(team.name))) {
                        onDeleteTeam?.(team.id);
                      }
                    }}
                    className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 p-1 rounded hover:bg-destructive/10 hover:text-destructive transition-all shrink-0"
                    title={t.teamSelector.disbandTeam}
                  >
                    <Trash2Icon className="size-3" />
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="border-t" />

          <button
            onClick={() => {
              onCreateTeam();
              setIsOpen(false);
            }}
            className="flex w-full items-center gap-2 px-2 py-2 text-xs hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <PlusIcon className="size-3.5" />
            <span>{t.teamSelector.createTeam}</span>
          </button>
        </div>
      )}
    </div>
  );
}
