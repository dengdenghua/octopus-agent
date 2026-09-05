import { describe, expect, it } from "vitest";

import { emptyConversation, type ExecutionSnapshot, type Turn } from "./items";
import { reduce, type ConversationEvent } from "./reducer";
import { replayEvents, type LoggedEvent } from "./replay";

const turn: Turn = {
  id: "turn",
  threadId: "thread",
  status: "inProgress",
  startedAt: "2026-09-05T00:00:00Z",
  completedAt: null,
  items: [],
  error: null,
};
const primary: ExecutionSnapshot = {
  engine: "codex",
  driver: "codex_app_server",
  reason: "role_backend",
  phase: "primary",
  invocation: 1,
};
const verification: ExecutionSnapshot = {
  ...primary,
  phase: "verification",
  invocation: 2,
};
const event = (execution: ExecutionSnapshot): ConversationEvent => ({
  method: "turn/execution/updated",
  params: { threadId: "thread", turnId: "turn", execution },
});
const initial = () =>
  reduce(emptyConversation("thread"), {
    method: "turn/started",
    params: { threadId: "thread", turn },
  }).next;

describe("durable execution binding", () => {
  it("replays the same engine and phase as live delivery", () => {
    const live = [event(primary), event(verification)].reduce(
      (state, next) => reduce(state, next).next,
      initial(),
    );
    const log: LoggedEvent[] = [
      {
        event: "turn_started",
        threadId: "thread",
        turnId: "turn",
        ts: turn.startedAt,
      },
      ...[primary, verification].map((execution) => ({
        event: "turn_updated",
        threadId: "thread",
        turnId: "turn",
        payload: { execution },
      })),
    ];
    expect(replayEvents(log).conversation.turns[0]?.execution).toEqual(
      live.turns[0]?.execution,
    );
    expect(live.turns[0]?.execution).toEqual(verification);
  });

  it("ignores stale, duplicate, foreign-thread and cross-engine updates", () => {
    const state = reduce(initial(), event(verification)).next;
    for (const incoming of [
      primary,
      verification,
      { ...verification, engine: "octopus" as const, invocation: 3 },
    ]) {
      expect(reduce(state, event(incoming)).next).toBe(state);
    }
    expect(
      reduce(state, {
        method: "turn/execution/updated",
        params: {
          threadId: "different",
          turnId: "turn",
          execution: { ...verification, invocation: 3 },
        },
      }).next,
    ).toBe(state);
  });

  it("keeps the engine evidence when a stale completion or start arrives", () => {
    const state = reduce(initial(), event(verification)).next;
    const started = reduce(state, {
      method: "turn/started",
      params: { threadId: "thread", turn },
    }).next;
    const completed = reduce(started, {
      method: "turn/completed",
      params: {
        threadId: "thread",
        turn: { ...turn, status: "completed", execution: primary },
      },
    }).next;
    expect(completed.turns[0]?.execution).toEqual(verification);
    expect(completed.turns[0]?.status).toBe("completed");
  });

  it.each([
    null,
    {},
    { ...primary, invocation: 0 },
    { ...primary, invocation: "1" },
    { ...primary, phase: "unknown" },
  ])("ignores malformed persisted evidence: %j", (execution) => {
    const state = initial();
    const log: LoggedEvent[] = [
      {
        event: "turn_updated",
        threadId: "thread",
        turnId: "turn",
        payload: { execution },
      },
    ];
    expect(replayEvents(log, { base: state }).conversation.turns).toEqual(
      state.turns,
    );
  });
});
