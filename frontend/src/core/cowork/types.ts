export type CoworkMemberKind = "agent" | "human";
export type CoworkMemberRole = "participant" | "observer";
export type CoworkMode = "chat" | "cluster" | "swarm" | "project";
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
  room_id?: string | null;
}

export interface CoworkEvent {
  action: "invite" | "leave" | "mute" | "unmute" | "mode" | "room_link";
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

export interface CollabRoomMessageInput {
  text: string;
  participant_id?: string;
  display_name?: string;
}

export interface CollabRoomMessageResponse {
  ok: boolean;
  room_id: string;
  seq: number;
}

export type CoworkSearchKind =
  | "blackboard"
  | "task"
  | "event"
  | "room_message"
  | "room_task";

export interface CoworkSearchHit {
  kind: CoworkSearchKind;
  title: string;
  snippet: string;
  score: number;
  actor: string;
  ts: string | null;
  ref: Record<string, unknown>;
}

export interface CoworkSearchResponse {
  thread_id: string;
  query: string;
  hits: CoworkSearchHit[];
}

export interface CoworkMemberPresence {
  member_id: string;
  last_read: number;
  last_seen_at: string | null;
  online: boolean;
  unread: number;
}

export interface CoworkPresenceResponse {
  thread_id: string;
  members: CoworkMemberPresence[];
}

/** Unified collaboration session — one view over the cowork thread (canonical)
 * plus a linked Team Room's transcript + participants. Mirrors the backend
 * CollaborationSession (GET /api/collab/{thread_id}). */
export interface CollaborationSession {
  session_id: string;
  room_id: string | null;
  mode: CoworkMode;
  roster: CoworkMember[];
  blackboard: Record<string, unknown>;
  tasks: Record<string, unknown>[];
  presence: CoworkMemberPresence[];
  room_messages: Record<string, unknown>[];
  room_participants: Record<string, unknown>[];
  room_tasks: Record<string, unknown>[];
}
