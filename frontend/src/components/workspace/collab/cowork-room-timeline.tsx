import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link2Icon, PinIcon, SmilePlusIcon } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { MemberProfilePopover } from "@/components/workspace/member-profile-popover";
import type {
  CoworkRoomEntityRef,
  CoworkRoomMessage,
  CoworkRoomParticipant,
  CoworkRoomReplyReference,
} from "@/core/cowork";
import { formatCompactRelativeTimestamp } from "@/core/utils/datetime";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

import {
  CoworkRoomMessageActions,
  type CoworkRoomMessageActionsProps,
} from "./cowork-room-message-actions";
import { AddAnnotationButton, AnnotationThread } from "./annotations";
import { useOptionalCollab } from "./collab-provider";
import {
  CoworkRoomSystemCard,
  getCoworkRoomSystemCard,
  isCoworkRoomSystemMessage,
} from "./cowork-room-system-card";

export type CoworkRoomMessageActionOptions = Omit<
  CoworkRoomMessageActionsProps,
  "message"
>;

export interface CoworkRoomTimelineProps {
  messages: CoworkRoomMessage[];
  participants?: CoworkRoomParticipant[];
  currentParticipantId?: string | null;
  messageActions?: CoworkRoomMessageActionOptions | false;
  onEntityClick?: (entity: CoworkRoomEntityRef) => void;
  emptyLabel?: ReactNode;
  className?: string;
}

export interface CoworkRoomTimelineEntryProps {
  message: CoworkRoomMessage;
  participants?: CoworkRoomParticipant[];
  currentParticipantId?: string | null;
  messageActions?: CoworkRoomMessageActionOptions | false;
  onEntityClick?: (entity: CoworkRoomEntityRef) => void;
  className?: string;
}

/**
 * Remove canonical-thread mirrors and repeated producer messages before room
 * events are mixed into the main conversation timeline. Project OS cards use
 * their own `project-action:*` source ids, so they remain visible.
 */
export function dedupeCoworkRoomMessages(
  messages: readonly CoworkRoomMessage[],
): CoworkRoomMessage[] {
  const seenSourceIds = new Set<string>();
  return messages.filter((message) => {
    const sourceId = message.metadata?.source_message_id?.trim() ?? "";
    if (!sourceId) return true;
    if (sourceId.startsWith("thread:")) return false;
    if (seenSourceIds.has(sourceId)) return false;
    seenSourceIds.add(sourceId);
    return true;
  });
}

function participantId(participant: CoworkRoomParticipant): string {
  for (const candidate of [
    participant.id,
    participant.participant_id,
    participant.name,
  ]) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
}

function participantLabel(
  participant: CoworkRoomParticipant | undefined,
  fallback: string,
): string {
  for (const candidate of [participant?.display_name, participant?.name]) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return fallback;
}

