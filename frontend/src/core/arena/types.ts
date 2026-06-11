/**
 * Arena Mode type definitions.
 */

export interface BattleRequest {
  prompt: string;
  model_a?: string | null;
  model_b?: string | null;
}

export interface BattleResponse {
  session_id: string;
  prompt: string;
  response_a: string;
  response_b: string;
  latency_a_ms: number | null;
  latency_b_ms: number | null;
  voted: boolean;
}

export type VoteChoice = "a" | "b" | "tie" | "both_bad";

export interface VoteRequest {
  session_id: string;
  vote: VoteChoice;
}

export interface VoteResponse {
  session_id: string;
  prompt: string;
  response_a: string;
  response_b: string;
  model_a: string;
  model_b: string;
  vote: string;
  latency_a_ms: number | null;
  latency_b_ms: number | null;
}

export interface LeaderboardEntry {
  rank: number;
  model_name: string;
  rating: number;
  wins: number;
  losses: number;
  ties: number;
  battles: number;
  win_rate: number;
}

export interface LeaderboardResponse {
  entries: LeaderboardEntry[];
}

export interface HistoryEntry {
  session_id: string;
  prompt: string;
  model_a: string | null;
  model_b: string | null;
  response_a: string;
  response_b: string;
  vote: string | null;
  created_at: string;
  voted_at: string | null;
  latency_a_ms: number | null;
  latency_b_ms: number | null;
}

export interface HistoryResponse {
  battles: HistoryEntry[];
}

export interface ArenaStats {
  total_battles: number;
  total_voted: number;
  total_models: number;
}
