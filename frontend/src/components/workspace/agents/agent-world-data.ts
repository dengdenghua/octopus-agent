// ---------------------------------------------------------------------------
// Agent World Data Layer — extracted from agent-world-unified.tsx (2026-06)
//
// Pure data + type definitions + helper functions. No React, no UI. Keeping
// this file separate means:
//   1. Data mutations don't invalidate component memoization.
//   2. The root component file stays under the god-file threshold.
//   3. Data can be unit-tested independently.
// ---------------------------------------------------------------------------

import type { LucideIcon } from "lucide-react";
import {
  BotIcon,
  Code2Icon,
  Layers3Icon,
  LandmarkIcon,
  PaletteIcon,
  SearchCheckIcon,
  TargetIcon,
  WorkflowIcon,
} from "lucide-react";

import type {
  Agent,
  AgentWorldAgent,
  AgentWorldCategory,
} from "@/core/agents/types";
import {
  WHITE_GHOST_AGENT_IDS,
  WHITE_GHOST_AGENT_ORDER,
} from "@/core/agents/persona-policy";

export type AgentCategoryFilter = "all" | AgentWorldCategory;

/** @deprecated Prefer the primary-persona names from core/agents. */
export const LOCAL_AGENT_ORDER = WHITE_GHOST_AGENT_ORDER;
/** @deprecated Prefer the primary-persona names from core/agents. */
export const LOCAL_AGENT_IDS = WHITE_GHOST_AGENT_IDS;
export const LOCAL_AGENT_RANK = new Map<string, number>(
  LOCAL_AGENT_ORDER.map((id, index) => [id, index]),
);
export const AGENT_CATEGORY_FILTERS: AgentCategoryFilter[] = [
  "all",
  "assistant",
  "coder",
  "researcher",
  "creative",
  "automation",
  "specialist",
  "financial",
];
export const CATEGORY_ICONS: Record<AgentCategoryFilter, LucideIcon> = {
  all: Layers3Icon,
  assistant: BotIcon,
  coder: Code2Icon,
  researcher: SearchCheckIcon,
  creative: PaletteIcon,
  automation: WorkflowIcon,
  specialist: TargetIcon,
  financial: LandmarkIcon,
};

export function localAgentToWorldAgent(agent: Agent): AgentWorldAgent {
  const displayName = agent.display_name ?? agent.name;
  const toolGroups = agent.tool_groups ?? [];
  return {
    id: agent.name,
    name: agent.name,
    display_name: displayName,
    description: agent.description || `${displayName} Agent`,
    author: "Octopus",
    category: toolGroups.length > 0 ? "automation" : "assistant",
    tags: toolGroups,
    icon: agent.icon || "🤖",
    avatar_url: agent.avatar_url ?? undefined,
    visual_urls: agent.visual_urls ?? undefined,
    model: agent.model ?? null,
    soul: agent.soul ?? null,
    tool_groups: toolGroups,
    private_skills: [],
    key_skills: [],
    available_skills: [],
    extra_affinity: [],
    version: "1.0.0",
    downloads: 0,
    rating: 4.8,
    rating_count: Math.max(1, toolGroups.length),
    is_featured: false,
    is_official: true,
    is_installed: true,
    created_at: new Date().toISOString(),
  };
}

export function worldAgentToAgent(agent: AgentWorldAgent): Agent {
  return {
    name: agent.id,
    display_name: agent.display_name,
    description: agent.description,
    icon: agent.icon,
    avatar_url: agent.avatar_url ?? null,
    visual_urls: agent.visual_urls ?? null,
    model: agent.model ?? null,
    tool_groups: agent.tool_groups ?? agent.tags,
    soul: agent.soul ?? null,
  };
}
