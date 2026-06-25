import { describe, expect, test } from "vitest";

import type { AgentWorldAgent } from "@/core/agents/types";

import {
  agentWorldIdentityKey,
  dedupeAgentWorldAgents,
} from "./agent-world-unified";

function agent(overrides: Partial<AgentWorldAgent>): AgentWorldAgent {
  return {
    id: "agent",
    name: "agent",
    display_name: "Agent",
    description: "",
    author: "octopus",
    category: "assistant",
    tags: [],
    icon: "🤖",
    version: "1.0.0",
    downloads: 0,
    rating: 0,
    rating_count: 0,
    is_featured: false,
    is_official: true,
    is_installed: true,
    created_at: "0",
    ...overrides,
  };
}

describe("Agent Hub dedupe", () => {
  test("uses character profile name as the display identity", () => {
    expect(
      agentWorldIdentityKey(
        agent({
          id: "echo_noah",
          name: "echo_noah",
          display_name: "Noah / Probability",
          character_profile: { name: "Noah" },
        }),
      ),
    ).toBe("noah");
  });

  test("collapses internal role agents and echo character duplicates", () => {
    const deduped = dedupeAgentWorldAgents([
      agent({
        id: "market_researcher",
        name: "market_researcher",
        display_name: "Noah",
        category: "researcher",
        is_official: true,
      }),
      agent({
        id: "echo_noah",
        name: "echo_noah",
        display_name: "Noah / Probability",
        author: "echo-universe-engine",
        category: "creative",
        is_official: false,
        character_profile: { name: "Noah" },
      }),
    ]);

    expect(deduped.map((item) => item.id)).toEqual(["market_researcher"]);
  });

  test("does not merge unrelated slash names outside known Echo characters", () => {
    const deduped = dedupeAgentWorldAgents([
      agent({ id: "sales", name: "sales", display_name: "Buyer" }),
      agent({
        id: "buyer_seller",
        name: "buyer_seller",
        display_name: "Buyer / Seller",
      }),
    ]);

    expect(deduped.map((item) => item.id)).toEqual(["sales", "buyer_seller"]);
  });
});
