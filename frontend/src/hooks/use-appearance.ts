import { swallow } from "@/core/utils/log";
import { useCallback, useEffect, useState } from "react";

/**
 * Appearance preferences:
 *
 *   - cornerScale: global multiplier on all radius tokens (0.5–1.5).
 *       0.5 = crisp, 1 = default, 1.5 = pill / friendly.
 *   - density: global base font size and spacing scale for information
 *       density, from relaxed to ultra-dense.
 *   - materialTheme: "standard" or "liquid". This layers a glass material
 *       over the active color theme instead of replacing light/dark/apple.
 *   - materialIntensity: liquid-only tuning for blur, translucency,
 *       field strength, edge highlights, and optical depth.
 *
 * Persisted to localStorage and applied as data-* attributes on <html>
 * so any Tailwind/CSS rule can react via data attributes.
 */

export type CornerScale = 0.5 | 0.75 | 1 | 1.25 | 1.5;
export type Density =
  | "relaxed"
  | "comfortable"
  | "compact"
  | "dense"
  | "ultradense";
export type MaterialTheme = "standard" | "liquid";
export type MaterialIntensity =
  | "crystal"
  | "clear"
  | "balanced"
  | "deep"
  | "frosted";

const CORNER_KEY = "octopus-corner-scale";
const DENSITY_KEY = "octopus-density";
const MATERIAL_THEME_KEY = "octopus-material-theme";
const MATERIAL_INTENSITY_KEY = "octopus-material-intensity";
const APPEARANCE_CHANGE_EVENT = "octopus:appearance-change";

const DEFAULT_CORNER: CornerScale = 1;
const DEFAULT_DENSITY: Density = "comfortable";
const DEFAULT_MATERIAL_THEME: MaterialTheme = "standard";
const DEFAULT_MATERIAL_INTENSITY: MaterialIntensity = "balanced";
const DENSITY_TOKENS: Record<
  Density,
  {
    baseFontSize: string;
    cardMinHeight: string;
    gap: string;
    headerPaddingX: string;
    headerPaddingY: string;
    pagePadding: string;
    panelPadding: string;
    rowPaddingX: string;
    rowPaddingY: string;
  }
> = {
  relaxed: {
    baseFontSize: "16px",
    rowPaddingY: "calc(var(--spacing) * 1.75)",
    rowPaddingX: "calc(var(--spacing) * 3)",
    gap: "calc(var(--spacing) * 5)",
    pagePadding: "calc(var(--spacing) * 5)",
    panelPadding: "calc(var(--spacing) * 5)",
    headerPaddingY: "calc(var(--spacing) * 3.5)",
    headerPaddingX: "calc(var(--spacing) * 5.5)",
    cardMinHeight: "204px",
  },
  comfortable: {
    baseFontSize: "15px",
    rowPaddingY: "calc(var(--spacing) * 1.5)",
    rowPaddingX: "calc(var(--spacing) * 2.5)",
    gap: "calc(var(--spacing) * 4)",
    pagePadding: "calc(var(--spacing) * 4)",
    panelPadding: "calc(var(--spacing) * 4)",
    headerPaddingY: "calc(var(--spacing) * 3)",
    headerPaddingX: "calc(var(--spacing) * 5)",
    cardMinHeight: "184px",
  },
  compact: {
    baseFontSize: "14px",
    rowPaddingY: "calc(var(--spacing) * 1.25)",
    rowPaddingX: "calc(var(--spacing) * 2)",
    gap: "calc(var(--spacing) * 3)",
    pagePadding: "calc(var(--spacing) * 3.5)",
    panelPadding: "calc(var(--spacing) * 3.5)",
    headerPaddingY: "calc(var(--spacing) * 2.5)",
    headerPaddingX: "calc(var(--spacing) * 4)",
    cardMinHeight: "168px",
  },
  dense: {
    baseFontSize: "13px",
    rowPaddingY: "calc(var(--spacing) * 1)",
    rowPaddingX: "calc(var(--spacing) * 1.75)",
    gap: "calc(var(--spacing) * 2.5)",
    pagePadding: "calc(var(--spacing) * 3)",
    panelPadding: "calc(var(--spacing) * 3)",
    headerPaddingY: "calc(var(--spacing) * 2)",
    headerPaddingX: "calc(var(--spacing) * 3.5)",
    cardMinHeight: "152px",
  },
  ultradense: {
    baseFontSize: "12.5px",
    rowPaddingY: "calc(var(--spacing) * 0.75)",
    rowPaddingX: "calc(var(--spacing) * 1.5)",
    gap: "calc(var(--spacing) * 2)",
    pagePadding: "calc(var(--spacing) * 2.5)",
    panelPadding: "calc(var(--spacing) * 2.5)",
    headerPaddingY: "calc(var(--spacing) * 1.75)",
    headerPaddingX: "calc(var(--spacing) * 3)",
    cardMinHeight: "136px",
  },
};

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
  return isDensity(raw) ? raw : DEFAULT_DENSITY;
}

function isDensity(value: string | null): value is Density {
  return (
    value === "relaxed" ||
    value === "comfortable" ||
    value === "compact" ||
    value === "dense" ||
    value === "ultradense"
  );
}

function readMaterialTheme(): MaterialTheme {
  if (typeof window === "undefined") return DEFAULT_MATERIAL_THEME;
  const raw = window.localStorage.getItem(MATERIAL_THEME_KEY);
  return raw === "liquid" ? "liquid" : DEFAULT_MATERIAL_THEME;
}

