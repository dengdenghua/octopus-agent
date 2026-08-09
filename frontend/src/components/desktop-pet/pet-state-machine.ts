export type PetAction =
  | "idle"
  | "thinking"
  | "working"
  | "waiting"
  | "tired"
  | "happy"
  | "success"
  | "error"
  | "curious"
  | "concerned";

export type PetState = {
  mood: PetAction;
  baseMood: Exclude<PetAction, "success" | "error" | "curious" | "concerned" | "happy">;
  tiredPending: boolean;
};

export type PetStateEvent =
  | { type: "agent"; mood: "idle" | "thinking" | "working" | "waiting" | "success" | "error" | "happy" }
  | { type: "presence"; online: boolean }
  | { type: "tired"; intensity?: number }
  | { type: "complete" };

const TRANSIENT_ACTIONS = new Set<PetAction>(["success", "error", "curious", "concerned", "happy"]);

export function createPetState(): PetState {
  return { mood: "idle", baseMood: "idle", tiredPending: false };
}

export function reducePetState(state: PetState, event: PetStateEvent): PetState {
  if (event.type === "complete") {
    if (TRANSIENT_ACTIONS.has(state.mood)) return { ...state, mood: state.baseMood };
    return state;
  }

  if (event.type === "agent") {
    if (event.mood === "success" || event.mood === "error" || event.mood === "happy") {
      return { ...state, mood: event.mood };
    }
    return {
      mood: event.mood,
      baseMood: event.mood,
      tiredPending: false,
    };
  }

  if (event.type === "presence") {
    if (state.mood !== state.baseMood) return state;
    return { ...state, mood: event.online ? "curious" : "concerned" };
  }

  const tired = (event.intensity ?? 0.5) >= 0.5;
  if (!tired) return state;
  if (state.baseMood === "idle") return { ...state, mood: "tired" };
  return { ...state, tiredPending: true };
}

export function petStateFromAgentEvent(
  state: PetState,
  event: PetStateEvent,
): PetState {
  return reducePetState(state, event);
}
