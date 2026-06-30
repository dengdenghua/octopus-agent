import { FileTextIcon, ListTodoIcon, SearchIcon, UsersIcon } from "lucide-react";
import { useState } from "react";

import { useCoworkPresence, useCoworkSearch } from "@/core/cowork/hooks";
import type {
  CoworkMemberPresence,
  CoworkSearchHit,
  CoworkSearchKind,
} from "@/core/cowork/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type T = ReturnType<typeof useI18n>["t"];

const KIND_ICON: Record<CoworkSearchKind, typeof FileTextIcon> = {
  blackboard: FileTextIcon,
  task: ListTodoIcon,
  event: UsersIcon,
};

function kindLabel(kind: CoworkSearchKind, t: T): string {
  if (kind === "blackboard") return t.coworkCollab.kindBlackboard;
  if (kind === "task") return t.coworkCollab.kindTask;
  return t.coworkCollab.kindEvent;
}

/** Compact presence row: online dots + a total-unread badge. Pure — data in. */
export function PresenceDots({
  members,
  seatNames = {},
  t,
}: {
  members: CoworkMemberPresence[];
  seatNames?: Record<string, string>;
  t: T;
}) {
  if (members.length === 0) return null;
  const online = members.filter((m) => m.online).length;
  const unread = members.reduce((sum, m) => sum + (m.unread || 0), 0);
  const shown = members.slice(0, 6);
  const extra = members.length - shown.length;

  return (
    <div className="flex min-w-0 items-center gap-2" data-testid="cowork-presence">
      <div className="flex items-center -space-x-0.5">
        {shown.map((m) => (
          <span
            key={m.member_id}
            title={`${seatNames[m.member_id] ?? m.member_id}${m.online ? ` · ${t.coworkCollab.online}` : ""}`}
            className={cn(
              "relative inline-flex size-2.5 rounded-full ring-2 ring-background",
              m.online ? "bg-emerald-500" : "bg-muted-foreground/35",
            )}
          />
        ))}
        {extra > 0 && (
          <span className="pl-1.5 text-[10px] text-muted-foreground">+{extra}</span>
        )}
      </div>
      <span className="shrink-0 text-[11px] text-muted-foreground">
        {online} {t.coworkCollab.online}
      </span>
      {unread > 0 && (
        <span
          data-testid="cowork-unread-total"
          className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
        >
          {t.coworkCollab.unread(unread)}
        </span>
      )}
    </div>
  );
}

/** Pure results list, grouped visually by per-hit kind. */
export function SearchHitList({ hits, t }: { hits: CoworkSearchHit[]; t: T }) {
  if (hits.length === 0) {
    return (
      <div className="px-1 py-3 text-center text-[11px] text-muted-foreground">
        {t.coworkCollab.noResults}
      </div>
    );
  }
  return (
    <ul className="flex flex-col gap-1" data-testid="cowork-search-results">
      {hits.map((hit, i) => {
        const Icon = KIND_ICON[hit.kind] ?? FileTextIcon;
        return (
          <li
            key={`${hit.kind}-${i}`}
            className="flex min-w-0 items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50"
          >
            <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-xs font-medium text-foreground">
                  {hit.title}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {kindLabel(hit.kind, t)}
                </span>
              </div>
              {hit.snippet && (
                <p className="truncate text-[11px] text-muted-foreground">
                  {hit.snippet}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Cowork group collab bar for the workbench: presence + replayable search. */
export function CoworkCollabBar({
  threadId,
  rosterSeats = [],
  className,
}: {
  threadId: string;
  rosterSeats?: { id: string; name: string }[];
  className?: string;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const presence = useCoworkPresence(threadId);
  const search = useCoworkSearch(threadId, query);

  const seatNames: Record<string, string> = {};
  for (const seat of rosterSeats) seatNames[seat.id] = seat.name;

  const members = presence.data?.members ?? [];
  const trimmed = query.trim();

  return (
    <div
      className={cn(
        "shrink-0 border-b border-border/45 bg-background/60 px-3 py-1.5",
        className,
      )}
      data-testid="cowork-collab-bar"
    >
      <div className="flex items-center justify-between gap-2">
        <PresenceDots members={members} seatNames={seatNames} t={t} />
        <div className="relative w-44 max-w-[55%] shrink-0">
          <SearchIcon className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.coworkCollab.searchPlaceholder}
            aria-label={t.coworkCollab.searchPlaceholder}
            className="h-7 w-full rounded-md border border-border/55 bg-background/70 pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground/70 focus-visible:border-primary/30 focus-visible:outline-none"
          />
        </div>
      </div>
      {trimmed.length > 0 && (
        <div className="mt-1.5 max-h-64 overflow-y-auto">
          {search.isLoading ? (
            <div className="px-1 py-3 text-center text-[11px] text-muted-foreground">
              …
            </div>
          ) : (
            <SearchHitList hits={search.data?.hits ?? []} t={t} />
          )}
        </div>
      )}
    </div>
  );
}
