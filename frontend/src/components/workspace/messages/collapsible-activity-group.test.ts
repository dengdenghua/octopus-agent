import { describe, expect, it } from "vitest";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

import {
  buildHeaderSummary,
  type ActivityItem,
} from "./collapsible-activity-group";

describe("CollapsibleActivityGroup public wording", () => {
  const items: ActivityItem[] = [
    { id: "read-1", label: "Read file" },
    { id: "search-1", label: "Search source" },
  ];

  it("describes grouped operations without exposing tool-call jargon in Chinese", () => {
    const summary = buildHeaderSummary("tool_calls", items, zhCN);

    expect(summary).toContain("操作记录");
    expect(summary).not.toContain("工具调用");
  });

  it("describes grouped operations without exposing tool-call jargon in English", () => {
    const summary = buildHeaderSummary("tool_calls", items, enUS);

    expect(summary).toContain("action record");
    expect(summary?.toLowerCase()).not.toContain("tool call");
  });
});
