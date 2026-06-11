import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { eventBus } from "@/core/events";
import type { Agent } from "@/core/agents/types";

export interface TeamParticipant {
  id: string;
  display_name: string;
  role: TeamParticipantRole;
  actor_id?: string | null;
  joined_at: string;
  last_seen_at?: string | null;
  status: string;
}

export interface Team {
  id: string;
  name: string;
  members: Agent[];
  leaderId: string | null;
  owner_id?: string | null;
  created_at?: string;
  updated_at?: string;
  participants?: TeamParticipant[];
  invite_token?: string | null;
  invite_role?: TeamParticipantRole;
}

export type TeamParticipantRole = "owner" | "member" | "viewer";

export interface TeamInvite {
  team_id: string;
  invite_token: string;
  invite_role?: TeamParticipantRole;
  invite_path: string;
  invite_hash_path: string;
}

export interface CreateTeamInviteInput {
  role?: TeamParticipantRole;
}

export interface JoinTeamInviteInput {
  display_name?: string;
  participant_id?: string;
}

export interface JoinTeamInviteResult {
  team: Team;
  participant: TeamParticipant;
}

export interface UpdateTeamParticipantInput {
  display_name?: string;
  role?: TeamParticipantRole;
  status?: "active" | "offline" | "removed";
}

export interface UpdateTeamParticipantResult {
  team: Team;
  participant: TeamParticipant;
}

export interface RemoveTeamParticipantResult {
  ok: boolean;
  team: Team;
  participant_id: string;
}

export interface CreateTeamInput {
  id?: string;
  name: string;
  members: Agent[];
  leaderId: string | null;
}

const BASE = () => `${getBackendBaseURL()}/api`;
const PARTICIPANT_KEY = "octopus:teamParticipantId";

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchTeams(): Promise<Team[]> {
  const res = await fetch(`${BASE()}/teams`);
  const data = await parseJson<{ teams?: Team[] } | Team[]>(res);
  return Array.isArray(data) ? data : (data.teams ?? []);
}

export async function createTeam(input: CreateTeamInput): Promise<Team> {
  const res = await fetch(`${BASE()}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return parseJson<Team>(res);
}

export async function updateTeam(
  teamId: string,
  input: CreateTeamInput,
): Promise<Team> {
  const res = await fetch(`${BASE()}/teams/${encodeURIComponent(teamId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return parseJson<Team>(res);
}

export async function deleteTeam(teamId: string): Promise<void> {
  const res = await fetch(`${BASE()}/teams/${encodeURIComponent(teamId)}`, {
    method: "DELETE",
  });
  await parseJson(res);
}

export async function createTeamInvite(
  teamId: string,
  input: CreateTeamInviteInput = {},
): Promise<TeamInvite> {
  const res = await fetch(
    `${BASE()}/teams/${encodeURIComponent(teamId)}/invite`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return parseJson<TeamInvite>(res);
}

export async function inspectTeamInvite(token: string): Promise<Team> {
  const res = await fetch(
    `${BASE()}/team-invites/${encodeURIComponent(token)}`,
  );
  const data = await parseJson<{ team: Team }>(res);
  return data.team;
}

export async function joinTeamInvite(
  token: string,
  input: JoinTeamInviteInput,
): Promise<JoinTeamInviteResult> {
  const res = await fetch(
    `${BASE()}/team-invites/${encodeURIComponent(token)}/join`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return parseJson<JoinTeamInviteResult>(res);
}

export async function updateTeamParticipant(
  teamId: string,
  participantId: string,
  input: UpdateTeamParticipantInput,
): Promise<UpdateTeamParticipantResult> {
  const res = await fetch(
    `${BASE()}/teams/${encodeURIComponent(teamId)}/participants/${encodeURIComponent(participantId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return parseJson<UpdateTeamParticipantResult>(res);
}

export async function removeTeamParticipant(
  teamId: string,
  participantId: string,
): Promise<RemoveTeamParticipantResult> {
  const res = await fetch(
    `${BASE()}/teams/${encodeURIComponent(teamId)}/participants/${encodeURIComponent(participantId)}`,
    {
      method: "DELETE",
    },
  );
  return parseJson<RemoveTeamParticipantResult>(res);
}

export async function migrateLegacyTeamsIfNeeded(
  existing: Team[],
): Promise<Team[]> {
  if (existing.length > 0 || typeof window === "undefined") return existing;
  const raw = window.localStorage.getItem("octopus:teams");
  if (!raw) return existing;
  let legacy: Team[];
  try {
    const parsed = JSON.parse(raw);
    legacy = Array.isArray(parsed) ? (parsed as Team[]) : [];
  } catch (e) {
    swallow(e);
    return existing;
  }
  const migrated: Team[] = [];
  for (const team of legacy) {
    if (
      !team?.name ||
      !Array.isArray(team.members) ||
      team.members.length === 0
    ) {
      continue;
    }
    try {
      migrated.push(
        await createTeam({
          id: team.id,
          name: team.name,
          members: team.members,
          leaderId: team.leaderId ?? team.members[0]?.name ?? null,
        }),
      );
    } catch (e) {
      swallow(e);
    }
  }
  return migrated.length > 0 ? migrated : existing;
}

export function readPreferredTeamId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const direct = window.localStorage.getItem("octopus:currentTeamId");
    if (direct) return direct;
    const raw = window.localStorage.getItem("octopus:currentTeam");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { id?: string };
    return parsed.id ?? null;
  } catch (e) {
    swallow(e);
    return null;
  }
}

export function writePreferredTeam(team: Team | null): void {
  if (typeof window === "undefined") return;
  try {
    if (!team) {
      window.localStorage.removeItem("octopus:currentTeamId");
      window.localStorage.removeItem("octopus:currentTeam");
      return;
    }
    window.localStorage.setItem("octopus:currentTeamId", team.id);
    window.localStorage.setItem("octopus:currentTeam", JSON.stringify(team));
  } catch (e) {
    swallow(e, "storage");
  }
}

export function dispatchTeamUpdated(team?: Team | null): void {
  if (typeof window === "undefined") return;
  eventBus.emit(
    "team:updated",
    team ? { id: team.id, name: team.name } : { id: "", name: "" },
  );
  eventBus.emit("teams:changed");
}

export function readOrCreateTeamParticipantId(): string {
  if (typeof window === "undefined") return `guest-${Date.now()}`;
  try {
    const existing = window.localStorage.getItem(PARTICIPANT_KEY);
    if (existing) return existing;
    const id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `guest-${Date.now()}`;
    window.localStorage.setItem(PARTICIPANT_KEY, id);
    return id;
  } catch (e) {
    swallow(e);
    return `guest-${Date.now()}`;
  }
}

export function readTeamParticipantIdForTeam(team?: Team | null): string {
  if (typeof window === "undefined") return `guest-${Date.now()}`;
  try {
    const existing = window.localStorage.getItem(PARTICIPANT_KEY);
    if (
      existing &&
      team?.participants?.some(
        (p) => p.id === existing && p.status !== "removed",
      )
    ) {
      return existing;
    }

    const localOwner = team?.participants?.find(
      (p) =>
        p.status !== "removed" &&
        p.role === "owner" &&
        (p.actor_id === "local" || p.id === "owner-local"),
    );
    if (localOwner) {
      return localOwner.id;
    }
  } catch (e) {
    swallow(e);
  }
  return readOrCreateTeamParticipantId();
}
