export interface ContextSection {
  summary: string;
  updatedAt: string;
}

export interface UserContext {
  workContext: ContextSection;
  personalContext: ContextSection;
  topOfMind: ContextSection;
}

export interface HistoryContext {
  recentMonths: ContextSection;
  earlierContext: ContextSection;
  longTermBackground: ContextSection;
}

export interface MemoryFact {
  id: string;
  content: string;
  category: string;
  confidence: number;
  createdAt: string;
  source: string;
  scope?: "global" | "agent" | "project" | string;
  agent_id?: string;
  project?: string;
  sourceError?: string | null;
}

export interface MemoryData {
  version: string;
  lastUpdated: string;
  user: UserContext;
  history: HistoryContext;
  facts: MemoryFact[];
}

export interface MemoryConfig {
  enabled: boolean;
  storage_path: string;
  auto_capture_enabled: boolean;
  debounce_seconds: number;
  max_facts: number;
  fact_confidence_threshold: number;
  injection_enabled: boolean;
  max_injection_tokens: number;
}

export type MemoryConfigPatch = Partial<
  Pick<
    MemoryConfig,
    | "enabled"
    | "auto_capture_enabled"
    | "injection_enabled"
    | "debounce_seconds"
    | "max_facts"
    | "fact_confidence_threshold"
    | "max_injection_tokens"
  >
>;

export interface MemorySearchResult {
  id: string;
  content: string;
  category: string;
  confidence: number;
  createdAt: string;
  source: string;
  scope?: "global" | "agent" | "project" | string;
  agent_id?: string;
  project?: string;
  relevance: number;
}

export interface FactCreateRequest {
  content: string;
  category?: string;
  confidence?: number;
  scope?: "global" | "agent" | "project" | string;
  agent_id?: string;
  project?: string;
}

export type MemoryFactInput = FactCreateRequest;

export interface FactPatchRequest {
  content?: string;
  category?: string;
  confidence?: number;
  scope?: "global" | "agent" | "project" | string;
  agent_id?: string;
  project?: string;
}

export type MemoryFactPatchInput = FactPatchRequest;

export type UserMemory = MemoryData;
