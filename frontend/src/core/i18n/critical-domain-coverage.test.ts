import { describe, expect, it } from "vitest";

import { agentOperatorJaJP, agentOperatorKoKR } from "./locales/agent-operator";
import {
  workspaceComputerJaJP,
  workspaceComputerKoKR,
} from "./locales/workspace-computer";
import { jaJP } from "./locales/ja-JP";
import { koKR } from "./locales/ko-KR";

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

  it("does not ship explicit source-key placeholders in dynamic locale maps", () => {
    const technicalTokens = new Set(["pass^k"]);
    for (const [locale, copy] of [
      ["ja-JP agentOperator", agentOperatorJaJP],
      ["ko-KR agentOperator", agentOperatorKoKR],
      ["ja-JP workspaceComputer", workspaceComputerJaJP],
      ["ko-KR workspaceComputer", workspaceComputerKoKR],
    ] as const) {
      for (const [source, translated] of Object.entries(copy)) {
        expect(
          translated,
          `${locale} has an empty translation for “${source}”`,
        ).toBeTruthy();
        if (technicalTokens.has(source)) continue;
        expect(
          translated,
          `${locale} explicitly repeats the source key “${source}”`,
        ).not.toBe(source);
      }
    }
  });

  it("keeps browser settings and swarm status labels localized", () => {
    for (const [locale, translations] of [
      ["ja-JP", jaJP],
      ["ko-KR", koKR],
    ] as const) {
      expect(translations.browserSettings.tabBrowsers, locale).not.toBe(
        "Browsers",
      );
      expect(translations.browserSettings.refresh, locale).not.toBe("Rescan");
      expect(translations.browserSettings.recommended, locale).not.toBe(
        "Recommended",
      );
      expect(translations.swarmPanel.collapse, locale).not.toBe("Collapse");
      expect(translations.swarmPanel.viewing, locale).not.toBe("Viewing");
      expect(translations.swarmPanel.taskStatuses.running, locale).not.toBe(
        "Running",
      );
      expect(translations.swarmPanel.phaseSynthesize, locale).not.toBe(
        "Synthesize",
      );
    }
  });
});
