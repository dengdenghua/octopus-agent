import { useEffect, useRef, useState } from "react";

/**
 * Typewriter buffer for streaming text.
 *
 * Instead of rendering every delta as it arrives (which makes long replies
 * flicker at render speed), this hook plays the incoming text back at a
 * fixed tick rate — accelerating on a large backlog, easing off as it
 * catches up — so the UI reads like a smooth typewriter. When the stream
 * finishes, the remaining backlog drains and the full text is shown.
 *
 * Design mirrors the WorkBuddy client's `useStreamingTextBuffer`
 * (40ms ticks, 1–4 chars/frame, accel/decel, drain-on-finish) with two
 * important guards:
 *
 *  - `prefers-reduced-motion` users always get the full text immediately
 *    (no animation).
 *  - Emoji surrogate pairs are never split mid-glyph.
 */
export interface StreamingTextBufferOptions {
  targetText: string;
  /** When false, the full text is shown immediately (no animation). */
  enabled?: boolean;
  /**
   * When the stream finishes (enabled flips false) with a backlog still
   * unplayed, drain it at the typewriter pace instead of jumping straight
   * to the full text. Without this, a backend that delivers the whole
   * answer in one delta + immediate completion would show the text
   * instantly — no typewriter at all. Mirrors WorkBuddy's drainOnFinish.
   * Default true.
   */
  drainOnFinish?: boolean;
  /**
   * Sentence-paced playback (L2): each tick advances at most
   * `sentenceWindowChars`, but prefers to stop exactly at a sentence
   * boundary (。！？;、newline, English .!? followed by space) so a whole
   * sentence appears in one beat — reads like a person speaking rather
   * than a uniform character-by-character machine. Large backlogs still
   * stream quickly because the window cap applies every tick. Default
   * true.
   */
  sentencePacing?: boolean;
  /** Max chars revealed per tick under sentence pacing. Default 120. */
  sentenceWindowChars?: number;
  /** Bump this to reset the buffer to the target text (e.g. message id). */
  resetKey?: string | number;
  /** Milliseconds between ticks. Default 40. */
  targetIntervalMs?: number;
  /** Minimum chars revealed per tick. Default 1. */
  minCharsPerTick?: number;
  /** Maximum chars revealed per tick. Default 4. */
  maxCharsPerTick?: number;
  /** Backlog ratio used to size each tick (accel). Default 20. */
  backlogDivisor?: number;
  /** Immediately reveal everything when backlog drops below this. */
  fastDrainThreshold?: number;
}

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_MOTION_QUERY).matches
  );
}

/**
 * Never split an emoji surrogate pair: if `length` lands right after a
 * high surrogate (0xD800–0xDBFF) with a low surrogate next, extend by one.
 */
function clampToSafeCharBoundary(text: string, length: number): number {
  if (length <= 0 || length >= text.length) return length;
  const code = text.charCodeAt(length - 1);
  if (code >= 0xd800 && code <= 0xdbff) {
    const next = text.charCodeAt(length);
    if (next >= 0xdc00 && next <= 0xdfff) return length + 1;
  }
  return length;
}

// Sentence enders that make the typewriter read like speech. Chinese
// punctuation is unambiguous; an English "." only counts when followed by
// whitespace or EOS so "3.14" / "e.g." are not split mid-sentence.
const SENTENCE_END_RE = /[。！？!?；;、\n]|\.(?=\s|$)/g;

/**
 * Find the index just past the next sentence boundary at/after `from`.
 * Returns -1 when the text has no boundary yet (stream still mid-sentence).
 */
function findSentenceEndAfter(text: string, from: number): number {
  if (from >= text.length) return -1;
  SENTENCE_END_RE.lastIndex = from;
  const m = SENTENCE_END_RE.exec(text);
  if (!m) return -1;
  return m.index + m[0].length;
}

