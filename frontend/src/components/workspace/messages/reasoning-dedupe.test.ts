import { describe, expect, test } from "vitest";

import {
  normalizeReasoningTextForDedupe,
  shouldShowReasoningProcessText,
} from "./reasoning-dedupe";

describe("reasoning summary/process dedupe", () => {
  test("treats bullet summary and plain process thought as duplicate", () => {
    expect(
      shouldShowReasoningProcessText(
        "用户问我能做什么，我应该简洁地列出我的主要能力",
        "- 用户问我能做什么，我应该简洁地列出我的主要能力",
        [
          {
            kind: "thought",
            text: "用户问我能做什么，我应该简洁地列出我的主要能力",
          },
        ],
      ),
    ).toBe(false);
  });

  test("treats Thought-prefixed reasoning and derived bullet summary as duplicate", () => {
    expect(
      shouldShowReasoningProcessText(
        "Thought: I should answer briefly with the main capabilities.",
        "- I should answer briefly with the main capabilities",
        [
          {
            kind: "thought",
            text: "I should answer briefly with the main capabilities",
          },
        ],
      ),
    ).toBe(false);
  });

  test("keeps execution log when it contains real non-thought events", () => {
    expect(
      shouldShowReasoningProcessText(
        'Thought: Check files.\nAction: read_file({ path: "x" })',
        "- Check files",
        [
          { kind: "thought", text: "Check files" },
          { kind: "tool", text: "read_file x" },
        ],
      ),
    ).toBe(true);
  });

  test("keeps distinct process thoughts", () => {
    expect(
      shouldShowReasoningProcessText(
        "I need to inspect the failing route first.",
        "- I can help with coding and product work",
        [
          {
            kind: "thought",
            text: "I need to inspect the failing route first",
          },
        ],
      ),
    ).toBe(true);
  });

  test("normalizes bullets, labels, punctuation, and whitespace", () => {
    expect(
      normalizeReasoningTextForDedupe(
        "  - Thought: 用户问我能做什么，我应该简洁地列出我的主要能力。\n",
      ),
    ).toBe("用户问我能做什么，我应该简洁地列出我的主要能力");
  });
});
