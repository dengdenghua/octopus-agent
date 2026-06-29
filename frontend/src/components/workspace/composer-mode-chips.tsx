/**
 * Composer (codex) mode chips — the "+" menu turn-shaping modes shown as
 * deletable chips beside the permission button:
 *   - plan → map     - spec → clipboard-check     - goal → target
 *
 * NOTE: "project" is NOT here — a project isn't a composer mode, it's a *group*
 * collaboration mode (chat/cluster/swarm/project, see cowork). It's selected via
 * the group's mode picker, not the composer "+" menu.
 *
 * Self-contained (own zh/en labels, decoupled from the concurrently-edited
 * locale bundle). Two drop-ins for the composer: ComposerModeMenuItems inside
 * the "+" DropdownMenuContent, and ComposerModeChips next to PermissionIndicator.
 */
import {
  ClipboardCheckIcon,
  MapIcon,
  TargetIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";

import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export type ComposerMode = "plan" | "spec" | "goal";

interface ModeMeta {
  icon: LucideIcon;
  zh: string;
  en: string;
}

// Order = how they appear in the "+" menu.
export const COMPOSER_MODES: Record<ComposerMode, ModeMeta> = {
  plan: { icon: MapIcon, zh: "规划", en: "Plan" },
  spec: { icon: ClipboardCheckIcon, zh: "规格", en: "Spec" },
  goal: { icon: TargetIcon, zh: "目标", en: "Goal" },
};

const MODE_ORDER: ComposerMode[] = ["plan", "spec", "goal"];

function useLabel() {
  const { locale } = useI18n();
  const zh = (locale || "en").slice(0, 2).toLowerCase() === "zh";
  return (mode: ComposerMode) => (zh ? COMPOSER_MODES[mode].zh : COMPOSER_MODES[mode].en);
}

/** The four mode entries for the composer's "+" dropdown menu. */
export function ComposerModeMenuItems({
  onSelect,
}: {
  onSelect: (mode: ComposerMode) => void;
}) {
  const label = useLabel();
  return (
    <>
      {MODE_ORDER.map((mode) => {
        const Icon = COMPOSER_MODES[mode].icon;
        return (
          <DropdownMenuItem
            key={mode}
            data-testid={`composer-mode-${mode}`}
            onClick={() => onSelect(mode)}
            className="gap-2 rounded-md text-[13px]"
          >
            <Icon className="size-4" />
            {label(mode)}
          </DropdownMenuItem>
        );
      })}
    </>
  );
}

/** Deletable chips for the active modes, rendered beside the permission button. */
export function ComposerModeChips({
  active,
  onRemove,
  className,
}: {
  active: ComposerMode[];
  onRemove: (mode: ComposerMode) => void;
  className?: string;
}) {
  const label = useLabel();
  if (active.length === 0) return null;
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {active.map((mode) => {
        const Icon = COMPOSER_MODES[mode].icon;
        return (
          <span
            key={mode}
            data-testid={`composer-chip-${mode}`}
            className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/50 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground"
            title={label(mode)}
          >
            <Icon className="size-3" />
            <span className="max-w-20 truncate">{label(mode)}</span>
            <button
              type="button"
              aria-label={`remove ${mode}`}
              data-testid={`composer-chip-remove-${mode}`}
              onClick={() => onRemove(mode)}
              className="ml-0.5 rounded-sm text-current/70 hover:text-current"
            >
              <XIcon className="size-3" />
            </button>
          </span>
        );
      })}
    </div>
  );
}
