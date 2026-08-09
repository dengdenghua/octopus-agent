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

export function useStreamingTextBuffer({
  targetText,
  enabled = true,
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
      setDisplayText(targetText);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  // Drive the typewriter as the target text grows.
  useEffect(() => {
    if (!enabled || reducedMotionRef.current) {
      displayRef.current = targetText.length;
      setDisplayText(targetText);
      return;
    }
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }

    const tick = () => {
      const backlog = targetText.length - displayRef.current;
      if (backlog <= 0) {
        if (tickRef.current) {
          clearInterval(tickRef.current);
          tickRef.current = null;
        }
        return;
      }
      let step: number;
      if (backlog <= fastDrainThreshold) {
        step = backlog;
      } else {
        // Accelerate on a large backlog, ease off as we catch up.
        step = Math.max(minCharsPerTick, Math.round(backlog / backlogDivisor));
        step = Math.min(step, maxCharsPerTick);
      }
      step = Math.min(step, backlog);
      displayRef.current = clampToSafeCharBoundary(
        targetText,
        displayRef.current + step,
      );
      setDisplayText(targetText.slice(0, displayRef.current));
      if (displayRef.current >= targetText.length && tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    };

    if (displayRef.current >= targetText.length) {
      setDisplayText(targetText);
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
