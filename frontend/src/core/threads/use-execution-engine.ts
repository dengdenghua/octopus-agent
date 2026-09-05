import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { coderQueryKeys, getCoderModelProfile } from "@/core/coder/api";
import {
  executionEnginePreference,
  previewExecutionEngine,
  type ExecutionEnginePreference,
} from "@/core/realtime/execution-policy";

function readPreference(key: string): ExecutionEnginePreference {
  try {
    return executionEnginePreference(window.localStorage.getItem(key));
  } catch {
    return "auto";
  }
}

export function useExecutionEngine({
  threadId,
  principal,
  roleBackend,
  codingTask,
  orchestrated,
  enabled,
}: {
  threadId: string;
  principal: string;
  roleBackend?: unknown;
  codingTask: boolean;
  orchestrated: boolean;
  enabled: boolean;
}) {
  const storageKey = `octopus:execution-engine:${principal}:${threadId}`;
  const [selection, setSelection] = useState(() => ({
    key: storageKey,
    value: readPreference(storageKey),
  }));
  useEffect(() => {
    setSelection({ key: storageKey, value: readPreference(storageKey) });
  }, [storageKey]);
  const preference =
    selection.key === storageKey ? selection.value : readPreference(storageKey);
  const rememberForThread = useCallback(
    (id: string) => {
      try {
        window.localStorage.setItem(
          `octopus:execution-engine:${principal}:${id}`,
          preference,
        );
      } catch {
        /* Storage is optional. */
      }
    },
    [principal, preference],
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
  const codexAvailable =
    !orchestrated && profile.data?.execution_available === true;
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
    codexUnavailableReason: orchestrated
      ? "orchestration_required"
      : (profile.data?.execution_unavailable_reason ??
        (profile.isError
          ? "configuration_unavailable"
          : profile.isPending
            ? "checking"
            : null)),
  };
}
