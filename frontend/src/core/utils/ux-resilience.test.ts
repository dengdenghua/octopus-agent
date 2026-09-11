import { describe, expect, it } from "vitest";
import { requireArray, serviceErrorMessage } from "./service-error";
import { displayValue, skillDescription } from "./display-value";
import { firstSubscriptionCheck } from "../automation/schedule-preview";
import { buildThreadRunStatusByHref } from "../threads/sidebar";

describe("UI failure and completion boundaries", () => {
  it("does not turn malformed collections into a valid empty result", () => {
    expect(requireArray([], "人物")).toEqual([]);
    for (const body of [undefined, null, {}, { detail: "Forbidden" }]) {
      expect(() => requireArray(body, "人物")).toThrow("人物");
    }
  });
  it("distinguishes permission, connection and absent content failures", () => {
    expect(
      serviceErrorMessage(new Error("HTTP 403 admin role required")),
    ).toContain("管理权限");
    expect(serviceErrorMessage(new Error("HTTP 502"))).toContain("尚未读取");
    expect(serviceErrorMessage(new Error("HTTP 404"))).toContain("未提供");
    expect(serviceErrorMessage(new Error("Invalid configuration"))).toBe(
      "Invalid configuration",
    );
  });
  it("renders nested metadata and YAML markers as readable text", () => {
    expect(displayValue({ scope: { enabled: true }, agents: ["a", "b"] })).toBe(
      "scope：enabled：是；agents：a、b",
    );
    expect(skillDescription("|")).toContain("暂无用途说明");
    expect(skillDescription(">\n  Produce reports")).toBe("Produce reports");
  });
  it("uses current completion to clear a historical failed team task", () => {
    const href = "/workspace/realtime/thread-1";
    const input: Parameters<typeof buildThreadRunStatusByHref>[0] = {
      activeTeamTasks: [
        { room_id: "thread-1", status: "failed" },
      ] as Parameters<typeof buildThreadRunStatusByHref>[0]["activeTeamTasks"],
      threadHrefById: new Map([["thread-1", href]]),
      liveThreadRunStatusByHref: new Map([[href, "done"]]),
    };
    expect(buildThreadRunStatusByHref(input).has(href)).toBe(false);
    input.liveThreadRunStatusByHref = new Map([[href, "error"]]);
    expect(buildThreadRunStatusByHref(input).get(href)).toBe("error");
  });
  it("previews a fresh subscription according to the service due-time rule", () => {
    const monday = new Date(2026, 8, 7, 10, 0);
    expect(firstSubscriptionCheck("每天", "09:00", "1", monday)).toEqual(
      monday,
    );
    expect(firstSubscriptionCheck("每小时", "", "1", monday)).toEqual(monday);
    expect(firstSubscriptionCheck("每周", "09:00", "2", monday)).toEqual(
      new Date(2026, 8, 8, 9, 0),
    );
    expect(firstSubscriptionCheck("每天", "26:00", "1", monday)).toBeNull();
  });
});
