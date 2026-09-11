import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync, readdirSync } from "node:fs";
import { mergeProfessions } from "@/core/agents/profession-catalog";
import type { Agent } from "@/core/agents/types";
import { PixelAgentAvatar } from "./pixel-agent-avatar";

describe("occupation portraits", () => {
  it("gives every current occupation distinct visible artwork and keeps it stable", () => {
    const agents = readdirSync("../agents").filter(id => id.startsWith("twin_")).map(id => {
      const profile = JSON.parse(readFileSync(`../agents/${id}/profile.jsonc`, "utf8"));
      return { name: id, display_name: profile.name, description: profile.description } as Agent;
    });
    const roles = mergeProfessions(agents);
    const render = (role: typeof roles[number]) => renderToStaticMarkup(<PixelAgentAvatar id={role.id} name={role.name} />);
    const portraits = roles.map(render);
    expect(roles.length).toBeGreaterThan(100);
    expect(new Set(portraits).size).toBe(roles.length);
    expect(roles.map(render)).toEqual(portraits);
  });
});
