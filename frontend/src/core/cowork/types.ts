export type CoworkMemberKind = "agent" | "human";
export type CoworkMemberRole = "participant" | "observer";
export type CoworkMode = "chat" | "cluster" | "swarm";
export type CoworkGrantScope = "all" | "from_join" | "range" | "summary";

export interface CoworkContextGrant {
  scope: CoworkGrantScope;
  from_msg?: number | null;
  to_msg?: number | null;
}

export interface CoworkMember {
  id: string;
  kind: CoworkMemberKind;
  role: CoworkMemberRole;
  joined_at_message?: number | null;
  grant: CoworkContextGrant;
  muted?: boolean;
  invited_by?: string;
}

export interface CoworkState {
  roster: CoworkMember[];
  mode: CoworkMode;
  event_count: number;
  is_one_to_one: boolean;
}

export interface CoworkEvent {
  action: "invite" | "leave" | "mute" | "unmute" | "mode";
  actor: string;
  target_id: string;
  target_kind: CoworkMemberKind;
  role: CoworkMemberRole;
  grant: CoworkContextGrant;
  mode?: CoworkMode | null;
  at_message?: number | null;
  ts: string;
  seq: number;
}

export interface CoworkGroupResponse {
  thread_id: string;
  state: CoworkState;
  blackboard: Record<string, unknown>;
  events: CoworkEvent[];
  responders: string[];
}

export interface CoworkInviteInput {
  target_id: string;
  kind?: CoworkMemberKind;
  role?: CoworkMemberRole;
  grant?: Partial<CoworkContextGrant>;
  at_message?: number | null;
}

export interface CoworkModeInput {
  mode: CoworkMode;
}
