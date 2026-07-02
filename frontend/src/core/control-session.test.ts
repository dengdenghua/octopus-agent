import { describe, expect, it, vi } from "vitest";

import {
  controlInterruptionDetail,
  getControlStopReason,
  runControlSessionAction,
  type ControlEvidence,
} from "./control-session";

describe("control-session", () => {
  it("normalizes boolean stop checks to operator_stop", () => {
    expect(getControlStopReason({ getStopped: () => true })).toBe(
      "operator_stop",
    );
    expect(getControlStopReason({ getStopped: () => "target_changed" })).toBe(
      "target_changed",
    );
    expect(getControlStopReason({ getStopped: () => false })).toBeNull();
  });

  it("returns compact interruption details", () => {
    expect(
      controlInterruptionDetail("target_changed", {
        surface: "electron_webview",
        targetId: "tab_1",
      }),
    ).toEqual({
      code: "control_session_interrupted",
      reason: "target_changed",
      surface: "electron_webview",
      targetId: "tab_1",
    });
  });

  it("wraps a successful action with indicator and evidence events", async () => {
    const setIndicator = vi.fn();
    const evidence: ControlEvidence[] = [];

    const result = await runControlSessionAction(
      { type: "click", selector: "#go" },
      async () => "ok",
      {
        control: {
          surface: "browser",
          targetId: "tab_1",
          setIndicator,
          recordEvidence: (item) => evidence.push(item),
          now: () => 100,
        },
        interrupted: (reason) => `interrupted:${reason}`,
      },
    );

    expect(result).toBe("ok");
    expect(setIndicator).toHaveBeenNthCalledWith(1, "action", {
      action: "click",
      surface: "browser",
      targetId: "tab_1",
    });
    expect(setIndicator).toHaveBeenLastCalledWith("idle", {
      action: "click",
    });
    expect(evidence).toEqual([
      {
        kind: "action",
        at: 100,
        action: "click",
        summary: "started",
      },
      {
        kind: "result",
        at: 100,
        action: "click",
        ok: true,
        summary: "completed",
      },
    ]);
  });

  it("does not run the action when already stopped", async () => {
    const run = vi.fn();
    const setIndicator = vi.fn();

    const result = await runControlSessionAction("click", run, {
      control: {
        surface: "computer",
        getStopped: () => "lease_lost",
        setIndicator,
      },
      interrupted: (reason) => `interrupted:${reason}`,
    });

    expect(run).not.toHaveBeenCalled();
    expect(result).toBe("interrupted:lease_lost");
    expect(setIndicator).toHaveBeenCalledWith("paused", {
      action: "click",
      reason: "lease_lost",
    });
  });
});
