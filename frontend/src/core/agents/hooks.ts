import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAgent,
  deleteAgent,
  generateAgentVisuals,
  getAgent,
  listAgents,
  updateAgent,
} from "./api";
import { type Agent, type CreateAgentRequest, type UpdateAgentRequest } from "./types";

export function useAgents() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: ({ signal }) => listAgents({ signal }),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  // Backend is the ONLY source of truth. No frontend preset merge: the
  // previous stub list (DID-xxx placeholders) caused footer → backend
  // routing mismatches that silently dropped persona soul (the LLM
  // started greeting as "Claude" because an unresolvable id leaked into
  // context.agent_name). If the backend is unreachable, callers get
  // `isLoading` / `error` and should render a loading state rather than
  // fake stubs that look clickable but break.
  const agents = useMemo<Agent[]>(() => data ?? [], [data]);
  return { agents, isLoading, error };
}

export function useAgent(name: string | null | undefined) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents", name],
    queryFn: ({ signal }) => getAgent(name!, { signal }),
    enabled: !!name,
    retry: false,
  });
  // No frontend preset fallback: null means "agent unknown, render a
  // placeholder or error instead of fabricating metadata". See
  // `useAgents()` above for the history.
  const agent = useMemo<Agent | null>(() => data ?? null, [data]);
  return { agent, isLoading, error };
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAgentRequest) => createAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateAgentRequest;
    }) => updateAgent(name, request),
    onSuccess: (_data, { name }) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
    },
  });
}

export function useGenerateAgentVisuals() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => generateAgentVisuals(name),
    onSuccess: (_data, name) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
    },
  });
}

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}
