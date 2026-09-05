import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { swallow } from "@/core/utils/log";
import { getToken } from "@/core/auth/api";
import { openAuthenticatedWebSocket } from "@/core/auth/websocket";
import { getBackendWebSocketBaseURL } from "@/core/config";
import { readOrCreateTeamParticipantId } from "@/core/teams";
import type { SpeakerPolicy } from "@/core/teams";
import { eventBus } from "@/core/events";
import { teamTaskQueryKeys } from "@/core/team-tasks/hooks";
import type { TeamTask } from "@/core/team-tasks/types";
import type {
  CoworkMessageReaction,
  CoworkPinnedMessage,
  CoworkRoomReplyReference,
} from "@/core/cowork/types";
import {
  createCollabAnnotation,
  createCollabAnnotationReply,
  deleteCollabAnnotation,
  getCollabAnnotations,
  getCollabMessageReactions,
  getCollabPinnedMessages,
  setCollabAnnotationResolved,
  toggleCollabMessageReaction,
  toggleCollabPinnedMessage,
} from "@/core/cowork/api";

export interface User {
  id: string;
  name: string;
  avatar?: string;
  color: string;
}

export interface AnnotationAuthor {
  display_name: string;
  avatar_color: string;
}

export interface AnnotationReply {
  reply_id: string;
  author: AnnotationAuthor | null;
  body: string;
  created_at: number;
}

export interface Annotation {
  annotation_id: string;
  message_id: string;
  author: AnnotationAuthor | null;
  body: string;
  created_at: number;
  resolved: boolean;
  replies: AnnotationReply[];
}

export interface RoomMessage {
  message_id: string;
  client_message_id?: string;
  seq?: number;
  thread_id?: string;
  participant_id: string;
  display_name: string;
  on_behalf_of?: string;
  text: string;
  reply_to?: CoworkRoomReplyReference | null;
  created_at: string;
  delivery_status?: "sending" | "sent" | "delivered" | "read" | "failed";
  error?: string;
}

export interface RoomMessageReceipt {
  room_id: string;
  message_id: string;
  participant_id: string;
  status: "delivered" | "read";
  seq?: number | null;
  updated_at?: string;
}

export interface TeamTaskProgressEvent {
  id: string;
  team_id: string;
  room_id: string;
  task_id: string;
  task: TeamTask | null;
  event: string;
  role?: string | null;
  role_status?: string | null;
  completed_roles?: number;
  total_roles?: number;
  progress?: number;
  server_time: string;
  error?: string | null;
  runner_event?: Record<string, unknown> | null;
}

export interface FloorState {
  speakerPolicy: SpeakerPolicy;
  currentSpeakerId: string | null;
  moderatorId: string | null;
  floorRequests: string[];
}

const DEFAULT_FLOOR: FloorState = {
  speakerPolicy: "free",
  currentSpeakerId: null,
  moderatorId: null,
  floorRequests: [],
};

interface CollabContextType {
  users: User[];
  currentUser: User | null;
  isConnected: boolean;
  roomMessages: RoomMessage[];
  messageReceipts: RoomMessageReceipt[];
  taskEvents: TeamTaskProgressEvent[];
  floor: FloorState;
  join: (user: User) => void;
  leave: () => void;
  updateCursor: (position: { x: number; y: number }) => void;
  sendRoomMessage: (
    text: string,
    onBehalfOf?: string,
    replyTo?: CoworkRoomReplyReference | null,
  ) => string | null;
  retryRoomMessage: (messageId: string) => boolean;
  markRoomMessageRead: (messageId: string, seq?: number) => boolean;
  raiseHand: () => void;
  yieldFloor: () => void;
  grantFloor: (targetId: string | null) => void;
  notifyThreadUpdate: (reason?: string) => void;
  annotations: Annotation[];
  messageReactions: CoworkMessageReaction[];
  pinnedMessages: CoworkPinnedMessage[];
  toggleMessageReaction: (messageId: string, emoji: string) => Promise<void>;
  togglePinnedMessage: (messageId: string) => Promise<void>;
  addAnnotation: (messageId: string, body: string) => Promise<void>;
  resolveAnnotation: (annotationId: string) => Promise<void>;
  unresolveAnnotation: (annotationId: string) => Promise<void>;
  deleteAnnotation: (annotationId: string) => Promise<void>;
  replyToAnnotation: (annotationId: string, body: string) => Promise<void>;
}

interface CollabProviderProps {
  children: ReactNode;
  teamId?: string | null;
  threadId?: string | null;
  participantId?: string | null;
  displayName?: string | null;
  avatar?: string | null;
  autoConnect?: boolean;
}

const CollabContext = createContext<CollabContextType | null>(null);

