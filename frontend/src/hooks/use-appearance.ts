import { swallow } from "@/core/utils/log";
import { useCallback, useEffect, useState } from "react";

/**
 * Appearance preferences:
 *
 *   - cornerScale: global multiplier on all radius tokens (0.5–1.5).
 *       0.5 = crisp, 1 = default, 1.5 = pill / friendly.
 *   - density: "comfortable" (15px base) or "compact" (14px, tighter rows).
 *
 * Persisted to localStorage and applied as data-* attributes on <html>
 * so any Tailwind/CSS rule can react via [data-corner-scale] / [data-density].
 */

export type CornerScale = 0.5 | 0.75 | 1 | 1.25 | 1.5;
export type Density = "comfortable" | "compact";

const CORNER_KEY = "octopus-corner-scale";
const DENSITY_KEY = "octopus-density";

const DEFAULT_CORNER: CornerScale = 1;
const DEFAULT_DENSITY: Density = "comfortable";

function readCorner(): CornerScale {
  if (typeof window === "undefined") return DEFAULT_CORNER;
  const raw = window.localStorage.getItem(CORNER_KEY);
  const v = raw != null ? Number(raw) : NaN;
  return ([0.5, 0.75, 1, 1.25, 1.5] as const).includes(v as CornerScale)
    ? (v as CornerScale)
    : DEFAULT_CORNER;
}

function readDensity(): Density {
  if (typeof window === "undefined") return DEFAULT_DENSITY;
  const raw = window.localStorage.getItem(DENSITY_KEY);
  return raw === "compact" ? "compact" : DEFAULT_DENSITY;
}

function applyCorner(scale: CornerScale) {
  const root = document.documentElement;
  root.style.setProperty("--corner-radius-scale", String(scale));
  root.dataset.cornerScale = String(scale);
}

function applyDensity(density: Density) {
  const root = document.documentElement;
  if (density === "compact") root.dataset.density = "compact";
  else delete root.dataset.density;
}

export function useAppearance() {
  const [cornerScale, setCornerScaleState] = useState<CornerScale>(DEFAULT_CORNER);
  const [density, setDensityState] = useState<Density>(DEFAULT_DENSITY);

  useEffect(() => {
    const c = readCorner();
    const d = readDensity();
    setCornerScaleState(c);
    setDensityState(d);
    applyCorner(c);
    applyDensity(d);
  }, []);

  const setCornerScale = useCallback((scale: CornerScale) => {
    setCornerScaleState(scale);
    applyCorner(scale);
    try {
      window.localStorage.setItem(CORNER_KEY, String(scale));
    } catch (e) { swallow(e, "storage"); }
  }, []);

  const setDensity = useCallback((d: Density) => {
    setDensityState(d);
    applyDensity(d);
    try {
      window.localStorage.setItem(DENSITY_KEY, d);
    } catch (e) { swallow(e, "storage"); }
  }, []);

  return { cornerScale, density, setCornerScale, setDensity };
}

/** Mount once at app root to hydrate appearance from storage before first paint. */
export function AppearanceBootstrap() {
  useAppearance();
  return null;
}
