import { describe, expect, it } from "vitest";

import {
  trustBadgeClass,
  trustTooltip,
  type TrustScore,
} from "./trust";

function score(overrides: Partial<TrustScore> = {}): TrustScore {
  return {
    member_id: "bot-a",
    kind: "agent",
    driver: "ai",
    accountable_owner: "",
    score: 70,
    label: "无记录",
    sample_size: 0,
    components: {
      completed: 0,
      failed: 0,
      rework_count: 0,
      human_signed: 0,
      takeover_count: 0,
    },
    ...overrides,
  };
}

describe("trustTooltip", () => {
  it("无记录时如实说明中立分", () => {
    expect(trustTooltip(score())).toBe("暂无交付记录，中立分。");
  });

  it("有记录时给出构成明细", () => {
    const tip = trustTooltip(
      score({
        sample_size: 4,
        components: {
          completed: 3,
          failed: 1,
          rework_count: 2,
          human_signed: 1,
          takeover_count: 1,
        },
      }),
    );
    expect(tip).toContain("完成 3 / 失败 1");
    expect(tip).toContain("返工 2");
    expect(tip).toContain("人工签收 1");
    expect(tip).toContain("被接管 1");
  });

  it("零值构成不出现", () => {
    const tip = trustTooltip(
      score({
        sample_size: 2,
        components: {
          completed: 2,
          failed: 0,
          rework_count: 0,
          human_signed: 0,
          takeover_count: 0,
        },
      }),
    );
    expect(tip).toContain("完成 2 / 失败 0");
    expect(tip).not.toContain("返工");
    expect(tip).not.toContain("被接管");
  });
});

describe("trustBadgeClass", () => {
  it("四档色阶", () => {
    expect(trustBadgeClass(95)).toContain("emerald");
    expect(trustBadgeClass(70)).toContain("sky");
    expect(trustBadgeClass(55)).toContain("amber");
    expect(trustBadgeClass(30)).toContain("red");
  });
});
