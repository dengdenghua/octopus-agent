import { describe, expect, it } from "vitest";

import { buildReplayHtml, type ReplayData } from "./replay-html";

function sample(overrides: Partial<ReplayData> = {}): ReplayData {
  return {
    title: "Refactor the auth module",
    steps: [
      { kind: "terminal", title: "run tests", subtitle: "pnpm test", body: "12 passed", status: "done" },
      { kind: "file", title: "edit auth.ts", subtitle: "src/auth.ts", status: "done" },
    ],
    footer: "2026-06-13",
    ...overrides,
  };
}

describe("buildReplayHtml", () => {
  it("emits a self-contained html document with a step player", () => {
    const html = buildReplayHtml(sample());
    expect(html.startsWith("<!doctype html")).toBe(true);
    expect(html.trimEnd().endsWith("</html>")).toBe(true);
    expect(html).toContain("<title>Refactor the auth module");
    // embedded vanilla-JS player + controls + step list
    expect(html).toContain("<script>");
    expect(html).toContain('id="play"');
    expect(html).toContain('id="seek"');
    expect(html).toContain('id="steps"');
    // no external resource references → self-contained
    expect(html).not.toMatch(/src=["']https?:\/\//);
  });

  it("embeds every step's title and body in the data", () => {
    const html = buildReplayHtml(sample());
    expect(html).toContain("run tests");
    expect(html).toContain("12 passed");
    expect(html).toContain("edit auth.ts");
  });

  it("inlines an optional screenshot data-url", () => {
    const img = "data:image/png;base64,AAAA";
    const html = buildReplayHtml(sample({ steps: [{ title: "shot", image: img }] }));
    expect(html).toContain(img);
  });

  it("renders an empty-state (and no script) when there are no steps", () => {
    const html = buildReplayHtml(sample({ steps: [] }));
    expect(html).toContain("No steps");
    expect(html).not.toContain("<script>");
  });

  it("drops empty steps (no title, body or image)", () => {
    const html = buildReplayHtml(
      sample({
        steps: [
          { title: "keep me", kind: "terminal" },
          { title: "", subtitle: "drop me", kind: "file" },
        ],
      }),
    );
    expect(html).toContain("keep me");
    expect(html).not.toContain("drop me");
  });

  it("escapes the title in page chrome (no markup injection)", () => {
    const html = buildReplayHtml(sample({ title: "</title><img src=x onerror=alert(1)>" }));
    expect(html).not.toContain("<img src=x onerror=alert(1)>");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });

  it("neutralises step content that tries to close the script early", () => {
    const html = buildReplayHtml(
      sample({ steps: [{ title: "x", body: "</script><script>alert(1)</script>" }] }),
    );
    expect(html).not.toContain("</script><script>alert(1)");
    expect(html).toContain("<\\/script>");
  });
});
