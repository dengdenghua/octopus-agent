import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { coderQueryKeys, getCoderModelProfile } from "@/core/coder/api";
import { authHeaders } from "@/core/auth/api";
import type { EngineCapabilityChecks } from "@/core/agents/engine-capability-checks";
import { getBackendBaseURL } from "@/core/config";
import {
  executionEnginePreference,
  previewExecutionEngine,
  type ExecutionEnginePreference,
} from "@/core/realtime/execution-policy";

function readPreference(key: string): ExecutionEnginePreference | null {
  try {
    const saved = window.localStorage.getItem(key);
    return saved === null ? null : executionEnginePreference(saved);
  } catch {
    return null;
  }
}

export function useExecutionEngine({
  threadId,
  parentThreadId,
  principal,
  roleBackend,
  codingTask,
  orchestrated,
  enabled,
}: {
  threadId: string;
  parentThreadId?: string;
  principal: string;
  roleBackend?: unknown;
  codingTask: boolean;
  orchestrated: boolean;
  nativeTopology?: boolean;
  enabled: boolean;
}) {
  const storageKey = `octopus:execution-engine:${principal}:${threadId}`;
  const parentStorageKey = parentThreadId
    ? `octopus:execution-engine:${principal}:${parentThreadId}`
    : null;
  const inherited = parentStorageKey ? readPreference(parentStorageKey) : null;
  const [selection, setSelection] = useState(() => ({
    key: storageKey,
    value: readPreference(storageKey) ?? inherited,
  }));
  useEffect(() => {
    const saved = readPreference(storageKey);
    const parent = parentStorageKey ? readPreference(parentStorageKey) : null;
    setSelection({ key: storageKey, value: saved ?? parent });
    if (saved === null && parent !== null) {
      try {
        window.localStorage.setItem(storageKey, parent);
      } catch {
        /* Optional storage. */
      }
    }
  }, [storageKey, parentStorageKey]);
  const savedPreference =
    (selection.key === storageKey
      ? selection.value
      : readPreference(storageKey)) ?? inherited;
  // Default synchronously: waiting for readiness would briefly submit Auto
  // and could send an early request to another provider. Readiness only
  // controls availability, never the user's model/engine ownership.
  const preference =
    savedPreference ??
    (enabled && !orchestrated && roleBackend !== "codex_app_server"
      ? "opencode"
      : "auto");
  const rememberForThread = useCallback(
    (id: string) => {
      setSelection({ key: storageKey, value: preference });
      try {
        window.localStorage.setItem(
          `octopus:execution-engine:${principal}:${id}`,
          preference,
        );
      } catch {
        /* Storage is optional. */
      }
    },
    [principal, preference, storageKey],
  );
  const setPreference = useCallback(
    (value: ExecutionEnginePreference) => {
      setSelection({ key: storageKey, value });
      try {
        window.localStorage.setItem(storageKey, value);
      } catch {
        /* Storage is optional. */
      }
    },
    [storageKey],
  );
  const profile = useQuery({
    queryKey: coderQueryKeys(principal).profile,
    queryFn: ({ signal }) => getCoderModelProfile(signal),
    enabled,
    staleTime: 30_000,
  });
  const codexAvailable = profile.data?.execution_available === true;
  const opencode = useQuery({
    queryKey: ["opencode-status", principal],
    queryFn: async ({ signal }) => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/config/opencode/status`,
        {
          headers: authHeaders(),
          signal,
        },
      );
      if (!response.ok) throw new Error("OpenCode status unavailable");
      return (await response.json()) as {
        available: boolean;
        reason: string | null;
        capability_checks?: EngineCapabilityChecks;
      };
    },
    enabled,
    staleTime: 30_000,
  });
  return {
    preference,
    setPreference,
    rememberForThread,
    engine: previewExecutionEngine({
      preference,
      roleBackend,
      codingTask,
      orchestrated,
      codexAvailable,
    }),
    codexAvailable,
    codexCapabilityChecks: profile.data?.capability_checks,
    opencodeCapabilityChecks: opencode.data?.capability_checks,
    opencodeAvailable: opencode.data?.available === true,
    opencodeUnavailableReason:
      opencode.data?.reason ??
      (opencode.isPending
        ? "正在检查 OpenCode 配置"
        : "暂时无法读取 OpenCode 配置"),
    codexUnavailableReason:
      profile.data?.execution_unavailable_reason ??
      (profile.isError
        ? "configuration_unavailable"
        : profile.isPending
          ? "checking"
          : null),
  };
}
