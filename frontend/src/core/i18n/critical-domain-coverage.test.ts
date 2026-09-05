import { describe, expect, it } from "vitest";

import { agentOperatorJaJP, agentOperatorKoKR } from "./locales/agent-operator";
import {
  workspaceComputerJaJP,
  workspaceComputerKoKR,
} from "./locales/workspace-computer";

const OPERATOR_CRITICAL_KEYS = [
  "Operator loop",
  "Agent evolution queue",
  "Apply promoted",
  "Refresh",
  "Pending review queue",
  "Task recovery queue",
  "Take over",
  "Competitor scorecard",
  "Scorecard",
  "Evidence",
  "Automation",
  "Plugin health",
  "Publisher trust",
  "Tool safety",
  "Subagent risk",
  "Topology policy",
  "Team promotion",
  "Promote",
  "Reject",
  "Archive",
] as const;

const COMPUTER_CRITICAL_KEYS = [
  "Local computer automation",
  "Computer assistant",
  "Refresh status",
  "Capture screen",
  "Runtime health",
  "Confirmation mode",
  "Screen observation",
  "Live computer screen",
  "Task plan",
  "Preview agent loop",
  "Observe and plan next step",
  "Add for confirmation",
  "Vision output",
  "Action preview",
  "Confirmation queue",
  "Confirm and run",
  "Activity log",
  "Waiting for confirmation",
  "Generate plan",
  "Execute action",
  "Release control",
  "Ready",
  "Blocked",
  "Running",
  "Paused",
  "Expired",
] as const;

function expectTranslated(
  locale: string,
  sourceKeys: readonly string[],
  copy: Record<string, string>,
) {
  for (const source of sourceKeys) {
    const translated = copy[source];
    expect(
      translated,
      `${locale} is missing critical translation for “${source}”`,
    ).toBeTruthy();
    expect(
      translated,
      `${locale} still displays the English source for “${source}”`,
    ).not.toBe(source);
  }
}

describe("critical locale coverage", () => {
  it("covers the high-frequency operator controls in Japanese and Korean", () => {
    expectTranslated(
      "ja-JP agentOperator",
      OPERATOR_CRITICAL_KEYS,
      agentOperatorJaJP,
    );
    expectTranslated(
      "ko-KR agentOperator",
      OPERATOR_CRITICAL_KEYS,
      agentOperatorKoKR,
    );
  });

  it("covers the high-frequency computer controls in Japanese and Korean", () => {
    expectTranslated(
      "ja-JP workspaceComputer",
      COMPUTER_CRITICAL_KEYS,
      workspaceComputerJaJP,
    );
    expectTranslated(
      "ko-KR workspaceComputer",
      COMPUTER_CRITICAL_KEYS,
      workspaceComputerKoKR,
    );
  });
});
