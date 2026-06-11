import {
  ClockIcon,
  EyeIcon,
  FileEditIcon,
  LightbulbIcon,
  SearchIcon,
  WrenchIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";

import type { TraceEntry } from "./types";

interface Props {
  entries: TraceEntry[];
  emptyHint?: string;
}

const KIND_ICON = {
  search: SearchIcon,
  read: EyeIcon,
  think: LightbulbIcon,
  write: FileEditIcon,
  tool: WrenchIcon,
};

function hostOf(url: string) {
  try {
    return new URL(url).host;
  } catch (e) {
    swallow(e);
    return url;
  }
}

function formatTime(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function TraceFeed({ entries, emptyHint }: Props) {
  const { t } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [detached, setDetached] = useState(false);
  const orderedEntries = useMemo(
    () => [...entries].sort((a, b) => a.timestamp - b.timestamp),
    [entries],
  );

  // Auto-scroll to bottom unless user detached.
  useEffect(() => {
    if (!detached && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [orderedEntries, detached]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setDetached(!atBottom);
  };

  if (orderedEntries.length === 0) {
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-xs">
        {emptyHint ?? t.swarmPanel.noActivity}
      </div>
    );
  }

  return (
    <div className="relative h-full">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="h-full overflow-auto px-4 py-3"
      >
        <ul className="space-y-2.5">
          {orderedEntries.map((e) => {
            const Icon = KIND_ICON[e.kind];
            return (
              <li key={e.id} className="flex gap-2.5 text-xs">
                <div className="flex w-14 shrink-0 flex-col items-end gap-1 pt-0.5 text-[10px] text-muted-foreground/70">
                  <span>{formatTime(e.timestamp)}</span>
                  <span className="rounded-lg bg-muted p-1 text-muted-foreground">
                    <Icon className="size-3" />
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    {e.faviconEmoji && (
                      <span className="text-sm leading-none">
                        {e.faviconEmoji}
                      </span>
                    )}
                    <span className="truncate text-sm text-foreground">
                      {e.title}
                    </span>
                    {e.url && (
                      <span className="text-muted-foreground/60 truncate text-[10px]">
                        {hostOf(e.url)}
                      </span>
                    )}
                  </div>
                  {e.detail && (
                    <p className="text-muted-foreground mt-0.5 line-clamp-2">
                      {e.detail}
                    </p>
                  )}
                  {e.kind === "tool" && (e.inputPreview || e.outputPreview) && (
                    <div className="mt-1 space-y-1 rounded-lg border border-border/60 bg-muted/20 px-2 py-1.5 font-mono text-[10px] text-muted-foreground">
                      {e.inputPreview && (
                        <div className="line-clamp-2">
                          <span className="text-foreground/70">in </span>
                          {e.inputPreview}
                        </div>
                      )}
                      {e.outputPreview && (
                        <div className="line-clamp-2">
                          <span className="text-foreground/70">out </span>
                          {e.outputPreview}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                {e.kind === "tool" && (
                  <ClockIcon className="mt-1 size-3 shrink-0 text-muted-foreground/40" />
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {detached && (
        <button
          type="button"
          onClick={() => {
            setDetached(false);
            if (scrollRef.current) {
              scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
            }
          }}
          className={cn(
            "absolute right-1/2 bottom-3 translate-x-1/2 rounded-lg",
            "bg-foreground/90 px-3 py-1 text-xs text-background shadow-lg",
            "hover:bg-foreground",
          )}
        >
          {t.swarmPanel.backToLatest}
        </button>
      )}
    </div>
  );
}
