import { describe, expect, it } from "vitest";

import { buildReplayHtml, type ReplayData } from "./replay-html";

const FRAME_A = "data:image/svg+xml,<svg/>A";
const FRAME_B = "data:image/svg+xml,<svg/>B";

function sample(overrides: Partial<ReplayData> = {}): ReplayData {
  return {
    title: "Book a flight",
    frames: [
      { image: FRAME_A, caption: "open the site" },
      { image: FRAME_B, caption: "search flights" },
    ],
    footer: "2026-06-13",
    ...overrides,
  };
}

describe("buildReplayHtml", () => {
  it("emits a self-contained html document with a player", () => {
    const html = buildReplayHtml(sample());
    expect(html.startsWith("<!doctype html")).toBe(true);
    expect(html.trimEnd().endsWith("</html>")).toBe(true);
    expect(html).toContain("<title>Book a flight");
    // the embedded vanilla-JS player + controls
    expect(html).toContain("<script>");
    expect(html).toContain('id="play"');
    expect(html).toContain('id="seek"');
    // no external resource references → self-contained
    expect(html).not.toMatch(/src=["']https?:\/\//);
  });

  it("embeds every frame's data-url", () => {
    const html = buildReplayHtml(sample());
    expect(html).toContain(FRAME_A);
    expect(html).toContain(FRAME_B);
  });

  it("renders an empty-state (and no script) when there are no frames", () => {
    const html = buildReplayHtml(sample({ frames: [] }));
    expect(html).toContain("No frames");
    expect(html).not.toContain("<script>");
  });

  it("drops malformed frames (missing image)", () => {
    const html = buildReplayHtml(
      sample({
        frames: [
          { image: FRAME_A, caption: "ok" },
          { image: "", caption: "broken" } as never,
        ],
      }),
    );
    expect(html).toContain(FRAME_A);
    expect(html).not.toContain("broken");
  });

  it("escapes the title in page chrome (no markup injection)", () => {
    const html = buildReplayHtml(sample({ title: "</title><img src=x onerror=alert(1)>" }));
    expect(html).not.toContain("<img src=x onerror=alert(1)>");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });

  it("neutralises a frame data-url that tries to close the script early", () => {
    const html = buildReplayHtml(
      sample({ frames: [{ image: "data:,</script><script>alert(1)</script>" }] }),
    );
    // The raw closer must be broken up so it can't end the data <script>.
    expect(html).not.toContain("</script><script>alert(1)");
    expect(html).toContain("<\\/script>");
  });
});
