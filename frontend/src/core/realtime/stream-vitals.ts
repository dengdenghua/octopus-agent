// Streaming "vitals" — turn-level liveness telemetry the UI uses to tell
// "the model is still working" apart from "the connection actually stuck".
//
// The realtime transport surfaces a rich notification stream (text deltas,
// reasoning deltas, tool progress, per-turn heartbeats) but the status strip
// historically judged liveness by a single number: milliseconds since the
// turn started. That can't distinguish a model mid-thought from a wedged
// socket — after ~12s it always read "waiting for model", alarming or not.
//
// This module records timestamps off the notification stream (see
// ``applyVitalNotification``) and classifies them into a small phase enum
// (see ``classifyVitals``). It is pure and React-free so the classification
// is unit-testable; the ticking React wrapper lives in ``use-stream-vitals``.

/** Coarse liveness state for the active turn. */
export type StreamPhase =
  // No active turn — nothing streaming.
  | "idle"
  // Text deltas are landing right now.
  | "streaming"
  // Turn is active and something is happening server-side (a tool is
  // running, reasoning is streaming, or a heartbeat/activity landed
  // recently) but no text is flowing this instant. The reassuring state.
  | "working"
  // Active turn, no first token yet, still lively — waiting on the model
  // to begin. Distinct from ``working`` only so the label can say so.
  | "waiting"
  // Connected, but no activity of any kind for a suspicious stretch and no
  // tool is running. Genuinely ambiguous — the honest "maybe stuck" state.
  | "slow"
  // The transport is down (auto-reconnect in flight). Definitely not the
  // model's fault.
  | "disconnected";

/** Mutable timestamp record accumulated off the notification stream. All
 * fields are epoch-ms (Date.now) or null when not yet observed. */
export interface VitalsMarks {
  /** Turn these marks belong to. Null only when the wire event has no id. */
  activeTurnId: string | null;
  /** ``turn/started`` — the wall-clock origin for elapsed + TTFT. */
  turnStartedAt: number | null;
  /** First ``item/agentMessage/delta`` of the turn — fixes TTFT. */
  firstDeltaAt: number | null;
  /** Most recent text delta — drives "streaming" freshness. */
  lastDeltaAt: number | null;
  /** Most recent activity of ANY kind (delta, tool progress, heartbeat).
   * Drives stall detection. */
  lastActivityAt: number | null;
  /** Most recent ``turn/heartbeat`` — team-mode keepalive. */
  lastHeartbeatAt: number | null;
  /** Server-reported elapsed seconds from the last heartbeat, if any. */
  heartbeatElapsedS: number | null;
  /** Worst gap observed between successive text deltas this turn (ms) —
   * the "streaming interval" metric. */
  maxDeltaGapMs: number;
}

/** Derived, render-ready liveness snapshot. */
export interface StreamVitals {
  phase: StreamPhase;
  /** Time-to-first-token (ms). Null until the first token / no turn. */
  ttftMs: number | null;
  /** Age of the most recent text delta (ms). Infinity when none yet. */
  lastDeltaAgeMs: number;
  /** Age of the most recent activity of any kind (ms). Infinity when none. */
  sinceActivityMs: number;
  /** Elapsed wall-time of the active turn (ms). */
  elapsedMs: number;
  /** Worst inter-delta gap seen this turn (ms). */
  maxDeltaGapMs: number;
  /** True once we're in a state worth flagging (slow / disconnected). */
  stalled: boolean;
}

export interface VitalsThresholds {
  /** Delta age below this → "streaming". */
  streamingFreshMs: number;
  /** Total silence (no activity, no running tool) beyond this → "slow". */
  activityStaleMs: number;
}

export const DEFAULT_VITALS_THRESHOLDS: VitalsThresholds = {
  streamingFreshMs: 1500,
  // Single-agent turns emit no heartbeat (only team topology does), so a
  // silent reasoning pause has no positive "alive" signal. 10s of total
  // silence with the socket up and no tool running is where "still
  // working" stops being a safe assumption — matches the pre-existing
  // 12s "waitingForModel" intuition while leaving headroom for a tick.
  activityStaleMs: 10_000,
};

export function emptyVitalsMarks(): VitalsMarks {
  return {
    activeTurnId: null,
    turnStartedAt: null,
    firstDeltaAt: null,
    lastDeltaAt: null,
    lastActivityAt: null,
    lastHeartbeatAt: null,
    heartbeatElapsedS: null,
    maxDeltaGapMs: 0,
  };
}

export function emptyVitals(): StreamVitals {
  return {
    phase: "idle",
    ttftMs: null,
    lastDeltaAgeMs: Infinity,
    sinceActivityMs: Infinity,
    elapsedMs: 0,
    maxDeltaGapMs: 0,
    stalled: false,
  };
}

// Notification methods that count as "the server is doing work". Anything
// under ``item/`` (text/reasoning deltas, tool progress, lifecycle) plus
// the explicit per-turn heartbeat. Kept broad on purpose: a new item
// sub-method should register as activity without a code change here.
function isActivityMethod(method: string): boolean {
  return method.startsWith("item/") || method === "turn/heartbeat";
}

/** Fold one realtime notification into the marks, in place. Call BEFORE
 * the reducer sees it; ``now`` is injected for testability. */
