import { describe, expect, it } from "vitest";

import { modePresetForAgentMode, workflowPresetForMode } from "./presets";

describe("modePresetForAgentMode", () => {
  it("maps top-level work modes to orchestration presets", () => {
    expect(modePresetForAgentMode("develop")).toMatchObject({
      id: "develop",
      workflowPreset: "develop.iterate",
      skillPackProfile: "develop",
      verificationPolicy: "standard",
    });
    expect(modePresetForAgentMode("audit")).toMatchObject({
      id: "develop",
      workflowPreset: "develop.iterate",
      skillPackProfile: "develop",
      verificationPolicy: "standard",
    });
    expect(modePresetForAgentMode("uxui")).toMatchObject({
      id: "uxui",
      workflowPreset: "uxui.regression",
      skillPackProfile: "uxui",
      verificationPolicy: "visual",
    });
  });

  it("migrates legacy audit selections into general mode", () => {
    expect(modePresetForAgentMode("audit")).toMatchObject({
      id: "develop",
      agentMode: "develop",
      workflowPreset: "develop.iterate",
      skillPackProfile: "develop",
      verificationPolicy: "standard",
    });
  });
});

describe("workflowPresetForMode", () => {
  it("maps legacy audit intensity values to general mode", () => {
    expect(workflowPresetForMode("audit", "standard")).toBe("develop.iterate");
    expect(workflowPresetForMode("audit", "max")).toBe("develop.iterate");
    expect(workflowPresetForMode("audit")).toBe("develop.iterate");
  });

  it("ignores intensity for non-audit modes (no deep leak)", () => {
    expect(workflowPresetForMode("develop", "max")).toBe("develop.iterate");
    expect(workflowPresetForMode("uxui", "max")).toBe("uxui.regression");
  });
});