function readMaterialIntensity(): MaterialIntensity {
  if (typeof window === "undefined") return DEFAULT_MATERIAL_INTENSITY;
  const raw = window.localStorage.getItem(MATERIAL_INTENSITY_KEY);
  return isMaterialIntensity(raw) ? raw : DEFAULT_MATERIAL_INTENSITY;
}

function isMaterialIntensity(value: string | null): value is MaterialIntensity {
  return (
    value === "crystal" ||
    value === "clear" ||
    value === "balanced" ||
    value === "deep" ||
    value === "frosted"
  );
}

function applyCorner(scale: CornerScale) {
  const root = document.documentElement;
  root.style.setProperty("--corner-radius-scale", String(scale));
  root.dataset.cornerScale = String(scale);
}

function applyDensity(density: Density) {
  const root = document.documentElement;
  const tokens = DENSITY_TOKENS[density];
  root.style.setProperty("--density-base-font-size", tokens.baseFontSize);
  root.style.setProperty("--density-row-padding-y", tokens.rowPaddingY);
  root.style.setProperty("--density-row-padding-x", tokens.rowPaddingX);
  root.style.setProperty("--density-gap", tokens.gap);
  root.style.setProperty("--density-page-padding", tokens.pagePadding);
  root.style.setProperty("--density-panel-padding", tokens.panelPadding);
  root.style.setProperty("--density-header-padding-y", tokens.headerPaddingY);
  root.style.setProperty("--density-header-padding-x", tokens.headerPaddingX);
  root.style.setProperty("--density-card-min-height", tokens.cardMinHeight);
  if (density === DEFAULT_DENSITY) delete root.dataset.density;
  else root.dataset.density = density;
}

function applyMaterialTheme(
  theme: MaterialTheme,
  intensity: MaterialIntensity,
) {
  const root = document.documentElement;
  if (theme === "liquid") {
    root.dataset.materialTheme = "liquid";
    root.dataset.materialIntensity = intensity;
  } else {
    delete root.dataset.materialTheme;
    delete root.dataset.materialIntensity;
  }
}

function emitAppearanceChange() {
  window.dispatchEvent(new Event(APPEARANCE_CHANGE_EVENT));
}

export function useAppearance() {
  const [cornerScale, setCornerScaleState] =
    useState<CornerScale>(DEFAULT_CORNER);
  const [density, setDensityState] = useState<Density>(DEFAULT_DENSITY);
  const [materialTheme, setMaterialThemeState] = useState<MaterialTheme>(
    DEFAULT_MATERIAL_THEME,
  );
  const [materialIntensity, setMaterialIntensityState] =
    useState<MaterialIntensity>(DEFAULT_MATERIAL_INTENSITY);

  useEffect(() => {
    const syncFromStorage = () => {
      const c = readCorner();
      const d = readDensity();
      const m = readMaterialTheme();
      const i = readMaterialIntensity();
      setCornerScaleState(c);
      setDensityState(d);
      setMaterialThemeState(m);
      setMaterialIntensityState(i);
      applyCorner(c);
      applyDensity(d);
      applyMaterialTheme(m, i);
    };

    syncFromStorage();
    window.addEventListener(APPEARANCE_CHANGE_EVENT, syncFromStorage);
    window.addEventListener("storage", syncFromStorage);
    return () => {
      window.removeEventListener(APPEARANCE_CHANGE_EVENT, syncFromStorage);
      window.removeEventListener("storage", syncFromStorage);
    };
  }, []);

  const setCornerScale = useCallback((scale: CornerScale) => {
    setCornerScaleState(scale);
    applyCorner(scale);
    try {
      window.localStorage.setItem(CORNER_KEY, String(scale));
    } catch (e) {
      swallow(e, "storage");
    }
    emitAppearanceChange();
  }, []);

  const setDensity = useCallback((d: Density) => {
    setDensityState(d);
    applyDensity(d);
    try {
      window.localStorage.setItem(DENSITY_KEY, d);
    } catch (e) {
      swallow(e, "storage");
    }
    emitAppearanceChange();
  }, []);

  const setMaterialTheme = useCallback((theme: MaterialTheme) => {
    setMaterialThemeState(theme);
    const intensity = readMaterialIntensity();
    setMaterialIntensityState(intensity);
    applyMaterialTheme(theme, intensity);
    try {
      window.localStorage.setItem(MATERIAL_THEME_KEY, theme);
    } catch (e) {
      swallow(e, "storage");
    }
    emitAppearanceChange();
  }, []);

  const setMaterialIntensity = useCallback((intensity: MaterialIntensity) => {
    setMaterialIntensityState(intensity);
    const theme = readMaterialTheme();
    applyMaterialTheme(theme, intensity);
    try {
      window.localStorage.setItem(MATERIAL_INTENSITY_KEY, intensity);
    } catch (e) {
      swallow(e, "storage");
    }
    emitAppearanceChange();
  }, []);

  return {
    cornerScale,
    density,
    materialTheme,
    materialIntensity,
    setCornerScale,
    setDensity,
    setMaterialTheme,
    setMaterialIntensity,
  };
}

/** Mount once at app root to hydrate appearance from storage before first paint. */
export function AppearanceBootstrap() {
  useAppearance();
  return null;
}