export function CollabProvider({
  children,
  teamId,
  threadId,
  participantId,
  displayName,
  avatar,
  autoConnect = true,
}: CollabProviderProps) {
  const resolvedParticipantId = useMemo(
    () => participantId || readOrCreateTeamParticipantId(),
    [participantId],
  );
  const resolvedDisplayName = displayName?.trim() || "You";
  const normalizedThreadId = useMemo(() => {
    const value = threadId?.trim();
    return value && value !== "new" ? value : "";
  }, [threadId]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const shouldReconnectRef = useRef(true);
  const queryClient = useQueryClient();
  const [users, setUsers] = useState<User[]>([]);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [roomMessages, setRoomMessages] = useState<RoomMessage[]>([]);
  const [messageReceipts, setMessageReceipts] = useState<RoomMessageReceipt[]>(
    [],
  );
  const [taskEvents, setTaskEvents] = useState<TeamTaskProgressEvent[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [messageReactions, setMessageReactions] = useState<
    CoworkMessageReaction[]
  >([]);
  const [pinnedMessages, setPinnedMessages] = useState<CoworkPinnedMessage[]>(
    [],
  );
  const [floor, setFloor] = useState<FloorState>(DEFAULT_FLOOR);

  const localUser = useMemo<User>(
    () => ({
      id: resolvedParticipantId,
      name: resolvedDisplayName,
      avatar: avatar ?? undefined,
      color: colorFor(resolvedParticipantId),
    }),
    [avatar, resolvedDisplayName, resolvedParticipantId],
  );

  useEffect(() => {
    setTaskEvents([]);
    setRoomMessages([]);
    setMessageReceipts([]);
    setFloor(DEFAULT_FLOOR);
  }, [teamId]);

  useEffect(() => {
    if (!teamId || !normalizedThreadId) {
      setAnnotations([]);
      setMessageReactions([]);
      setPinnedMessages([]);
      return;
    }
    let disposed = false;
    void getCollabAnnotations(normalizedThreadId)
      .then((next) => {
        if (!disposed) setAnnotations(next);
      })
      .catch((error) => {
        if (!disposed) swallow(error, "load-collaboration-annotations");
      });
    void getCollabMessageReactions(normalizedThreadId)
      .then((next) => {
        if (!disposed) setMessageReactions(next);
      })
      .catch((error) => {
        if (!disposed) swallow(error, "load-collaboration-message-reactions");
      });
    void getCollabPinnedMessages(normalizedThreadId)
      .then((next) => {
        if (!disposed) setPinnedMessages(next);
      })
      .catch((error) => {
        if (!disposed) swallow(error, "load-collaboration-pinned-messages");
      });
    return () => {
      disposed = true;
    };
  }, [normalizedThreadId, teamId]);

  useEffect(() => {
    if (!teamId || typeof window === "undefined") return;
    const queued = readRoomOutbox(teamId, resolvedParticipantId);
    if (queued.length === 0) return;
    setRoomMessages((prev) => {
      let next = prev;
      for (const item of queued) {
        next = upsertRoomMessage(next, {
          message_id: `local:${item.client_message_id}`,
          client_message_id: item.client_message_id,
          thread_id: item.thread_id,
          participant_id: item.on_behalf_of || resolvedParticipantId,
          display_name: item.on_behalf_of ? "Pending" : localUser.name,
          on_behalf_of: item.on_behalf_of,
          reply_to: item.reply_to,
          text: item.text,
          created_at: item.created_at,
          delivery_status: "sending",
        });
      }
      return next;
    });
  }, [localUser.name, resolvedParticipantId, teamId]);

  const notifyRemoved = useCallback(
    (_reason = "removed") => {
      if (!teamId || typeof window === "undefined") return;
      eventBus.emit("team:removed", { teamId });
    },
    [teamId],
  );

  const closeSocket = useCallback(() => {
    shouldReconnectRef.current = false;
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    setIsConnected(false);
  }, []);

  useEffect(() => {
    if (!teamId || !autoConnect || typeof window === "undefined") {
      setCurrentUser(localUser);
      setUsers(localUser ? [localUser] : []);
      return;
    }

    shouldReconnectRef.current = true;
    let disposed = false;

    const connect = () => {
      if (disposed || !shouldReconnectRef.current) return;
      const wsBase = getBackendWebSocketBaseURL();
      const params = new URLSearchParams({
        participant_id: resolvedParticipantId,
        display_name: resolvedDisplayName,
      });
      if (normalizedThreadId) {
        params.set("thread_id", normalizedThreadId);
      }
      const socket = openAuthenticatedWebSocket(
        `${wsBase}/api/teams/${encodeURIComponent(teamId)}/ws?${params.toString()}`,
        getToken(),
      );
      wsRef.current = socket;

      socket.onopen = () => {
        if (disposed) return;
        setIsConnected(true);
        setCurrentUser(localUser);
        for (const queued of readRoomOutbox(teamId, resolvedParticipantId)) {
          try {
            socket.send(
              JSON.stringify({
                type: "message",
                text: queued.text,
                client_message_id: queued.client_message_id,
                ...(queued.on_behalf_of
                  ? { on_behalf_of: queued.on_behalf_of }
                  : {}),
                ...(queued.thread_id ? { thread_id: queued.thread_id } : {}),
                ...(queued.reply_to ? { reply_to: queued.reply_to } : {}),
              }),
            );
          } catch {
            break;
          }
        }
      };
      socket.onmessage = (event) => {
        if (disposed) return;
        const msg = parseMessage(event.data);
        if (!msg) return;
        if (msg.type === "error") {
          const message = String(msg.message ?? "");
          const clientMessageId = String(msg.client_message_id ?? "");
          if (clientMessageId) {
            setRoomMessages((prev) =>
              markRoomMessageFailed(prev, clientMessageId, message),
            );
            if (msg.retryable !== true) {
              removeRoomOutboxMessage(
                teamId,
                resolvedParticipantId,
                clientMessageId,
              );
            }
          }
          if (message.includes("participant removed")) {
            shouldReconnectRef.current = false;
            notifyRemoved("removed");
            socket.close(4403);
          } else if (
            msg.code === "speech_denied" ||
            msg.code === "delegation_denied" ||
            msg.code === "not_moderator"
          ) {
            // The room rejected this send (muted / not your turn / not the
            // moderator / not authorized to speak for someone). Surface it.
            toast.error(message || "You can't speak right now");
          }
        } else if (msg.type === "message:error") {
          const clientMessageId = String(msg.client_message_id ?? "");
          if (clientMessageId) {
            setRoomMessages((prev) =>
              markRoomMessageFailed(
                prev,
                clientMessageId,
                String(msg.message ?? "Message was not saved"),
              ),
            );
            if (msg.retryable !== true) {
              removeRoomOutboxMessage(
                teamId,
                resolvedParticipantId,
                clientMessageId,
              );
            }
          }
        } else if (msg.type === "floor") {
          setFloor(floorFrom(msg));
        } else if (msg.type === "ready" && msg.participant) {
          setCurrentUser(participantToUser(msg.participant, avatar));
          if (isRecord(msg.team)) setFloor(floorFrom(msg.team));
        } else if (msg.type === "presence" && Array.isArray(msg.participants)) {
          setUsers(msg.participants.map((p) => participantToUser(p)));
        } else if (msg.type === "message:receipt") {
          const status = msg.status === "read" ? "read" : "delivered";
          const receipt: RoomMessageReceipt = {
            room_id: String(msg.room_id ?? teamId ?? ""),
            message_id: String(msg.message_id ?? ""),
            participant_id: String(msg.participant_id ?? ""),
            status,
            seq: Number.isFinite(Number(msg.seq)) ? Number(msg.seq) : null,
            updated_at: String(msg.updated_at ?? new Date().toISOString()),
          };
          if (!receipt.message_id || !receipt.participant_id) return;
          setMessageReceipts((prev) => upsertRoomMessageReceipt(prev, receipt));
          if (receipt.participant_id === resolvedParticipantId) {
            setRoomMessages((prev) =>
              prev.map((message) =>
                message.message_id === receipt.message_id
                  ? {
                      ...message,
                      delivery_status:
                        receipt.status === "read" ? "read" : "delivered",
                    }
                  : message,
              ),
            );
          }
        } else if (msg.type === "message" && typeof msg.text === "string") {
          const incomingThreadId =
            typeof msg.thread_id === "string" ? msg.thread_id : "";
          if (normalizedThreadId && incomingThreadId !== normalizedThreadId) {
            return;
          }
          const text = msg.text;
          const clientMessageId = String(msg.client_message_id ?? "");
          if (clientMessageId) {
            removeRoomOutboxMessage(
              teamId,
              resolvedParticipantId,
              clientMessageId,
            );
          }
          setRoomMessages((prev) =>
            upsertRoomMessage(prev, {
              message_id: String(msg.message_id ?? `room-msg-${Date.now()}`),
              client_message_id: clientMessageId || undefined,
              seq: Number.isFinite(Number(msg.seq))
                ? Number(msg.seq)
                : undefined,
              thread_id: incomingThreadId || undefined,
              participant_id: String(msg.participant_id ?? ""),
              display_name: String(msg.display_name ?? "Guest"),
              reply_to: isRecord(msg.reply_to)
                ? (msg.reply_to as CoworkRoomReplyReference)
                : undefined,
              text,
              created_at: String(msg.created_at ?? new Date().toISOString()),
              delivery_status: "sent",
            }),
          );
          if (
            clientMessageId &&
            String(msg.participant_id ?? "") !== resolvedParticipantId &&
            wsRef.current?.readyState === WebSocket.OPEN
          ) {
            try {
              wsRef.current.send(
                JSON.stringify({
                  type: "message:delivered",
                  message_id: String(msg.message_id ?? ""),
                  seq: Number.isFinite(Number(msg.seq))
                    ? Number(msg.seq)
                    : undefined,
                }),
              );
            } catch {
              // Delivery receipts are best-effort; reconnect catch-up remains
              // authoritative for the message itself.
            }
          }
        } else if (msg.type === "thread:update") {
          const incomingThreadId =
            typeof msg.thread_id === "string" ? msg.thread_id : "";
          if (normalizedThreadId && incomingThreadId !== normalizedThreadId) {
            return;
          }
          const senderId = String(msg.participant_id ?? "");
          if (senderId === resolvedParticipantId) return;
          if (msg.reason === "annotation" && normalizedThreadId) {
            void getCollabAnnotations(normalizedThreadId)
              .then(setAnnotations)
              .catch((error) =>
                swallow(error, "refresh-collaboration-annotations"),
              );
          }
          if (msg.reason === "reaction" && normalizedThreadId) {
            void getCollabMessageReactions(normalizedThreadId)
              .then(setMessageReactions)
              .catch((error) =>
                swallow(error, "refresh-collaboration-message-reactions"),
              );
          }
          if (msg.reason === "pin" && normalizedThreadId) {
            void getCollabPinnedMessages(normalizedThreadId)
              .then(setPinnedMessages)
              .catch((error) =>
                swallow(error, "refresh-collaboration-pinned-messages"),
              );
          }
          window.dispatchEvent(
            new CustomEvent("octopus:team-thread-update", {
              detail: {
                teamId,
                threadId: incomingThreadId,
                participantId: senderId,
                reason: String(msg.reason ?? "updated"),
              },
            }),
          );
        } else if (msg.type === "team:update" && msg.team) {
          eventBus.emit("team:room-updated", { roomId: teamId ?? "" });
          if (isRecord(msg.team)) setFloor(floorFrom(msg.team));
          if (teamHasRemovedParticipant(msg.team, resolvedParticipantId)) {
            shouldReconnectRef.current = false;
            notifyRemoved("removed");
            socket.close(4403);
          }
        } else if (msg.type === "task:progress") {
          const taskEvent = parseTaskProgressEvent(msg, teamId);
          if (!taskEvent) return;
          setTaskEvents((prev) => appendTaskProgressEvent(prev, taskEvent));
          if (taskEvent.event === "task_deleted") {
            queryClient.setQueryData<TeamTask[]>(
              teamTaskQueryKeys.byRoom(taskEvent.room_id),
              (current) => removeTaskFromList(current, taskEvent.task_id),
            );
            void queryClient.invalidateQueries({
              queryKey: teamTaskQueryKeys.byRoom(taskEvent.room_id),
            });
          } else if (taskEvent.task) {
            queryClient.setQueryData<TeamTask[]>(
              teamTaskQueryKeys.byRoom(taskEvent.room_id),
              (current) => mergeTaskIntoList(current, taskEvent.task!),
            );
            void queryClient.invalidateQueries({
              queryKey: teamTaskQueryKeys.byRoom(taskEvent.room_id),
            });
          }
        }
      };
      socket.onclose = (event) => {
        if (disposed) return;
        setIsConnected(false);
        setRoomMessages((prev) =>
          prev.map((message) =>
            message.delivery_status === "sending"
              ? {
                  ...message,
                  delivery_status: "failed",
                  error: "Connection lost before the message was confirmed",
                }
              : message,
          ),
        );
        if (event.code === 4403) {
          shouldReconnectRef.current = false;
          notifyRemoved("removed");
          return;
        }
        if (shouldReconnectRef.current) {
          reconnectTimerRef.current = window.setTimeout(connect, 1500);
        }
      };
      socket.onerror = () => {
        setIsConnected(false);
      };
    };

    connect();

    return () => {
      disposed = true;
      closeSocket();
    };
  }, [
    autoConnect,
    avatar,
    closeSocket,
    localUser,
    normalizedThreadId,
    notifyRemoved,
    queryClient,
    resolvedDisplayName,
    resolvedParticipantId,
    teamId,
  ]);

  useEffect(() => {
    if (!isConnected) return;
    const timer = window.setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "presence:ping" }));
      }
    }, 15000);
    return () => window.clearInterval(timer);
  }, [isConnected]);

  const join = useCallback((user: User) => {
    setCurrentUser(user);
    setUsers((prev) => [user, ...prev.filter((u) => u.id !== user.id)]);
    setIsConnected(true);
  }, []);

  const leave = useCallback(() => {
    closeSocket();
    setUsers((prev) => prev.filter((u) => u.id !== currentUser?.id));
    setCurrentUser(null);
  }, [closeSocket, currentUser?.id]);

  const sendJson = useCallback((payload: Record<string, unknown>): boolean => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return false;
    try {
      wsRef.current.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }, []);

  const updateCursor = useCallback(
    (position: { x: number; y: number }) => {
      sendJson({
        type: "cursor",
        position,
        ...(normalizedThreadId ? { thread_id: normalizedThreadId } : {}),
      });
    },
    [normalizedThreadId, sendJson],
  );

  const sendRoomMessage = useCallback(
    (
      text: string,
      onBehalfOf?: string,
      replyTo?: CoworkRoomReplyReference | null,
    ) => {
      const clean = text.trim();
      if (!clean) return null;
      const clientMessageId = createClientMessageId();
      const localMessage: RoomMessage = {
        message_id: `local:${clientMessageId}`,
        client_message_id: clientMessageId,
        thread_id: normalizedThreadId || undefined,
        participant_id: onBehalfOf || localUser.id,
        display_name: onBehalfOf ? "Pending" : localUser.name,
        on_behalf_of: onBehalfOf,
        reply_to: replyTo ?? undefined,
        text: clean,
        created_at: new Date().toISOString(),
        delivery_status: "sending",
      };
      enqueueRoomOutbox(teamId, resolvedParticipantId, {
        client_message_id: clientMessageId,
        thread_id: normalizedThreadId || undefined,
        on_behalf_of: onBehalfOf,
        text: clean,
        reply_to: replyTo ?? undefined,
      });
      setRoomMessages((prev) => upsertRoomMessage(prev, localMessage));
      const sent = sendJson({
        type: "message",
        text: clean,
        client_message_id: clientMessageId,
        ...(onBehalfOf ? { on_behalf_of: onBehalfOf } : {}),
        ...(normalizedThreadId ? { thread_id: normalizedThreadId } : {}),
        ...(replyTo ? { reply_to: replyTo } : {}),
      });
      if (!sent) {
        setRoomMessages((prev) =>
          markRoomMessageFailed(prev, clientMessageId, "Not connected"),
        );
      }
      return clientMessageId;
    },
    [localUser, normalizedThreadId, resolvedParticipantId, sendJson, teamId],
  );

  const retryRoomMessage = useCallback(
    (messageId: string) => {
      const pending = roomMessages.find(
        (message) =>
          message.message_id === messageId ||
          message.client_message_id === messageId,
      );
      if (!pending?.client_message_id || pending.delivery_status !== "failed") {
        return false;
      }
      setRoomMessages((prev) =>
        prev.map((message) =>
          message.client_message_id === pending.client_message_id
            ? { ...message, delivery_status: "sending", error: undefined }
            : message,
        ),
      );
      const sent = sendJson({
        type: "message",
        text: pending.text,
        client_message_id: pending.client_message_id,
        ...(pending.on_behalf_of ? { on_behalf_of: pending.on_behalf_of } : {}),
        ...(pending.thread_id ? { thread_id: pending.thread_id } : {}),
        ...(pending.reply_to ? { reply_to: pending.reply_to } : {}),
      });
      if (!sent) {
        setRoomMessages((prev) =>
          markRoomMessageFailed(
            prev,
            pending.client_message_id!,
            "Not connected",
          ),
        );
      }
      return sent;
    },
    [roomMessages, sendJson],
  );

  const markRoomMessageRead = useCallback(
    (messageId: string, seq?: number) => {
      const cleanId = messageId.trim();
      if (!cleanId) return false;
      const sent = sendJson({
        type: "message:read",
        message_id: cleanId,
        ...(seq != null ? { seq } : {}),
      });
      if (sent) {
        setMessageReceipts((prev) =>
          upsertRoomMessageReceipt(prev, {
            room_id: teamId ?? "",
            message_id: cleanId,
            participant_id: resolvedParticipantId,
            status: "read",
            seq: seq ?? null,
            updated_at: new Date().toISOString(),
          }),
        );
        setRoomMessages((prev) =>
          prev.map((message) =>
            message.message_id === cleanId
              ? { ...message, delivery_status: "read" }
              : message,
          ),
        );
      }
      return sent;
    },
    [resolvedParticipantId, sendJson, teamId],
  );

  const raiseHand = useCallback(() => {
    sendJson({ type: "floor:request" });
  }, [sendJson]);

  const yieldFloor = useCallback(() => {
    sendJson({ type: "floor:yield" });
  }, [sendJson]);

  const grantFloor = useCallback(
    (targetId: string | null) => {
      sendJson({ type: "floor:grant", target: targetId ?? "" });
    },
    [sendJson],
  );

  const notifyThreadUpdate = useCallback(
    (reason = "updated") => {
      if (!normalizedThreadId) return;
      sendJson({
        type: "thread:update",
        thread_id: normalizedThreadId,
        reason,
      });
    },
    [normalizedThreadId, sendJson],
  );

  const author = useMemo<AnnotationAuthor | null>(
    () =>
      currentUser
        ? { display_name: currentUser.name, avatar_color: currentUser.color }
        : null,
    [currentUser],
  );

  const addAnnotation = useCallback(
    async (messageId: string, body: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      const annotation = await createCollabAnnotation(normalizedThreadId, {
        message_id: messageId,
        body,
        display_name: author?.display_name,
        avatar_color: author?.avatar_color,
      });
      setAnnotations((prev) => [...prev, annotation]);
      void queryClient.invalidateQueries({
        queryKey: ["cowork", "session", normalizedThreadId],
      });
      notifyThreadUpdate("annotation");
    },
    [author, normalizedThreadId, notifyThreadUpdate, queryClient],
  );

  const toggleMessageReaction = useCallback(
    async (messageId: string, emoji: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      const reaction = await toggleCollabMessageReaction(normalizedThreadId, {
        message_id: messageId,
        emoji,
      });
      setMessageReactions((previous) => {
        const withoutCurrent = previous.filter(
          (item) =>
            !(
              item.message_id === reaction.message_id &&
              item.emoji === reaction.emoji
            ),
        );
        return reaction.count > 0
          ? [...withoutCurrent, reaction]
          : withoutCurrent;
      });
      notifyThreadUpdate("reaction");
    },
    [normalizedThreadId, notifyThreadUpdate],
  );

  const togglePinnedMessage = useCallback(
    async (messageId: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      const pin = await toggleCollabPinnedMessage(
        normalizedThreadId,
        messageId,
      );
      setPinnedMessages((previous) =>
        pin.pinned
          ? [
              ...previous.filter((item) => item.message_id !== pin.message_id),
              {
                message_id: pin.message_id,
                pinned_by: currentUser?.id ?? "",
                created_at: Date.now() / 1000,
              },
            ]
          : previous.filter((item) => item.message_id !== pin.message_id),
      );
      notifyThreadUpdate("pin");
    },
    [currentUser?.id, normalizedThreadId, notifyThreadUpdate],
  );

  const resolveAnnotation = useCallback(
    async (annotationId: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      const annotation = await setCollabAnnotationResolved(
        normalizedThreadId,
        annotationId,
        true,
      );
      setAnnotations((prev) =>
        prev.map((item) =>
          item.annotation_id === annotationId ? annotation : item,
        ),
      );
      notifyThreadUpdate("annotation");
    },
    [normalizedThreadId, notifyThreadUpdate],
  );

  const unresolveAnnotation = useCallback(
    async (annotationId: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      const annotation = await setCollabAnnotationResolved(
        normalizedThreadId,
        annotationId,
        false,
      );
      setAnnotations((prev) =>
        prev.map((item) =>
          item.annotation_id === annotationId ? annotation : item,
        ),
      );
      notifyThreadUpdate("annotation");
    },
    [normalizedThreadId, notifyThreadUpdate],
  );

  const deleteAnnotation = useCallback(
    async (annotationId: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      await deleteCollabAnnotation(normalizedThreadId, annotationId);
      setAnnotations((prev) =>
        prev.filter((item) => item.annotation_id !== annotationId),
      );
      notifyThreadUpdate("annotation");
    },
    [normalizedThreadId, notifyThreadUpdate],
  );

  const replyToAnnotation = useCallback(
    async (annotationId: string, body: string) => {
      if (!normalizedThreadId) throw new Error("请先创建协作会话");
      const { reply } = await createCollabAnnotationReply(
        normalizedThreadId,
        annotationId,
        {
          body,
          display_name: author?.display_name,
          avatar_color: author?.avatar_color,
        },
      );
      setAnnotations((prev) =>
        prev.map((item) =>
          item.annotation_id === annotationId
            ? {
                ...item,
                replies: [...item.replies, reply],
              }
            : item,
        ),
      );
      notifyThreadUpdate("annotation");
    },
    [author, normalizedThreadId, notifyThreadUpdate],
  );

  return (
    <CollabContext.Provider
      value={{
        users,
        currentUser,
        isConnected,
        roomMessages,
        messageReceipts,
        taskEvents,
        floor,
        raiseHand,
        yieldFloor,
        grantFloor,
        join,
        leave,
        updateCursor,
        sendRoomMessage,
        retryRoomMessage,
        markRoomMessageRead,
        notifyThreadUpdate,
        annotations,
        messageReactions,
        pinnedMessages,
        toggleMessageReaction,
        togglePinnedMessage,
        addAnnotation,
        resolveAnnotation,
        unresolveAnnotation,
        deleteAnnotation,
        replyToAnnotation,
      }}
    >
      {children}
    </CollabContext.Provider>
  );
}

