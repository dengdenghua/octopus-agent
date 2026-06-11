import {
  CheckCircle2Icon,
  CircleIcon,
  CircleSlashIcon,
  Loader2Icon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { TodoListItem } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";

// `TodoEntry` is the per-row shape of `TodoListItem.plan[number]`.
// `@/core/realtime` doesn't re-export it from items.ts, so we derive it
// inline rather than reach past the barrel.
type TodoEntry = TodoListItem["plan"][number];

/**
 * Structured checklist with per-entry status.
 *
 * `pending` — empty circle (subtle).
 * `in_progress` — spinning loader.
 * `completed` — filled check.
 * `blocked` — circle with slash.
 *
 * The optional `explanation` is rendered as a short prefix paragraph
 * so the user knows *why* this list exists (e.g. "Breaking down the
 * migration into review-able chunks").
 */
export function TodoListView({ item }: { item: TodoListItem }) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "rounded-md border border-border/40 bg-muted/20 p-3 text-sm",
      )}
      data-status={item.status}
    >
      <div className="text-[10px] font-medium uppercase tracking-wider text-primary">
        {t.realtimeItems.todo.label}
      </div>
      {item.explanation ? (
        <p className="mt-1 text-xs text-muted-foreground">{item.explanation}</p>
      ) : null}
      <ul className="mt-2 flex flex-col gap-1.5">
        {item.plan.map((entry, idx) => (
          <TodoRow key={idx} entry={entry} />
        ))}
      </ul>
    </div>
  );
}

function TodoRow({ entry }: { entry: TodoEntry }) {
  const Icon = (() => {
    switch (entry.status) {
      case "completed":
        return CheckCircle2Icon;
      case "in_progress":
        return Loader2Icon;
      case "blocked":
        return CircleSlashIcon;
      case "pending":
      default:
        return CircleIcon;
    }
  })();
  const iconClass = (() => {
    switch (entry.status) {
      case "completed":
        return "text-emerald-500";
      case "in_progress":
        return "animate-spin text-primary";
      case "blocked":
        return "text-amber-500";
      case "pending":
      default:
        return "text-muted-foreground/60";
    }
  })();
  const textClass = (() => {
    switch (entry.status) {
      case "completed":
        return "text-muted-foreground line-through decoration-muted-foreground/40";
      case "in_progress":
        return "text-foreground font-medium";
      case "blocked":
        return "text-amber-700 dark:text-amber-400";
      default:
        return "text-foreground";
    }
  })();
  return (
    <li className="flex items-start gap-2">
      <Icon className={cn("mt-0.5 size-3.5 shrink-0", iconClass)} />
      <span className={cn("flex-1 text-sm leading-snug", textClass)}>
        {entry.title}
      </span>
    </li>
  );
}
