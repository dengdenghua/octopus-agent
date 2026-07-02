export type ControlSurface =
  | "browser"
  | "chrome"
  | "electron_webview"
  | "backend_preview"
  | "computer";

export type ControlIndicatorMode = "idle" | "action" | "paused";

export type ControlStopReason =
  | "operator_stop"
  | "target_changed"
  | "lease_lost"
  | "timeout"
  | "session_replaced";

export type ControlActionDescriptor =
  | string
  | {
      type?: string;
      [key: string]: unknown;
    };

export interface ControlEvidence {
  id?: string;
  kind: "action" | "result" | "screenshot" | "dom" | "lease" | "log";
  at?: number;
  action?: string;
  ok?: boolean;
  summary?: string;
  detail?: unknown;
}

export interface ControlSessionOptions {
  sessionId?: string;
  ownerLabel?: string;
  surface?: ControlSurface;
  targetId?: string | number | null;
  timeoutMs?: number;
  getStopped?: () => boolean | ControlStopReason;
  setIndicator?: (
    mode: ControlIndicatorMode,
    detail?: Record<string, unknown>,
  ) => void | Promise<void>;
  recordEvidence?: (evidence: ControlEvidence) => void | Promise<void>;
  now?: () => number;
}

export function getControlActionType(action: ControlActionDescriptor): string {
  if (typeof action === "string") return action;
  return typeof action.type === "string" && action.type
    ? action.type
    : "action";
}

export function getControlStopReason(
  control?: ControlSessionOptions,
): ControlStopReason | null {
  const stopped = control?.getStopped?.();
  if (!stopped) return null;
  return typeof stopped === "string" ? stopped : "operator_stop";
}

export function controlInterruptionDetail(
  reason: ControlStopReason,
  control?: ControlSessionOptions,
): Record<string, unknown> {
  return compactRecord({
    code: "control_session_interrupted",
    reason,
    sessionId: control?.sessionId,
    ownerLabel: control?.ownerLabel,
    surface: control?.surface,
    targetId: control?.targetId,
  });
}

function compactRecord(
  record: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(record).filter(([, value]) => value !== undefined),
  );
}

export async function runControlSessionAction<T>(
  action: ControlActionDescriptor,
  run: () => Promise<T>,
  options: {
    control?: ControlSessionOptions;
    interrupted: (reason: ControlStopReason) => T;
  },
): Promise<T> {
  const { control } = options;
  const actionType = getControlActionType(action);
  const now = control?.now ?? Date.now;
  const stoppedBefore = getControlStopReason(control);
  if (stoppedBefore) {
    await control?.setIndicator?.("paused", {
      action: actionType,
      reason: stoppedBefore,
    });
    await control?.recordEvidence?.({
      kind: "result",
      at: now(),
      action: actionType,
      ok: false,
      summary: `interrupted:${stoppedBefore}`,
      detail: controlInterruptionDetail(stoppedBefore, control),
    });
    return options.interrupted(stoppedBefore);
  }

  await control?.setIndicator?.(
    "action",
    compactRecord({
      action: actionType,
      surface: control.surface,
      targetId: control.targetId,
      sessionId: control.sessionId,
      ownerLabel: control.ownerLabel,
    }),
  );
  await control?.recordEvidence?.({
    kind: "action",
    at: now(),
    action: actionType,
    summary: "started",
  });

  try {
    const result = await run();
    const stoppedAfter = getControlStopReason(control);
    if (stoppedAfter) {
      await control?.setIndicator?.("paused", {
        action: actionType,
        reason: stoppedAfter,
      });
      await control?.recordEvidence?.({
        kind: "result",
        at: now(),
        action: actionType,
        ok: false,
        summary: `interrupted:${stoppedAfter}`,
        detail: controlInterruptionDetail(stoppedAfter, control),
      });
      return options.interrupted(stoppedAfter);
    }
    await control?.recordEvidence?.({
      kind: "result",
      at: now(),
      action: actionType,
      ok: true,
      summary: "completed",
    });
    return result;
  } finally {
    if (!getControlStopReason(control)) {
      await control?.setIndicator?.(
        "idle",
        compactRecord({
          action: actionType,
          sessionId: control?.sessionId,
        }),
      );
    }
  }
}