export function useCollab() {
  const context = useContext(CollabContext);
  if (!context) {
    throw new Error("useCollab must be used within CollabProvider");
  }
  return context;
}

export function useOptionalCollab() {
  return useContext(CollabContext);
}

function createClientMessageId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

interface QueuedRoomMessage {
  client_message_id: string;
  text: string;
  thread_id?: string;
  on_behalf_of?: string;
  created_at: string;
  reply_to?: CoworkRoomReplyReference | null;
}

const ROOM_OUTBOX_PREFIX = "octopus:room-outbox:";

function roomOutboxKey(teamId: string, participantId: string): string {
  return `${ROOM_OUTBOX_PREFIX}${teamId}:${participantId}`;
}

function readRoomOutbox(
  teamId?: string | null,
  participantId?: string | null,
): QueuedRoomMessage[] {
  if (!teamId || !participantId || typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(roomOutboxKey(teamId, participantId)) ?? "[]",
    );
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is QueuedRoomMessage =>
        item &&
        typeof item === "object" &&
        typeof item.client_message_id === "string" &&
        typeof item.text === "string" &&
        typeof item.created_at === "string",
    );
  } catch {
    return [];
  }
}

function writeRoomOutbox(
  teamId: string,
  participantId: string,
  messages: QueuedRoomMessage[],
) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      roomOutboxKey(teamId, participantId),
      JSON.stringify(messages.slice(-100)),
    );
  } catch {
    // Storage may be disabled or full; in-memory delivery still works.
  }
}

