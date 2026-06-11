import { CheckCircle2Icon, PlayIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";

interface Props {
  onReplay?: () => void;
  className?: string;
}

export function TaskCompleteBanner({ onReplay, className }: Props) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs dark:border-emerald-900/50 dark:bg-emerald-950/30",
        className,
      )}
    >
      <CheckCircle2Icon className="size-4 text-emerald-600 dark:text-emerald-400" />
      <span className="flex-1 text-emerald-700 dark:text-emerald-300">
        {t.swarmPanel.taskComplete}
      </span>
      {onReplay && (
        <button
          type="button"
          onClick={onReplay}
          className="flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2 py-0.5 text-[11px] text-emerald-700 transition-colors hover:bg-emerald-100 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300"
        >
          <PlayIcon className="size-3" fill="currentColor" />
          {t.swarmPanel.replayTeamWork}
        </button>
      )}
    </div>
  );
}

const EMOJI = ["👍", "👎", "❤️", "😂"] as const;

export function EmojiReactionRow({
  className,
}: {
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {EMOJI.map((e) => (
        <button
          key={e}
          type="button"
          className="flex size-7 items-center justify-center rounded-lg text-sm transition-transform hover:scale-110 hover:bg-muted"
        >
          {e}
        </button>
      ))}
    </div>
  );
}
