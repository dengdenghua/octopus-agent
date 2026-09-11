import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import type { CloudExpertAgent } from "@/core/agents/agent-world-api";
import { CURATED_ROLE_NAMES, CURATED_TEAM_IDS, FINANCE_TEAM_IDS, DIGITAL_EMPLOYEE_GROUPS, DIGITAL_EMPLOYEE_IDS, selectDigitalEmployees } from "./digital-employee-catalog";

const source = JSON.parse(readFileSync("../extensions/workbuddy-experts/storefront/data/expert-store.json", "utf8"));
const experts = source.experts.map((e: { plugin: string; expertType: string }) => ({ id: `wb_${e.plugin}`, is_team: e.expertType === "team" }) as CloudExpertAgent);
describe("digital employee catalog", () => {
  it("groups restored finance roles and retained finance teams without duplicate memberships", () => {
    const finance = DIGITAL_EMPLOYEE_GROUPS.find((group) => group.id === "finance")!;
    expect(finance.ids).toHaveLength(10);
    const ids = DIGITAL_EMPLOYEE_GROUPS.flatMap((group) => group.ids);
    expect(new Set(ids).size).toBe(ids.length);
    const selected = selectDigitalEmployees(experts);
    const financial = selected.filter((expert) => expert.category_id === "finance");
    expect(financial.filter((expert) => !expert.is_team)).toHaveLength(10);
    expect(financial.filter((expert) => expert.is_team)).toHaveLength(10);
    expect(financial.map((expert) => expert.id)).toEqual(expect.arrayContaining([...finance.ids, ...FINANCE_TEAM_IDS]));
  });
  it("uses distinct job names without changing identity or provenance", () => {
    expect(Object.keys(CURATED_ROLE_NAMES)).toHaveLength(78);
    expect(new Set(Object.values(CURATED_ROLE_NAMES)).size).toBe(78);
    for (const id of [...DIGITAL_EMPLOYEE_IDS, ...CURATED_TEAM_IDS]) expect(CURATED_ROLE_NAMES[id]).toBeTruthy();
    const original = { id: "wb_senior-developer", display_name: "吴八哥", name: "senior_developer", author: "Original author", source: "workbuddy", is_installed: true } as CloudExpertAgent;
    const [renamed] = selectDigitalEmployees([original]);
    expect(renamed.display_name).toBe("高级开发工程师");
    expect(renamed).toMatchObject({ id: original.id, name: original.name, author: original.author, source: original.source, is_installed: true });
    expect(original.display_name).toBe("吴八哥");
    expect(CURATED_ROLE_NAMES["wb_believe-in-light"]).toBe("光通信产业研究团队");
  });
  it("retains 58 reviewed jobs and 20 teams including finance", () => {
    expect(DIGITAL_EMPLOYEE_IDS.size).toBe(58);
    expect(DIGITAL_EMPLOYEE_GROUPS.map((g) => g.ids.length)).toEqual([28, 10, 12, 8]);
    for (const id of ["embedded-firmware-engineer", "ai-engineer", "experiment-tracking-manager", "thesis-writing-mentor", "study-planner"])
      expect(DIGITAL_EMPLOYEE_IDS.has(`wb_${id}`)).toBe(true);
    for (const id of ["fortune-consultant", "worldcup-buddy", "dockerfile-gen", "kdocs-pdf-toolbox", "mai-deal-advisor", "mentougou-business-guide", "corp-credit-due-diligence", "sa-legal-compliance", "career-broker", "douyin-strategist", "wechat-official-account-expert", "api-dev", "godot-shader-developer"])
      expect(DIGITAL_EMPLOYEE_IDS.has(`wb_${id}`)).toBe(false);
    for (const id of DIGITAL_EMPLOYEE_IDS) expect(experts.some((e: CloudExpertAgent) => e.id === id && !e.is_team)).toBe(true);
    const selected = selectDigitalEmployees(experts);
    expect(selected.filter((e) => !e.is_team)).toHaveLength(DIGITAL_EMPLOYEE_IDS.size);
    expect(CURATED_TEAM_IDS.size).toBe(20);
    const teams = selected.filter((e) => e.is_team);
    expect(teams).toHaveLength(20);
    for (const id of CURATED_TEAM_IDS) expect(teams.some((e) => e.id === id)).toBe(true);
    expect(FINANCE_TEAM_IDS).toHaveLength(10);
    for (const id of FINANCE_TEAM_IDS) expect(teams.some((e) => e.id === id)).toBe(true);
  });
  it("keeps previously added non-curated roles manageable only in the added view", () => {
    const legacy = { id: "wb_legacy-tool", is_installed: true } as CloudExpertAgent;
    expect(selectDigitalEmployees([legacy])).toEqual([]);
    expect(selectDigitalEmployees([legacy], true)).toEqual([legacy]);
    const legacyTeam = { id: "wb_cloud-ops-team", is_team: true, is_installed: true } as CloudExpertAgent;
    expect(selectDigitalEmployees([legacyTeam])).toEqual([]);
    expect(selectDigitalEmployees([legacyTeam], true)).toEqual([legacyTeam]);
  });
});