function enqueueRoomOutbox(
  teamId: string | null | undefined,
  participantId: string,
  message: Omit<QueuedRoomMessage, "created_at"> & { created_at?: string },
) {
  if (!teamId) return;
  const queued = readRoomOutbox(teamId, participantId).filter(
    (item) => item.client_message_id !== message.client_message_id,
  );
  queued.push({
    ...message,
    created_at: message.created_at ?? new Date().toISOString(),
  });
  writeRoomOutbox(teamId, participantId, queued);
}

function removeRoomOutboxMessage(
  teamId: string | null | undefined,
  participantId: string,
  clientMessageId: string,
) {
  if (!teamId) return;
  const queued = readRoomOutbox(teamId, participantId).filter(
    (item) => item.client_message_id !== clientMessageId,
  );
  writeRoomOutbox(teamId, participantId, queued);
}

export function upsertRoomMessage(
  messages: RoomMessage[],
  incoming: RoomMessage,
): RoomMessage[] {
  const index = messages.findIndex(
    (message) =>
      message.message_id === incoming.message_id ||
      Boolean(
        incoming.client_message_id &&
        message.client_message_id === incoming.client_message_id,
      ),
  );
  if (index < 0) return [...messages, incoming].slice(-50);
  const next = [...messages];
  next[index] = incoming;
  return next.slice(-50);
}

