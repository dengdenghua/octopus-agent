import { useState } from "react";
import { ChevronDownIcon, ChevronRightIcon, BrainIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ReasoningItem } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";
import { stripTraceLabelPrefixes } from "@/components/workspace/messages/trace-labels";

/**
 * Collapsible "thinking" block for the agent's chain-of-thought.
 *
 * Default-collapsed: reasoning is supplementary context, not the
 * primary output, so we summarize it with the first non-empty line and
 * let the user expand for the full text. Visually muted (smaller font,
 * muted color, dashed left border) to keep it from competing with
 * agent messages.
 *
 * The first line of `content` (or the first `summary` entry as a
 * fallback) is shown as the collapsed-state preview; this is enough
 * for the user to skim without expanding every block.
 */
export function ReasoningView({ item }: { item: ReasoningItem }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const content = stripTraceLabelPrefixes(item.content);
  const firstLine =
    stripTraceLabelPrefixes(item.summary && item.summary.find(Boolean)) ||
    content.split(/\r?\n/).find(line => line.trim().length > 0) ||
    "";
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-border/60 bg-muted/30",
        "px-3 py-2 text-xs text-muted-foreground",
      )}
      data-status={item.status}
    >
      <button
        type="button"
        onClick={() => setOpen(prev => !prev)}
        className="flex w-full items-center gap-1.5 text-left transition-colors hover:text-foreground"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDownIcon className="size-3.5 shrink-0" />
        ) : (
          <ChevronRightIcon className="size-3.5 shrink-0" />
        )}
        <BrainIcon className="size-3.5 shrink-0 opacity-70" />
        <span className="font-medium">{t.realtimeItems.reasoning.label}</span>
        {!open && firstLine && (
          <span className="ml-2 truncate font-normal opacity-70">
            {firstLine}
          </span>
        )}
      </button>
      {open && (
        <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-xs leading-relaxed">
          {content || (
            <span className="italic opacity-60">
              {t.realtimeItems.reasoning.empty}
            </span>
          )}
        </pre>
      )}
    </div>
  );
}
