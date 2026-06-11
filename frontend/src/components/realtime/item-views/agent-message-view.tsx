import { MessageResponse } from "@/components/ai-elements/message";
import { cn } from "@/lib/utils";
import type { AgentMessageItem } from "@/core/realtime";

/**
 * Assistant-side chat bubble for streamed agent text.
 *
 * Codex-flat style: no border, no background — a left-aligned prose block
 * that reads as body copy. Markdown is rendered via Streamdown (the
 * repo's existing renderer used by the workspace chat) so code fences,
 * lists and inline formatting all come out consistent with the rest of
 * the app. While the item is still streaming (status === "inProgress")
 * and no text has arrived yet, a muted placeholder stands in for the
 * cursor so the user sees *something* happening.
 */
export function AgentMessageView({ item }: { item: AgentMessageItem }) {
  const streaming = item.status === "inProgress";
  if (!item.text) {
    return (
      <div
        className="w-full text-sm text-muted-foreground"
        data-status={item.status}
      >
        {streaming ? <span className="animate-pulse">…</span> : null}
      </div>
    );
  }
  return (
    <div
      className={cn(
        "w-full min-w-0 text-sm leading-relaxed text-foreground",
        "prose prose-sm max-w-none",
        "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
      )}
      data-status={item.status}
    >
      <MessageResponse className="prose-sm">{item.text}</MessageResponse>
    </div>
  );
}