export function upsertRoomMessageReceipt(
  receipts: RoomMessageReceipt[],
  incoming: RoomMessageReceipt,
): RoomMessageReceipt[] {
  const index = receipts.findIndex(
    (receipt) =>
      receipt.message_id === incoming.message_id &&
      receipt.participant_id === incoming.participant_id,
  );
  if (index < 0) return [...receipts, incoming].slice(-500);
  const current = receipts[index]!;
  const status =
    current.status === "read" || incoming.status === "read"
      ? "read"
      : "delivered";
  const next = [...receipts];
  next[index] = {
    ...current,
    ...incoming,
    status,
    seq: incoming.seq ?? current.seq ?? null,
  };
  return next.slice(-500);
}

function markRoomMessageFailed(
  messages: RoomMessage[],
  clientMessageId: string,
  error: string,
): RoomMessage[] {
  return messages.map((message) =>
    message.client_message_id === clientMessageId
      ? { ...message, delivery_status: "failed", error }
      : message,
  );
}

function parseMessage(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "string") return null;
  try {
    const parsed = JSON.parse(data);
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, unknown>)
      : null;
  } catch (e) {
    swallow(e);
    return null;
  }
}

function participantToUser(participant: unknown, avatar?: string | null): User {
  const item =
    participant && typeof participant === "object"
      ? (participant as Record<string, unknown>)
      : {};
  const id = String(item.id ?? `guest-${Date.now()}`);
  const name = String(item.display_name ?? "Guest");
  return {
    id,
    name,
    avatar: avatar ?? undefined,
    color: colorFor(id),
  };
}

