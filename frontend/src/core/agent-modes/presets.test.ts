import { describe, expect, it } from "vitest";

import { modePresetForAgentMode } from "./presets";

describe("modePresetForAgentMode", () => {
  it("maps top-level work modes to orchestration presets", () => {
    expect(modePresetForAgentMode("develop")).toMatchObject({
      id: "develop",
      workflowPreset: "develop.iterate",
      skillPackProfile: "develop",
      verificationPolicy: "standard",
    });
    expect(modePresetForAgentMode("audit")).toMatchObject({
      id: "audit",
      workflowPreset: "audit.review",
      skillPackProfile: "audit",
      verificationPolicy: "strict",
    });
    expect(modePresetForAgentMode("uxui")).toMatchObject({
      id: "uxui",
      workflowPreset: "uxui.regression",
      skillPackProfile: "uxui",
      verificationPolicy: "visual",
    });
    expect(modePresetForAgentMode("architect")).toMatchObject({
      id: "architect",
      workflowPreset: "architect.design",
      skillPackProfile: "architect",
      verificationPolicy: "standard",
    });
  });

  it("keeps audit as the only user-facing audit mode", () => {
    expect(modePresetForAgentMode("audit")).toMatchObject({
      id: "audit",
      agentMode: "audit",
      workflowPreset: "audit.review",
      skillPackProfile: "audit",
      verificationPolicy: "strict",
    });
  });
});
