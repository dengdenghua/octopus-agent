import type { Message } from "@/core/api/types";
import { BookOpenIcon, ChevronDownIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { GroundingSource } from "@/core/realtime/items";
import { cn } from "@/lib/utils";

/**
 * Plain-language "consulted N project docs" chip.
 *
 * Surfaces the codebase grounding the agent actually used this turn — the wiki
 * pages + source chunks folded into its prompt — carried on the AI reply's
 * ``additional_kwargs.grounding``. Collapsed by default (one quiet line); click
 * to expand the exact docs/files. Builds trust that the answer is grounded in
 * the project without dumping retrieval noise into the chat.
 */
export function GroundingChip({ message }: { message: Message }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const sources = useMemo(() => {
    const g = message.additional_kwargs?.grounding;
    if (!Array.isArray(g) || g.length === 0) return null;
    return g as GroundingSource[];
  }, [message.additional_kwargs?.grounding]);
  if (!sources) return null;
  const label = t.message.grounding.label.replace(
    "{count}",
    String(sources.length),
  );
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <BookOpenIcon className="size-3.5 shrink-0" />
        <span className="truncate">{label}</span>
        <ChevronDownIcon
          className={cn(
            "size-3 shrink-0 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <ul className="mt-1.5 flex max-w-md flex-col gap-1 rounded-md border border-border/50 bg-muted/20 p-2 text-xs">
          {sources.map((source, index) => (
            <li
              key={`${source.path}-${index}`}
              className="flex min-w-0 items-center gap-2"
            >
              <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                {source.kind === "doc"
                  ? t.message.grounding.doc
                  : t.message.grounding.source}
              </span>
              <span className="truncate font-medium text-foreground/90">
                {source.title}
              </span>
              <span className="truncate text-muted-foreground/70">
                {source.path}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
