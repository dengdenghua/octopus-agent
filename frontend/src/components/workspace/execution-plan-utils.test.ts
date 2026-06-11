import { describe, expect, test } from "vitest";

import { normalizeExecutionPlan } from "./execution-plan-utils";

describe("normalizeExecutionPlan", () => {
  test("fills missing arrays and legacy step shapes", () => {
    const plan = normalizeExecutionPlan({
      id: "legacy-plan-1",
      title: "Legacy plan",
      steps: [
        "Inspect backend",
        { title: "Patch UI", tools: ["pnpm", "vitest"], status: "completed" },
        { description: "Ship it", tool_names: ["browser"] },
      ],
      risk_level: "medium",
    });

    expect(plan).not.toBeNull();
    expect(plan?.plan_id).toBe("legacy-plan-1");
    expect(plan?.steps).toHaveLength(3);
    expect(plan?.steps[0]?.description).toBe("Inspect backend");
    expect(plan?.steps[0]?.tools_needed).toEqual([]);
    expect(plan?.steps[1]?.tools_needed).toEqual(["pnpm", "vitest"]);
    expect(plan?.steps[1]?.status).toBe("completed");
    expect(plan?.steps[2]?.tools_needed).toEqual(["browser"]);
    expect(plan?.estimated_actions).toBe(3);
  });

  test("returns null for non-record input", () => {
    expect(normalizeExecutionPlan(null)).toBeNull();
    expect(normalizeExecutionPlan("bad")).toBeNull();
  });
});
