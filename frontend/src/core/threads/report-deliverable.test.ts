import { describe, expect, it } from "vitest";

import {
  liveEventIsReportLike,
  REPORT_DELIVERABLE_PATTERN,
} from "./report-deliverable";

describe("REPORT_DELIVERABLE_PATTERN", () => {
  it("matches report keywords as whole words only", () => {
    for (const text of [
      "research",
      "deep-research",
      "deep_research",
      "run_deep_research", // wrapper tool name still counts (no boundary)
      "report",
      "wrote reports/out.docx",
      "deliverable.pdf",
      "swarm",
    ]) {
      expect(REPORT_DELIVERABLE_PATTERN.test(text), text).toBe(true);
    }
  });

  it("does not match subagent role names embedded in orchestration input", () => {
    // The run_orchestration payload that caused the pet error: an agent_id
    // roster of [critic, explorer, researcher] must not count as report-like.
    for (const text of [
      '"agent_id":["critic","explorer","researcher"]',
      "researcher",
      "researching",
      "research_engine",
    ]) {
      expect(REPORT_DELIVERABLE_PATTERN.test(text), text).toBe(false);
    }
  });
});

describe("liveEventIsReportLike", () => {
  it("flags report-writing tool events", () => {
    expect(liveEventIsReportLike({ name: "report-writing" })).toBe(true);
  });

  it("flags outputs that mention a report artifact", () => {
    expect(
      liveEventIsReportLike({
        name: "command_run",
        output: "wrote reports/out.docx",
      }),
    ).toBe(true);
  });

  it("does not flag a run_orchestration event whose input lists researcher", () => {
    // Regression for the realtime page pet error: the turn completed with
    // error=null but the pet flipped to the error mood because this event
    // looked report-like.
    expect(
      liveEventIsReportLike({
        name: "run_orchestration",
        input: { goal: "分析项目", agent_id: ["critic", "explorer", "researcher"] },
      }),
    ).toBe(false);
  });

  it("stays false for plain tool events", () => {
    expect(liveEventIsReportLike({ name: "read_file", input: { path: "a.py" } })).toBe(false);
  });
});
