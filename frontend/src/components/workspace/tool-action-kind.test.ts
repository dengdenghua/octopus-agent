import { describe, expect, it } from "vitest";

import {
  actionStateLabel,
  inferToolActionKind,
  inferToolActionKindFromText,
  reasoningStateLabel,
} from "./tool-action-kind";

const zhProbe = "\u601d\u8003\u4e2d";

describe("tool action kind inference", () => {
  it("classifies common tools into user-visible action kinds", () => {
    expect(inferToolActionKind("web_search")).toBe("search");
    expect(inferToolActionKind("list_cwd")).toBe("list");
    expect(inferToolActionKind("read_file")).toBe("read");
    expect(inferToolActionKind("create_file")).toBe("create");
    expect(inferToolActionKind("write_text_file")).toBe("write");
    expect(inferToolActionKind("exec_shell")).toBe("run");
    expect(inferToolActionKind("deep-research-swarm")).toBe("skill");
    expect(inferToolActionKind("planning")).toBe("plan");
  });

  it("classifies action callback text in English and Chinese", () => {
    expect(inferToolActionKindFromText("Action: web_search({})")).toBe("search");
    expect(inferToolActionKindFromText("search official docs")).toBe("search");
    expect(inferToolActionKindFromText("\u641c\u7d22 OpenClaw \u5b98\u65b9\u6587\u6863")).toBe("search");
    expect(inferToolActionKindFromText("\u8bfb\u53d6 README.md")).toBe("read");
    expect(inferToolActionKindFromText("\u6b63\u5728\u521b\u5efa\u6587\u4ef6 plan.md")).toBe("create");
    expect(inferToolActionKindFromText("\u89c4\u5212\u4e0b\u4e00\u6b65")).toBe("plan");
  });
});

describe("tool action labels", () => {
  it("uses precise running and completed Chinese labels", () => {
    expect(actionStateLabel("search", true, zhProbe)).toBe("\u6b63\u5728\u641c\u7d22");
    expect(actionStateLabel("search", false, zhProbe)).toBe("\u5df2\u641c\u7d22");
    expect(actionStateLabel("list", true, zhProbe)).toBe("\u6b63\u5728\u6d4f\u89c8\u76ee\u5f55");
    expect(actionStateLabel("list", false, zhProbe)).toBe("\u5df2\u6d4f\u89c8\u76ee\u5f55");
    expect(actionStateLabel("create", true, zhProbe)).toBe("\u6b63\u5728\u521b\u5efa\u6587\u4ef6");
  });

  it("uses completed labels for historical thinking and active labels for live thinking", () => {
    expect(reasoningStateLabel("\u68c0\u67e5\u7ed3\u679c", false, zhProbe)).toBe("\u601d\u8003");
    expect(reasoningStateLabel("\u68c0\u67e5\u7ed3\u679c", true, zhProbe)).toBe("\u601d\u8003\u4e2d");
    expect(reasoningStateLabel("\u89c4\u5212\u4e0b\u4e00\u6b65", true, zhProbe)).toBe(
      "\u6b63\u5728\u89c4\u5212\u4e0b\u4e00\u6b65",
    );
  });

  it("keeps English labels specific too", () => {
    expect(actionStateLabel("run", true, "Thinking")).toBe("Running command");
    expect(actionStateLabel("run", false, "Thinking")).toBe("Ran command");
    expect(actionStateLabel("plan", true, "Thinking")).toBe("Planning next step");
  });
});