export function applyVitalNotification(
  marks: VitalsMarks,
  note: { method: string; params?: Record<string, unknown> },
  now: number,
): void {
  const { method, params } = note;

  if (method === "turn/started") {
    // A fresh turn resets everything; the started event is itself activity.
    const wireTurn = params?.turn;
    const wireTurnId =
      wireTurn && typeof wireTurn === "object" && "id" in wireTurn
        ? (wireTurn as { id?: unknown }).id
        : params?.turnId;
    marks.activeTurnId = typeof wireTurnId === "string" ? wireTurnId : null;
    marks.turnStartedAt = now;
    marks.firstDeltaAt = null;
    marks.lastDeltaAt = null;
    marks.lastActivityAt = now;
    marks.lastHeartbeatAt = null;
    marks.heartbeatElapsedS = null;
    marks.maxDeltaGapMs = 0;
    return;
  }

  if (method === "item/agentMessage/delta") {
    if (marks.lastDeltaAt != null) {
      marks.maxDeltaGapMs = Math.max(
        marks.maxDeltaGapMs,
        now - marks.lastDeltaAt,
      );
    }
    if (marks.firstDeltaAt == null) marks.firstDeltaAt = now;
    marks.lastDeltaAt = now;
    marks.lastActivityAt = now;
    return;
  }

  if (method === "turn/heartbeat") {
    marks.lastHeartbeatAt = now;
    const elapsed = params?.elapsedS;
    if (typeof elapsed === "number" && Number.isFinite(elapsed)) {
      marks.heartbeatElapsedS = elapsed;
    }
    marks.lastActivityAt = now;
    return;
  }

  if (isActivityMethod(method)) {
    marks.lastActivityAt = now;
  }
}

/** Refresh liveness when thread/resume confirms that a turn is still active.
 * A different turn resets stale marks; the same turn preserves TTFT and gap
 * observations collected before reconnect. */
export function seedVitalsFromResumedTurn(
  marks: VitalsMarks,
  turn: { id?: unknown; status?: unknown; startedAt?: unknown } | null,
  now: number,
): void {
  if (!turn || typeof turn.id !== "string" || turn.status !== "inProgress") {
    return;
  }

  if (marks.activeTurnId !== turn.id) {
    Object.assign(marks, emptyVitalsMarks());
    marks.activeTurnId = turn.id;
    const parsedStartedAt =
      typeof turn.startedAt === "string" ? Date.parse(turn.startedAt) : NaN;
    marks.turnStartedAt = Number.isFinite(parsedStartedAt)
      ? Math.min(parsedStartedAt, now)
      : now;
  }
  // The resume response is positive evidence from the server and starts a
  // fresh silence window. If nothing follows, classification becomes slow.
  marks.lastActivityAt = now;
}

export interface ClassifyInput {
  marks: VitalsMarks;
  /** Transport is up (WebSocket open). */
  connected: boolean;
  /** The most recent turn is still ``inProgress``. */
  turnActive: boolean;
  /** A tool/subagent item is currently running — protects long silent
   * tool calls (a 60s command) from being flagged "slow". */
  hasRunningWork: boolean;
}

/** Classify accumulated marks into a render-ready snapshot. Pure. */
export function classifyVitals(
  input: ClassifyInput,
  now: number,
  thresholds: VitalsThresholds = DEFAULT_VITALS_THRESHOLDS,
): StreamVitals {
  const { marks, connected, turnActive, hasRunningWork } = input;

  const ttftMs =
    marks.turnStartedAt != null && marks.firstDeltaAt != null
      ? Math.max(0, marks.firstDeltaAt - marks.turnStartedAt)
      : null;
  const lastDeltaAgeMs =
    marks.lastDeltaAt != null ? Math.max(0, now - marks.lastDeltaAt) : Infinity;
  const sinceActivityMs =
    marks.lastActivityAt != null
      ? Math.max(0, now - marks.lastActivityAt)
      : Infinity;
  const elapsedMs =
    marks.turnStartedAt != null ? Math.max(0, now - marks.turnStartedAt) : 0;

  const base = {
    ttftMs,
    lastDeltaAgeMs,
    sinceActivityMs,
    elapsedMs,
    maxDeltaGapMs: marks.maxDeltaGapMs,
  };

  if (!turnActive) return { ...emptyVitals(), ...base, phase: "idle" };
  if (!connected) return { ...base, phase: "disconnected", stalled: true };

  // Text is flowing this instant.
  if (lastDeltaAgeMs < thresholds.streamingFreshMs) {
    return { ...base, phase: "streaming", stalled: false };
  }

  // No local telemetry for this turn yet — e.g. a turn resumed mid-flight,
  // where marks are empty until the first live notification lands. Don't
  // accuse the connection on absent evidence; assume the server is working.
  if (marks.lastActivityAt == null) {
    return { ...base, phase: "working", stalled: false };
  }

  // Silent too long with nothing running → the honest "maybe stuck" state.
  // A running tool or a fresh activity/heartbeat keeps us out of here.
  if (!hasRunningWork && sinceActivityMs >= thresholds.activityStaleMs) {
    return { ...base, phase: "slow", stalled: true };
  }

  // Waiting on the model to *begin*: no visible text, no running tool, and
  // nothing has happened since the turn opened. Any real activity beyond
  // the start (reasoning, heartbeat, tool progress) is "working", not this.
  const hadActivity =
    marks.turnStartedAt != null && marks.lastActivityAt > marks.turnStartedAt;
  if (marks.firstDeltaAt == null && !hasRunningWork && !hadActivity) {
    return { ...base, phase: "waiting", stalled: false };
  }

  // Active and recently alive: tool running, reasoning streaming, or a
  // between-chunks pause the server is clearly still working through.
  return { ...base, phase: "working", stalled: false };
}
