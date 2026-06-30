import { Loader2Icon, UsersIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  dispatchTeamUpdated,
  inspectTeamInvite,
  joinTeamInvite,
  readOrCreateTeamParticipantId,
  writePreferredTeam,
  type Team,
} from "@/core/teams";

function teamRealtimeTarget(threadId?: string | null): string {
  const cleanId = threadId?.trim();
  if (!cleanId || cleanId === "new") return "/workspace/realtime/new";
  return `/workspace/realtime/${encodeURIComponent(cleanId)}`;
}

export default function TeamJoinPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = useMemo(() => params.get("token")?.trim() ?? "", [params]);
  const requestedThreadId = useMemo(() => {
    const value = params.get("thread")?.trim() ?? "";
    return /^[A-Za-z0-9_-]+$/.test(value) ? value : "";
  }, [params]);
  const [team, setTeam] = useState<Team | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setLoading(false);
      setError(t.teamJoin.missingToken);
      return;
    }
    setLoading(true);
    void inspectTeamInvite(token)
      .then((nextTeam) => {
        if (cancelled) return;
        setTeam(nextTeam);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError(t.teamJoin.invalidInvite);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t.teamJoin.invalidInvite, t.teamJoin.missingToken, token]);

  const handleJoin = async () => {
    if (!token || !team) return;
    setJoining(true);
    try {
      const result = await joinTeamInvite(token, {
        display_name: name.trim() || t.teamJoin.guestName,
        participant_id: readOrCreateTeamParticipantId(),
      });
      writePreferredTeam(result.team);
      dispatchTeamUpdated(result.team);
      window.dispatchEvent(new Event("octopus:teams-refresh"));
      toast.success(t.teamJoin.joinSuccess(result.team.name));
      navigate(teamRealtimeTarget(requestedThreadId || "new"), { replace: true });
    } catch {
      toast.error(t.teamJoin.joinFailed);
    } finally {
      setJoining(false);
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="flex items-center justify-center px-6 py-10">
        <div className="workspace-panel w-full max-w-md rounded-[1.5rem] p-6 shadow-sm">
          <div className="mb-5 flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <UsersIcon className="size-5" />
            </span>
            <div>
              <h1 className="text-base font-semibold">{t.teamJoin.title}</h1>
              <p className="text-sm text-muted-foreground">
                {t.teamJoin.description}
              </p>
            </div>
          </div>

          {loading ? (
            <LoadingState
              title={t.teamJoin.loadingInvite}
              className="min-h-[180px] border-0 bg-transparent p-4"
            />
          ) : error ? (
            <ErrorState
              title={t.teamJoin.invalidInvite}
              detail={error}
              className="min-h-[180px] border-0 bg-transparent p-4"
            />
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-muted/20 px-3 py-2">
                <div className="text-sm font-medium">{team?.name}</div>
                <div className="text-xs text-muted-foreground">
                  {t.teamJoin.membersAndParticipants(
                    team?.members.length ?? 0,
                    team?.participants?.length ?? 0,
                  )}
                </div>
              </div>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t.teamJoin.displayNamePlaceholder}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleJoin();
                  }
                }}
              />
              <Button
                className="w-full"
                onClick={() => void handleJoin()}
                disabled={joining}
              >
                {joining ? (
                  <>
                    <Loader2Icon className="mr-2 size-4 animate-spin" />
                    {t.teamJoin.joining}
                  </>
                ) : (
                  t.teamJoin.joinButton
                )}
              </Button>
            </div>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
