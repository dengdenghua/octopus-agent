import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useStreamingTextBuffer } from "./use-streaming-text-buffer";

function mockMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
}

describe("useStreamingTextBuffer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows the initial text immediately, then typewriters the growth", () => {
    mockMatchMedia(false);
    const { result, rerender } = renderHook(
      ({ text }: { text: string }) =>
        useStreamingTextBuffer({ targetText: text }),
      { initialProps: { text: "你好" } },
    );
    expect(result.current).toBe("你好");

    const full =
      "你好，这是一段很长的思考内容，用来验证打字机缓冲播放器是否按固定节奏逐步展示，而不会一次性闪烁出来。";
    rerender({ text: full });

    // First tick reveals only a slice, not everything.
    act(() => {
      vi.advanceTimersByTime(40);
    });
    const afterFirstTick = result.current;
    expect(afterFirstTick.length).toBeGreaterThan(2);
    expect(afterFirstTick.length).toBeLessThan(full.length);

    // Catching up: eventually the full text is revealed.
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(result.current).toBe(full);
  });

  it("respects prefers-reduced-motion by showing everything at once", () => {
    mockMatchMedia(true);
    const { result, rerender } = renderHook(
      ({ text }: { text: string }) =>
        useStreamingTextBuffer({ targetText: text }),
      { initialProps: { text: "短" } },
    );
    const full = "这是一段完整的长文本内容，系统要求减少动效时应立即全部展示。";
    rerender({ text: full });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current).toBe(full);
  });

  it("never splits an emoji surrogate pair mid-glyph", () => {
    mockMatchMedia(false);
    const { result, rerender } = renderHook(
      ({ text }: { text: string }) =>
        useStreamingTextBuffer({ targetText: text }),
      { initialProps: { text: "a" } },
    );
    const emojiText = "🎉🎊✨ 测试思考内容 📌🚀 更多文字".repeat(3);
    rerender({ text: emojiText });

    // Sample the buffer at several points during playback.
    for (let i = 0; i < 30; i++) {
      act(() => {
        vi.advanceTimersByTime(40);
      });
      const shown = result.current;
      // Every code point in the shown text must be complete (no orphan
      // high surrogate at the boundary).
      expect([...shown].join("")).toBe(shown);
      if (shown.length > 0) {
        const last = shown.charCodeAt(shown.length - 1);
        // A trailing high surrogate with no low surrogate would be orphaned.
        if (last >= 0xd800 && last <= 0xdbff) {
          const next = emojiText.charCodeAt(shown.length);
          expect(next >= 0xdc00 && next <= 0xdfff).toBe(true);
        }
      }
    }
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(result.current).toBe(emojiText);
  });

  it("drains fast when the stream settles", () => {
    mockMatchMedia(false);
    const { result, rerender } = renderHook(
      ({ text }: { text: string }) =>
        useStreamingTextBuffer({
          targetText: text,
          fastDrainThreshold: 6,
        }),
      { initialProps: { text: "ok" } },
    );
    const tail = "尾巴内容";
    rerender({ text: `已完成，${tail}` });

    // Advance until the backlog is small; the remaining chars drain in one
    // or two ticks thanks to fastDrainThreshold.
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(result.current).toBe(`已完成，${tail}`);
  });
});
