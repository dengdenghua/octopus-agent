
import { UserCircleIcon, UsersIcon } from "lucide-react";
import { useMemo } from "react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";

export type TeamMode = "chat" | "cowork";

export type LegacyTeamMode =
  | "group_chat"
  | "free"
  | "free_chat"
  | "swarm"
  | "debate"
  | "pipeline";

export function normalizeTeamMode(
  value: TeamMode | LegacyTeamMode | string | null | undefined,
): TeamMode {
  // ``free`` was a placeholder UI-only mode that the backend never
  // distinguished from ``chat``. It was removed 2026-06-04; legacy
  // threads / persisted picker state with ``free`` collapse back to
  // ``chat``, which is what the backend always treated them as.
  if (value === "chat" || value === "group_chat") return "chat";
  if (value === "free" || value === "free_chat") return "chat";
  if (value === "cowork" || value === "swarm" || value === "debate" || value === "pipeline") {
    return "cowork";
  }
  return "chat";
}

const TEAM_MODES: {
  key: TeamMode;
  icon: typeof UsersIcon;
  activeColor: string;
  activeIconColor: string;
}[] = [
  {
    key: "chat",
    icon: UserCircleIcon,
    activeColor: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
    activeIconColor: "text-emerald-600 dark:text-emerald-400",
  },
  {
    key: "cowork",
    icon: UsersIcon,
    activeColor: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
    activeIconColor: "text-blue-600 dark:text-blue-400",
  },
];

export function TeamModePicker({
  value,
  onChange,
  className,
}: {
  value: TeamMode;
  onChange: (mode: TeamMode) => void;
  className?: string;
}) {
  const { t } = useI18n();

  const activeIndex = useMemo(
    () => TEAM_MODES.findIndex((m) => m.key === value),
    [value],
  );

  return (
    <div className={cn("relative flex items-center rounded-full bg-muted/50 p-[3px] ring-1 ring-border/20", className)}>
      <div
        className="absolute top-[3px] bottom-[3px] rounded-full bg-background shadow-sm ring-1 ring-border/40 transition-all duration-300 ease-out"
        style={{
          left: `calc(${activeIndex} * (100% - 4px) / 2 + 2px)`,
          width: `calc((100% - 4px) / 2)`,
        }}
      />
      {TEAM_MODES.map((mode) => {
        const Icon = mode.icon;
        const active = value === mode.key;
        const label = t.teamMode[mode.key];
        return (
          <button
            key={mode.key}
            type="button"
            onClick={() => onChange(mode.key)}
            className={cn(
              "relative z-10 flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors duration-200",
              active
                ? mode.activeColor
                : "text-muted-foreground/60 hover:text-muted-foreground",
            )}
          >
            <Icon className={cn("size-3.5 transition-colors duration-200", active && mode.activeIconColor)} />
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function TeamModeDescription({
  mode,
  className,
}: {
  mode: TeamMode;
  className?: string;
}) {
  const { t } = useI18n();
  const descKey = `${mode}Description` as keyof typeof t.teamMode;
  const desc = t.teamMode[descKey];

  return (
    <p className={cn("text-muted-foreground text-xs", className)}>
      {desc}
    </p>
  );
}
