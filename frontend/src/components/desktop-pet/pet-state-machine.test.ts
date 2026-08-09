import { describe, expect, it } from "vitest";

import { createPetState, reducePetState } from "./pet-state-machine";

describe("pet state machine", () => {
  it("maps agent lifecycle states to looping moods", () => {
    let state = createPetState();
    for (const mood of ["thinking", "working", "waiting"] as const) {
      state = reducePetState(state, { type: "agent", mood });
      expect(state).toMatchObject({ mood, baseMood: mood });
    }
  });

  it("restores the active agent state after a transient action", () => {
    const working = reducePetState(createPetState(), { type: "agent", mood: "working" });
    const curious = reducePetState(working, { type: "presence", online: true });
    expect(curious.mood).toBe("curious");
    expect(reducePetState(curious, { type: "complete" }).mood).toBe("working");
  });

  it("keeps offline presence distinct from an agent error", () => {
    const state = reducePetState(createPetState(), { type: "presence", online: false });
    expect(state.mood).toBe("concerned");
    expect(state.mood).not.toBe("error");
  });

  it("defers fatigue while a task is active", () => {
    const working = reducePetState(createPetState(), { type: "agent", mood: "working" });
    const tired = reducePetState(working, { type: "tired", intensity: 0.9 });
    expect(tired).toMatchObject({ mood: "working", tiredPending: true });
  });
});
