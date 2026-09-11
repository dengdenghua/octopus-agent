import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import type { Agent } from "./types";
import { mergeProfessions } from "./profession-catalog";
describe("shared profession catalog", () => {
  it("merges overlapping local roles but retains specialized engineering", () => {
    const agents = readdirSync("../agents").filter(id => id.startsWith("twin_")).map(id => {
      const profile = JSON.parse(readFileSync(`../agents/${id}/profile.jsonc`, "utf8"));
      return { name: id, display_name: profile.name, description: profile.description } as Agent;
    });
    const merged = mergeProfessions([...agents, ...agents]);
    expect(new Set(merged.map(r => r.id)).size).toBe(merged.length);
    expect(merged.filter(r => r.name === "产品经理")).toHaveLength(1);
    expect(merged.some(r => r.name === "结构工程师")).toBe(true);
    expect(merged.some(r => r.name === "光学工程师")).toBe(true);
    expect(merged.some(r => r.name === "嵌入式工程师")).toBe(true);
    for (const agent of agents) expect(merged.some(r => r.candidates.some(c => c.role_id === agent.name))).toBe(true);
    expect(mergeProfessions(agents)).toEqual(merged);
  });
});
