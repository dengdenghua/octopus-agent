import type { BaseStream } from "@/core/api/use-stream-types";
import { useEffect } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { useThreadChat } from "./chats";
import { FlipDisplay } from "./flip-display";

export function ThreadTitle({
  className,
  threadId,
  thread,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
}) {
  const { t } = useI18n();
  const { isNewThread } = useThreadChat();
  useEffect(() => {
    let _title = t.pages.untitled;

    if (thread.values?.title) {
      _title = thread.values.title;
    } else if (isNewThread) {
      _title = t.pages.newChat;
    }
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${t.pages.appName}`;
    } else {
      document.title = `${_title} - ${t.pages.appName}`;
    }
  }, [
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    t.pages.appName,
    thread.isThreadLoading,
    thread.values,
  ]);

  // Fallback: show a muted placeholder on new/untitled threads so the
  // header has an anchor on the left side (otherwise justify-between
  // throws the right-side actions hard to one edge and the header looks
  // Implementation note.
  const fallback = isNewThread
    ? t.pages.newChat
    : thread.values?.title
      ? null
      : t.pages.untitled;
  const displayTitle = thread.values?.title ?? fallback;
  if (!displayTitle) return null;
  const isPlaceholder = !thread.values?.title;
  return (
    <FlipDisplay
      uniqueKey={threadId}
      className={cn(
        "max-w-[min(48vw,38rem)] truncate text-sm font-medium",
        isPlaceholder
          ? "text-muted-foreground/70 italic"
          : "text-foreground/80",
        className,
      )}
    >
      {displayTitle}
    </FlipDisplay>
  );
}
