import { LiquidGlassField } from "./browser/liquid-glass-field";

/**
 * Mounts the global liquid-glass light field once at app root.
 *
 * The field renders a fixed, pointer-reactive WebGL/canvas caustic layer
 * behind all glass surfaces so panels read as a continuous liquid material
 * rather than isolated frosted cards. It is gated to the liquid material
 * theme via CSS (`octo-global-liquid-field`), so mounting it unconditionally
 * is safe: it stays hidden for the standard theme and respects
 * `prefers-reduced-motion` inside the field itself.
 */
export function MaterialThemeEffects() {
  return (
    <div aria-hidden className="octo-global-liquid-field">
      <LiquidGlassField />
    </div>
  );
}