function initials(label: string): string {
  const normalized = label.trim();
  if (!normalized) return "?";
  return normalized
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function renderMessageText(
  text: string,
  participants: Map<string, CoworkRoomParticipant>,
): ReactNode {
  const tokens = text.split(/(@agent:[\w.-]+|@[\p{L}\p{N}_.-]+)/gu);
  return tokens.map((token, index) => {
    if (!token.startsWith("@")) return <Fragment key={index}>{token}</Fragment>;
    const agentId = token.startsWith("@agent:")
      ? token.slice("@agent:".length)
      : "";
    const label = agentId
      ? `@${participantLabel(participants.get(agentId), agentId)}`
      : token;
    return (
      <span
        key={index}
        title={agentId ? token : undefined}
        className="rounded bg-primary/10 px-0.5 font-medium text-primary"
      >
        {label}
      </span>
    );
  });
}

function EntityReferences({
  refs,
  onEntityClick,
}: {
  refs: CoworkRoomEntityRef[];
  onEntityClick?: (entity: CoworkRoomEntityRef) => void;
}) {
  if (refs.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {refs.map((ref, index) => {
        const label = ref.label || ref.id;
        return onEntityClick ? (
          <button
            type="button"
            key={`${ref.kind}:${ref.id}:${index}`}
            className="inline-flex max-w-56 items-center gap-1 truncate rounded-md border border-border-subtle bg-background/70 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground outline-none hover:border-primary/30 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onEntityClick(ref)}
          >
            <Link2Icon className="size-2.5 shrink-0" />
            <span className="truncate">{label}</span>
          </button>
        ) : (
          <span
            key={`${ref.kind}:${ref.id}:${index}`}
            className="inline-flex max-w-56 items-center gap-1 truncate rounded-md border border-border-subtle bg-background/70 px-1.5 py-0.5 text-[10px] text-muted-foreground"
          >
            <Link2Icon className="size-2.5 shrink-0" />
            <span className="truncate">{label}</span>
          </span>
        );
      })}
    </div>
  );
}

function ReplyReference({
  reply,
  participantById,
}: {
  reply: CoworkRoomReplyReference;
  participantById: Map<string, CoworkRoomParticipant>;
}) {
  const author =
    reply.display_name?.trim() ||
    (reply.participant_id
      ? participantLabel(
          participantById.get(reply.participant_id),
          reply.participant_id,
        )
      : "原消息");
  const preview = reply.text?.replace(/\s+/g, " ").trim();
  if (!preview && !reply.seq) return null;
  return (
    <div className="mb-2 flex max-w-full items-start gap-1.5 rounded-md border-l-2 border-primary/35 bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
      <span className="shrink-0 font-medium text-foreground/70">
        回复 {author}
      </span>
      {reply.seq ? (
        <span className="shrink-0 text-muted-foreground/70">
          · #{reply.seq}
        </span>
      ) : null}
      {preview ? <span className="min-w-0 truncate">{preview}</span> : null}
    </div>
  );
}

function buildParticipantMap(participants: CoworkRoomParticipant[]) {
  const next = new Map<string, CoworkRoomParticipant>();
  for (const participant of participants) {
    const id = participantId(participant);
    if (id) next.set(id, participant);
  }
  return next;
}

function CoworkRoomTimelineEntryContent({
  message,
  participantById,
  currentParticipantId,
  messageActions,
  onEntityClick,
  className,
}: Omit<CoworkRoomTimelineEntryProps, "participants"> & {
  participantById: Map<string, CoworkRoomParticipant>;
}) {
  const collab = useOptionalCollab();
  const [showAnnotations, setShowAnnotations] = useState(false);
  const [showReactionPicker, setShowReactionPicker] = useState(false);
  const refs = message.metadata?.entity_refs ?? [];
  if (isCoworkRoomSystemMessage(message)) {
    const card = getCoworkRoomSystemCard(message) ?? {
      type: "project_update",
      title: message.text,
    };
    return (
      <div data-message-seq={message.seq} className={cn("py-1", className)}>
        <CoworkRoomSystemCard
          card={card}
          entityRefs={refs}
          onEntityClick={onEntityClick}
        />
      </div>
    );
  }

  const participant = message.participant_id
    ? participantById.get(message.participant_id)
    : undefined;
  const displayName =
    message.display_name?.trim() ||
    participantLabel(participant, message.participant_id || "协作成员");
  const own = Boolean(
    currentParticipantId && message.participant_id === currentParticipantId,
  );
  const avatarUrl =
    typeof participant?.avatar_url === "string"
      ? participant.avatar_url
      : undefined;
  const annotationMessageId =
    message.metadata?.source_message_id ||
    `room:${message.room_id ?? "room"}:${message.seq}`;
  const messageAnnotations =
    collab?.annotations.filter(
      (annotation) => annotation.message_id === annotationMessageId,
    ) ?? [];
  const annotationCount = messageAnnotations.length;
  const messageReactions =
    collab?.messageReactions.filter(
      (reaction) => reaction.message_id === annotationMessageId,
    ) ?? [];
  const reactingParticipantId = collab?.currentUser?.id;
  const isPinned = Boolean(
    collab?.pinnedMessages.some(
      (pin) => pin.message_id === annotationMessageId,
    ),
  );

  return (
    <article
      data-message-seq={message.seq}
      className={cn(
        "group/msg flex items-start gap-2",
        own && "flex-row-reverse",
        className,
      )}
    >
      <MemberProfilePopover
        name={displayName}
        avatar={
          <Avatar className="size-14 shrink-0 rounded-2xl">
            {avatarUrl ? (
              <AvatarImage src={avatarUrl} alt={displayName} />
            ) : null}
            <AvatarFallback className="rounded-2xl text-lg font-semibold">
              {initials(displayName)}
            </AvatarFallback>
          </Avatar>
        }
        roleLabel={participant?.kind === "agent" ? "AI 成员" : "协作成员"}
        presenceLabel={own ? "当前视角" : "参与对话"}
        summary={
          participant?.description?.trim() ||
          (participant?.kind === "agent"
            ? "正在参与当前协作。"
            : "该成员正在参与当前对话。")
        }
        trigger={
          <button
            type="button"
            className="mt-0.5 shrink-0 rounded-lg outline-none transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`${displayName} · 查看成员信息`}
          >
            <Avatar className="size-8 rounded-lg">
              {avatarUrl ? (
                <AvatarImage src={avatarUrl} alt={displayName} />
              ) : null}
              <AvatarFallback className="rounded-lg text-[10px] font-semibold">
                {initials(displayName)}
              </AvatarFallback>
            </Avatar>
          </button>
        }
      />
      <div
        className={cn(
          "flex min-w-0 max-w-[min(78%,42rem)] flex-col items-start",
          own && "items-end text-right",
        )}
      >
        <div
          className={cn(
            "mb-1 flex items-center gap-1.5 text-[11px] text-muted-foreground",
            own && "flex-row-reverse",
          )}
        >
          <span className="truncate font-medium text-foreground/80">
            {displayName}
          </span>
          {message.ts ? (
            <time dateTime={message.ts}>
              {formatCompactRelativeTimestamp(message.ts)}
            </time>
          ) : null}
        </div>
        <div
          className={cn(
            "rounded-2xl rounded-tl-md border border-border-subtle bg-card px-3 py-2 text-left shadow-[var(--shadow-xs)]",
            own &&
              "rounded-tl-2xl rounded-tr-md border-primary/15 bg-primary/[0.07]",
          )}
        >
          {message.metadata?.reply_to ? (
            <ReplyReference
              reply={message.metadata.reply_to}
              participantById={participantById}
            />
          ) : null}
          <p className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground">
            {renderMessageText(message.text, participantById)}
          </p>
          <EntityReferences refs={refs} onEntityClick={onEntityClick} />
        </div>
        {isPinned ? (
          <div
            className={cn(
              "mt-1 flex items-center gap-1 text-[11px] text-muted-foreground",
              own && "flex-row-reverse",
            )}
          >
            <PinIcon className="size-3" />
            <span>已置顶</span>
          </div>
        ) : null}
        {messageReactions.length > 0 ? (
          <div
            className={cn("mt-1 flex flex-wrap gap-1", own && "justify-end")}
          >
            {messageReactions.map((reaction) => {
              const active = Boolean(
                reactingParticipantId &&
                reaction.participant_ids.includes(reactingParticipantId),
              );
              return (
                <button
                  key={`${reaction.message_id}:${reaction.emoji}`}
                  type="button"
                  aria-label={`${reaction.emoji} ${reaction.count} 人回应`}
                  onClick={() =>
                    void collab
                      ?.toggleMessageReaction(
                        annotationMessageId,
                        reaction.emoji,
                      )
                      .catch((error) =>
                        swallow(error, "toggle-collaboration-message-reaction"),
                      )
                  }
                  className={cn(
                    "rounded-full border border-border-subtle bg-muted/50 px-1.5 py-0.5 text-xs transition-colors hover:bg-muted",
                    active && "border-primary/30 bg-primary/10 text-primary",
                  )}
                >
                  {reaction.emoji} {reaction.count}
                </button>
              );
            })}
          </div>
        ) : null}
        {messageActions !== false && messageActions ? (
          <CoworkRoomMessageActions
            {...messageActions}
            message={message}
            className={cn(own && "justify-end", messageActions.className)}
          />
        ) : null}
        {collab ? (
          <div className="relative flex items-center gap-0.5">
            <button
              type="button"
              aria-label="添加消息回应"
              aria-expanded={showReactionPicker}
              onClick={() => setShowReactionPicker((current) => !current)}
              className="rounded p-1 text-muted-foreground opacity-0 transition hover:bg-muted hover:text-foreground group-hover/msg:opacity-100 focus-visible:opacity-100"
            >
              <SmilePlusIcon className="size-3.5" />
            </button>
            <button
              type="button"
              aria-label={isPinned ? "取消置顶消息" : "置顶消息"}
              onClick={() =>
                void collab
                  .togglePinnedMessage(annotationMessageId)
                  .catch((error) =>
                    swallow(error, "toggle-collaboration-message-pin"),
                  )
              }
              className={cn(
                "rounded p-1 text-muted-foreground opacity-0 transition hover:bg-muted hover:text-foreground group-hover/msg:opacity-100 focus-visible:opacity-100",
                isPinned && "opacity-100 text-primary",
              )}
            >
              <PinIcon className="size-3.5" />
            </button>
            {showReactionPicker ? (
              <div className="absolute left-0 top-7 z-10 flex gap-0.5 rounded-lg border border-border-subtle bg-popover p-1 shadow-md">
                {["👍", "✅", "👀", "🎉"].map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    aria-label={`用 ${emoji} 回应`}
                    onClick={() => {
                      setShowReactionPicker(false);
                      void collab
                        .toggleMessageReaction(annotationMessageId, emoji)
                        .catch((error) =>
                          swallow(
                            error,
                            "toggle-collaboration-message-reaction",
                          ),
                        );
                    }}
                    className="rounded p-1 text-sm hover:bg-muted"
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            ) : null}
            <AddAnnotationButton
              messageId={annotationMessageId}
              className={annotationCount > 0 ? "opacity-100 text-primary" : ""}
            />
            {annotationCount > 0 ? (
              <button
                type="button"
                aria-label={`查看 ${annotationCount} 条批注`}
                onClick={() => setShowAnnotations((current) => !current)}
                className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/15"
              >
                {annotationCount}
              </button>
            ) : null}
          </div>
        ) : null}
        {collab && showAnnotations && annotationCount > 0 ? (
          <div className="mt-2 w-full space-y-2">
            {messageAnnotations.map((annotation) => (
              <AnnotationThread
                key={annotation.annotation_id}
                annotation={annotation}
              />
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

/** A single room event with no nested live-region semantics. */
export function CoworkRoomTimelineEntry({
  message,
  participants = [],
  currentParticipantId,
  messageActions,
  onEntityClick,
  className,
}: CoworkRoomTimelineEntryProps) {
  const participantById = useMemo(
    () => buildParticipantMap(participants),
    [participants],
  );
  return (
    <CoworkRoomTimelineEntryContent
      message={message}
      participantById={participantById}
      currentParticipantId={currentParticipantId}
      messageActions={messageActions}
      onEntityClick={onEntityClick}
      className={className}
    />
  );
}

export function CoworkRoomTimeline({
  messages,
  participants = [],
  currentParticipantId,
  messageActions,
  onEntityClick,
  emptyLabel = "还没有协作消息",
  className,
}: CoworkRoomTimelineProps) {
  const participantById = useMemo(
    () => buildParticipantMap(participants),
    [participants],
  );

  if (messages.length === 0) {
    return (
      <div
        className={cn(
          "flex min-h-32 items-center justify-center px-4 text-center text-sm text-muted-foreground",
          className,
        )}
      >
        {emptyLabel}
      </div>
    );
  }

  return (
    <div
      role="log"
      aria-live="polite"
      aria-label="协作房间消息"
      className={cn("space-y-3 px-3 py-4", className)}
    >
      {messages.map((message, index) => (
        <CoworkRoomTimelineEntryContent
          key={`${isCoworkRoomSystemMessage(message) ? "system" : "message"}:${message.seq}:${index}`}
          message={message}
          participantById={participantById}
          currentParticipantId={currentParticipantId}
          messageActions={messageActions}
          onEntityClick={onEntityClick}
        />
      ))}
    </div>
  );
}
