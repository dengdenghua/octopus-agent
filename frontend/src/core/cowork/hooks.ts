import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getCoworkGroup,
  inviteCoworkMember,
  removeCoworkMember,
  setCoworkMode,
} from "./api";
import type { CoworkInviteInput, CoworkMode } from "./types";

const COWORK_KEY = ["cowork"] as const;

export const coworkQueryKeys = {
  all: COWORK_KEY,
  group: (threadId?: string | null) =>
    [...COWORK_KEY, "group", threadId ?? "none"] as const,
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
    },
  });
}
