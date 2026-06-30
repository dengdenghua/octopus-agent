import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getCollabSession,
  getCoworkGroup,
  getCoworkPresence,
  inviteCoworkMember,
  linkCoworkRoom,
  removeCoworkMember,
  searchCowork,
  setCoworkMode,
} from "./api";
import type {
  CoworkInviteInput,
  CoworkMode,
  CoworkSearchKind,
} from "./types";

const COWORK_KEY = ["cowork"] as const;

export const coworkQueryKeys = {
  all: COWORK_KEY,
  group: (threadId?: string | null) =>
    [...COWORK_KEY, "group", threadId ?? "none"] as const,
  presence: (threadId?: string | null) =>
    [...COWORK_KEY, "presence", threadId ?? "none"] as const,
  search: (threadId?: string | null, query?: string, kinds?: CoworkSearchKind[]) =>
    [...COWORK_KEY, "search", threadId ?? "none", query ?? "", (kinds ?? []).join(",")] as const,
  session: (threadId?: string | null) =>
    [...COWORK_KEY, "session", threadId ?? "none"] as const,
};

export function useCoworkGroup(threadId?: string | null) {
  return useQuery({
    queryKey: coworkQueryKeys.group(threadId),
    queryFn: () => getCoworkGroup(threadId!),
    enabled: Boolean(threadId && threadId !== "new"),
    staleTime: 1500,
  });
}

export function useInviteCoworkMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      threadId,
      input,
    }: {
      threadId: string;
      input: CoworkInviteInput;
    }) => inviteCoworkMember(threadId, input),
    onSuccess: (_state, { threadId }) => {
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.group(threadId) });
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.session(threadId) });
    },
  });
}

export function useRemoveCoworkMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      threadId,
      memberId,
    }: {
      threadId: string;
      memberId: string;
    }) => removeCoworkMember(threadId, memberId),
    onSuccess: (_state, { threadId }) => {
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.group(threadId) });
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.session(threadId) });
    },
  });
}

export function useSetCoworkMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      threadId,
      mode,
    }: {
      threadId: string;
      mode: CoworkMode;
    }) => setCoworkMode(threadId, mode),
    onSuccess: (_state, { threadId }) => {
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.group(threadId) });
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.session(threadId) });
    },
  });
}

export function useCoworkPresence(
  threadId?: string | null,
  opts: { enabled?: boolean; refetchInterval?: number } = {},
) {
  const enabled =
    (opts.enabled ?? true) && Boolean(threadId && threadId !== "new");
  return useQuery({
    queryKey: coworkQueryKeys.presence(threadId),
    queryFn: () => getCoworkPresence(threadId!),
    enabled,
    refetchInterval: enabled ? (opts.refetchInterval ?? 15000) : false,
    staleTime: 5000,
  });
}

export function useCoworkSearch(
  threadId?: string | null,
  query?: string,
  opts: { kinds?: CoworkSearchKind[]; limit?: number } = {},
) {
  const trimmed = (query ?? "").trim();
  return useQuery({
    queryKey: coworkQueryKeys.search(threadId, trimmed, opts.kinds),
    queryFn: () =>
      searchCowork(threadId!, trimmed, { kinds: opts.kinds, limit: opts.limit }),
    enabled: Boolean(threadId && threadId !== "new") && trimmed.length > 0,
    staleTime: 2000,
  });
}

export function useCollabSession(threadId?: string | null) {
  return useQuery({
    queryKey: coworkQueryKeys.session(threadId),
    queryFn: () => getCollabSession(threadId!),
    enabled: Boolean(threadId && threadId !== "new"),
    staleTime: 2000,
  });
}

export function useLinkCoworkRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, roomId }: { threadId: string; roomId: string }) =>
      linkCoworkRoom(threadId, roomId),
    onSuccess: (_void, { threadId }) => {
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.session(threadId) });
      void qc.invalidateQueries({ queryKey: coworkQueryKeys.group(threadId) });
    },
  });
}
