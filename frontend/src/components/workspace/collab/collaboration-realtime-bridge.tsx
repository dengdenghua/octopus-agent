import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { coworkQueryKeys } from "@/core/cowork/hooks";
import type { CoworkRoomParticipant } from "@/core/cowork/types";

import { CollabProvider, useCollab } from "./collab-provider";

export function countOnlineRoomParticipants(
  participants: readonly CoworkRoomParticipant[],
): number {
  const onlineIds = new Set<string>();
  for (const participant of participants) {
    const status = String(participant.status ?? "")
      .trim()
      .toLowerCase();
    if (status !== "active" && status !== "online") continue;
    const id = String(
      participant.id ?? participant.participant_id ?? "",
    ).trim();
    if (id) onlineIds.add(id);
  }
  return onlineIds.size;
}

function CollaborationRealtimeSync({ threadId }: { threadId: string }) {
  const queryClient = useQueryClient();
  const { isConnected, roomMessages, users } = useCollab();
  const activitySignal = useMemo(
    () =>
      JSON.stringify({
        connected: isConnected,
        messages: roomMessages.map((message) => [
          message.message_id,
          message.delivery_status,
        ]),
        users: users.map((user) => user.id).sort(),
      }),
    [isConnected, roomMessages, users],
  );
  const previousSignalRef = useRef(activitySignal);

  useEffect(() => {
    if (previousSignalRef.current === activitySignal) return;
    previousSignalRef.current = activitySignal;
    void queryClient.invalidateQueries({
      queryKey: coworkQueryKeys.session(threadId),
    });
  }, [activitySignal, queryClient, threadId]);

  return null;
}

/** Keep the linked Team Room live while its workspace is open.
 *
 * The bridge has no visual surface of its own: it establishes presence and
 * turns room WebSocket events into immediate refreshes of the canonical
 * collaboration timeline. The existing five-second query remains a recovery
 * path for reconnects and cross-process updates.
 */
export function CollaborationRealtimeBridge({
  roomId,
  threadId,
  participantId,
  displayName,
  avatar,
  children,
}: {
  roomId?: string | null;
  threadId?: string | null;
  participantId?: string | null;
  displayName?: string | null;
  avatar?: string | null;
  children?: ReactNode;
}) {
  if (!roomId || !threadId || threadId === "new") return children ?? null;
  return (
    <CollabProvider
      teamId={roomId}
      threadId={threadId}
      participantId={participantId}
      displayName={displayName}
      avatar={avatar}
    >
      <CollaborationRealtimeSync threadId={threadId} />
      {children}
    </CollabProvider>
  );
}