export function useStreamingTextBuffer({
  targetText,
  enabled = true,
  drainOnFinish = true,
  sentencePacing = true,
  sentenceWindowChars = 120,
  resetKey,
  targetIntervalMs = 40,
  minCharsPerTick = 1,
  maxCharsPerTick = 4,
  backlogDivisor = 20,
  fastDrainThreshold = 0,
}: StreamingTextBufferOptions): string {
  const [displayText, setDisplayText] = useState(targetText);
  const displayRef = useRef(targetText.length);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reducedMotionRef = useRef(prefersReducedMotion());
  const resetKeyRef = useRef(resetKey);
  const drainingRef = useRef(false);

  // Track the OS "reduce motion" preference while mounted.
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(REDUCED_MOTION_QUERY);
    const handle = () => {
      reducedMotionRef.current = mql.matches;
    };
    reducedMotionRef.current = mql.matches;
    mql.addEventListener?.("change", handle);
    return () => mql.removeEventListener?.("change", handle);
  }, []);

  // Hard reset when the target message changes identity.
  useEffect(() => {
    if (resetKey !== resetKeyRef.current) {
      resetKeyRef.current = resetKey;
      displayRef.current = targetText.length;
      drainingRef.current = false;
      setDisplayText(targetText);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  // Drive the typewriter as the target text grows.
  useEffect(() => {
    if (reducedMotionRef.current) {
      displayRef.current = targetText.length;
      drainingRef.current = false;
      setDisplayText(targetText);
      return;
    }
    const finishDrain = () => {
      displayRef.current = targetText.length;
      drainingRef.current = false;
      setDisplayText(targetText);
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    };
    if (!enabled) {
      // Stream finished. If there's still a backlog and drainOnFinish is
      // set, keep playing at typewriter pace (WorkBuddy drainOnFinish);
      // otherwise reveal the full text now.
      if (drainOnFinish && displayRef.current < targetText.length) {
        drainingRef.current = true;
      } else {
        finishDrain();
        return;
      }
    }
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }

    const advance = (chars: number) => {
      const clamped = clampToSafeCharBoundary(
        targetText,
        displayRef.current + chars,
      );
      displayRef.current = Math.min(clamped, targetText.length);
      setDisplayText(targetText.slice(0, displayRef.current));
      if (displayRef.current >= targetText.length) {
        finishDrain();
      }
    };

    const tick = () => {
      const backlog = targetText.length - displayRef.current;
      if (backlog <= 0) {
        finishDrain();
        return;
      }
      // Drain mode (stream finished): finish at char-level pace — the
      // sentence grouping is a live-stream nicety, not a replay device.
      if (drainingRef.current) {
        let step: number;
        if (backlog <= fastDrainThreshold) {
          step = backlog;
        } else {
          step = Math.max(
            minCharsPerTick,
            Math.round(backlog / backlogDivisor),
          );
          step = Math.min(step, maxCharsPerTick);
        }
        advance(Math.min(step, backlog));
        return;
      }
      // Sentence-paced playback: advance at most sentenceWindowChars but
      // prefer landing exactly on a sentence boundary so the whole
      // sentence appears in one beat.
      if (sentencePacing && backlog > fastDrainThreshold) {
        const windowEnd = Math.min(
          targetText.length,
          displayRef.current + sentenceWindowChars,
        );
        const sentenceEnd = findSentenceEndAfter(targetText, displayRef.current);
        const goal =
          sentenceEnd !== -1 && sentenceEnd <= windowEnd
            ? sentenceEnd
            : windowEnd;
        advance(Math.max(1, goal - displayRef.current));
        return;
      }
      // Uniform char-level fallback (sentencePacing off).
      let step: number;
      if (backlog <= fastDrainThreshold) {
        step = backlog;
      } else {
        step = Math.max(minCharsPerTick, Math.round(backlog / backlogDivisor));
        step = Math.min(step, maxCharsPerTick);
      }
      advance(Math.min(step, backlog));
    };

    if (displayRef.current >= targetText.length) {
      finishDrain();
      return;
    }
    tickRef.current = setInterval(tick, targetIntervalMs);
    return () => {
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    };
  }, [
    targetText,
    enabled,
    drainOnFinish,
    sentencePacing,
    sentenceWindowChars,
    targetIntervalMs,
    minCharsPerTick,
    maxCharsPerTick,
    backlogDivisor,
    fastDrainThreshold,
  ]);

  // Cleanup on unmount.
  useEffect(
    () => () => {
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    },
    [],
  );

  return displayText;
}
