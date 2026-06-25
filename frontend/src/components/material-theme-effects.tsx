import { LiquidGlassField } from "@/components/browser/liquid-glass-field";
import { useAppearance } from "@/hooks/use-appearance";

export function MaterialThemeEffects() {
  const { materialTheme } = useAppearance();

  if (materialTheme !== "liquid") return null;

  return (
    <div className="octo-global-liquid-field" aria-hidden>
      <LiquidGlassField />
    </div>
  );
}
