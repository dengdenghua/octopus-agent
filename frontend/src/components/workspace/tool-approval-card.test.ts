import { describe, expect, it } from "vitest";

import { getApprovalData, isApprovalRequest } from "./tool-approval-card";

describe("isApprovalRequest", () => {
  it("returns true when content contains [APPROVAL REQUIRED]", () => {
    expect(isApprovalRequest("[APPROVAL REQUIRED] please confirm")).toBe(true);
  });

  it("returns true when additional_kwargs has approval_request", () => {
    expect(isApprovalRequest("", { approval_request: "{}" })).toBe(true);
  });

  it("returns false for plain content", () => {
    expect(isApprovalRequest("hello world")).toBe(false);
  });

  it("returns false for empty inputs", () => {
    expect(isApprovalRequest("", {})).toBe(false);
  });
});

describe("getApprovalData", () => {
  const validPayload = JSON.stringify({
    type: "tool_approval_request",
    tool_name: "bash",
    tool_call_id: "tc_1",
    detail: "run rm -rf",
    args_preview: "rm -rf /tmp",
  });

  it("parses from content with [APPROVAL REQUIRED] marker", () => {
    const content = `[APPROVAL REQUIRED] ${validPayload}`;
    const data = getApprovalData(content);
    expect(data).not.toBeNull();
    expect(data!.tool_name).toBe("bash");
    expect(data!.tool_call_id).toBe("tc_1");
  });

  it("parses from additional_kwargs.approval_request", () => {
    const data = getApprovalData("", { approval_request: validPayload });
    expect(data).not.toBeNull();
    expect(data!.tool_name).toBe("bash");
  });

  it("prefers additional_kwargs over content", () => {
    const altPayload = JSON.stringify({
      type: "tool_approval_request",
      tool_name: "write_file",
      tool_call_id: "tc_2",
      detail: "write",
      args_preview: "",
    });
    const data = getApprovalData(`[APPROVAL REQUIRED] ${validPayload}`, {
      approval_request: altPayload,
    });
    expect(data!.tool_name).toBe("write_file");
  });

  it("returns null for invalid JSON in additional_kwargs", () => {
    expect(getApprovalData("", { approval_request: "not json" })).toBeNull();
  });

  it("returns null for content without marker", () => {
    expect(getApprovalData("just some text")).toBeNull();
  });

  it("returns null for content with marker but no JSON", () => {
    expect(getApprovalData("[APPROVAL REQUIRED] no json here")).toBeNull();
  });
});
