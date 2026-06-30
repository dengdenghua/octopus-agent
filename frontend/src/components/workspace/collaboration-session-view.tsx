import { LinkIcon, ListTodoIcon, MessageSquareIcon, UsersIcon } from "lucide-react";

import { useCollabSession } from "@/core/cowork/hooks";
import type { CollaborationSession } from "@/core/cowork/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { PresenceDots } from "./cowork-collab-bar";
import { TEAM_MODE_META, type TeamMode } from "./team-mode-picker";

type T = ReturnType<typeof useI18n>["t"];

function Stat({
  icon: Icon,
  value,
  label,
}: {
  icon: typeof UsersIcon;
  value: number | string;
  label: string;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] text-muted-foreground"
      title={label}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      <span className="font-medium text-foreground">{value}</span>
    </span>
  );
}

/** Pure render of one unified collaboration session — cowork thread (canonical)
 * plus its linked Team Room surface. Data in, no fetching. */
export function CollaborationSessionView({
  session,
  t,
}: {
  session: CollaborationSession;
  t: T;
}) {
  const modeMeta = TEAM_MODE_META[session.mode as TeamMode] ?? TEAM_MODE_META.chat;
  const ModeIcon = modeMeta.icon;
  return (
    <div
      className="flex flex-col gap-2 rounded-xl border border-border/60 bg-background/70 p-3"
      data-testid="collab-session-view"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span
          className="inline-flex items-center gap-1 rounded-full bg-muted/60 px-2 py-0.5 text-[11px] font-medium text-foreground"
          title={modeMeta.description}
        >
          <ModeIcon className="size-3.5" aria-hidden="true" />
          {modeMeta.label}
        </span>
        <Stat icon={UsersIcon} value={session.roster.length} label={t.coworkCollab.members} />
        <Stat icon={ListTodoIcon} value={session.tasks.length} label={t.coworkCollab.kindTask} />
      </div>

      <PresenceDots members={session.presence} t={t} />

      {session.room_id && (
        <div
          className="flex min-w-0 flex-wrap items-center gap-2 border-t border-border/45 pt-2"
          data-testid="collab-session-room"
        >
          <span
            className="inline-flex items-center gap-1 truncate text-[11px] text-muted-foreground"
            title={session.room_id}
          >
            <LinkIcon className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate font-medium text-foreground">{session.room_id}</span>
          </span>
          <Stat
            icon={UsersIcon}
            value={session.room_participants.length}
            label={t.coworkCollab.members}
          />
          <Stat
            icon={MessageSquareIcon}
            value={session.room_messages.length}
            label={t.coworkCollab.kindEvent}
          />
        </div>
      )}
    </div>
  );
}

/** Live panel: fetches the unified session and renders it. */
export function CollaborationSessionPanel({
  threadId,
  className,
}: {
  threadId: string;
  className?: string;
}) {
  const { t } = useI18n();
  const { data: session } = useCollabSession(threadId);
  if (!session) return null;
  return (
    <div className={cn("w-full", className)}>
      <CollaborationSessionView session={session} t={t} />
    </div>
  );
}
