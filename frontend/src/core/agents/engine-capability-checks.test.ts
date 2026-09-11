import { describe, expect, it } from "vitest";
import { engineVerificationLabel } from "./engine-capability-checks";

describe("engine verification labels", () => {
  it("does not confuse configuration with a real call", () => {
    expect(engineVerificationLabel(undefined, true)).toBe("配置就绪，尚无近期调用验证");
  });
  it("expires old evidence and rejects future timestamps", () => {
    const checks = { chat: { state: "verified" as const, checked_at: 1000 } };
    expect(engineVerificationLabel(checks, true, 1001_000)).toBe("最近会话调用通过");
    expect(engineVerificationLabel(checks, true, 1300_000)).toBe("配置就绪，尚无近期调用验证");
    expect(engineVerificationLabel(checks, true, 999_000)).toBe("配置就绪，尚无近期调用验证");
  });
  it("reports failure as recent evidence with retry available", () => {
    expect(engineVerificationLabel({ chat: { state: "failed", checked_at: 1000 } }, false, 1001_000))
      .toBe("Recent session call failed; retry available");
  });
});