function teamHasRemovedParticipant(
  team: unknown,
  participantId: string,
): boolean {
  const item =
    team && typeof team === "object" ? (team as Record<string, unknown>) : {};
  const participants = Array.isArray(item.participants)
    ? item.participants
    : [];
  return participants.some((participant) => {
    if (!participant || typeof participant !== "object") return false;
    const p = participant as Record<string, unknown>;
    return p.id === participantId && p.status === "removed";
  });
}

function parseTaskProgressEvent(
  msg: Record<string, unknown>,
  expectedTeamId?: string | null,
): TeamTaskProgressEvent | null {
  const task = isRecord(msg.task) ? (msg.task as unknown as TeamTask) : null;
  const taskId = stringOr(msg.task_id) || task?.id || "";
  const roomId =
    stringOr(msg.room_id) || stringOr(msg.team_id) || task?.room_id || "";
  if (!taskId || !roomId) return null;
  // Require an explicit expectedTeamId and force a strict match. A
  // permissive fallback (when expectedTeamId is falsy) used to let
  // global subscribers swallow task:progress for arbitrary rooms,
  // which corrupted React Query cache and could clear UI for tasks
  // the user owns. WS messages MUST be scoped to the current team.
  if (!expectedTeamId || roomId !== expectedTeamId) return null;
  const event = stringOr(msg.event) || "progress";
  const serverTime = stringOr(msg.server_time) || new Date().toISOString();
  return {
    id: [
      taskId,
      event,
      serverTime,
      stringOr(msg.role),
      stringOr(msg.completed_roles),
    ].join(":"),
    team_id: stringOr(msg.team_id) || roomId,
    room_id: roomId,
    task_id: taskId,
    task,
    event,
    role: stringOr(msg.role) || null,
    role_status: stringOr(msg.role_status) || null,
    completed_roles: numberOr(msg.completed_roles),
    total_roles: numberOr(msg.total_roles),
    progress: numberOr(msg.progress),
    server_time: serverTime,
    error: stringOr(msg.error) || null,
    runner_event: isRecord(msg.runner_event) ? msg.runner_event : null,
  };
}

function appendTaskProgressEvent(
  prev: TeamTaskProgressEvent[],
  event: TeamTaskProgressEvent,
) {
  const filtered = prev.filter((item) => item.id !== event.id);
  return [...filtered, event].slice(-80);
}

function mergeTaskIntoList(
  current: TeamTask[] | undefined,
  task: TeamTask,
): TeamTask[] {
  const existing = current ?? [];
  const next = existing.some((item) => item.id === task.id)
    ? existing.map((item) => (item.id === task.id ? task : item))
    : [task, ...existing];
  return [...next].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

function removeTaskFromList(
  current: TeamTask[] | undefined,
  taskId: string,
): TeamTask[] {
  return (current ?? []).filter((item) => item.id !== taskId);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

const FLOOR_POLICIES = new Set<SpeakerPolicy>([
  "free",
  "admin_only",
  "round_robin",
  "roll_call",
  "moderated",
]);

// Extract floor state from either a dedicated ``floor`` event or a team
// object (which carries the same fields). Tolerant of missing keys.
function floorFrom(source: unknown): FloorState {
  const item = isRecord(source) ? source : {};
  const policy = String(item.speaker_policy ?? "free") as SpeakerPolicy;
  return {
    speakerPolicy: FLOOR_POLICIES.has(policy) ? policy : "free",
    currentSpeakerId:
      typeof item.current_speaker_id === "string"
        ? item.current_speaker_id
        : null,
    moderatorId:
      typeof item.moderator_id === "string" ? item.moderator_id : null,
    floorRequests: Array.isArray(item.floor_requests)
      ? item.floor_requests.filter((x): x is string => typeof x === "string")
      : [],
  };
}

function stringOr(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberOr(value: unknown): number | undefined {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function colorFor(id: string): string {
  const palette = [
    "#2563eb",
    "#059669",
    "#dc2626",
    "#7c3aed",
    "#ca8a04",
    "#0891b2",
    "#be185d",
    "#4f46e5",
  ];
  let hash = 0;
  for (const char of id) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return palette[hash % palette.length] ?? palette[0]!;
}
