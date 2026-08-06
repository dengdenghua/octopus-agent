import { useParams, useLocation, useSearchParams } from "react-router-dom";
import { useEffect, useRef, useState } from "react";

import { env } from "@/env";
import { uuid } from "@/core/utils/uuid";

type ThreadChatState = {
  threadId: string;
  isNewThread: boolean;
};

function resolveStateFromPath(
  threadIdFromPath: string | undefined,
  isNewPath: boolean,
): ThreadChatState {
  if (isNewPath) {
    return { threadId: uuid(), isNewThread: true };
  }
  return {
    threadId: threadIdFromPath ?? uuid(),
    isNewThread: false,
  };
}

export function useThreadChat() {
  const params = useParams();
  const threadIdFromPath = params.threadId ?? params.thread_id;
  const { key: locationKey, pathname } = useLocation();
  const isNewPath = threadIdFromPath === "new" || pathname.endsWith("/new");

  const [searchParams] = useSearchParams();

  const [state, setState] = useState<ThreadChatState>(() =>
    resolveStateFromPath(threadIdFromPath, isNewPath),
  );

  // Track the last location key we synchronized state for. On every
  // render, check if the location has changed; if so, compute the
  // correct state for the new route and use it for THIS render frame
  // (by returning it directly) while also scheduling a state update.
  // This eliminates the one-frame stale state that was causing old
  // messages to flash when navigating between threads or to /new.
  const lastKeyRef = useRef<string>(locationKey);
  let current: ThreadChatState = state;

  if (lastKeyRef.current !== locationKey) {
    lastKeyRef.current = locationKey;
    current = resolveStateFromPath(threadIdFromPath, isNewPath);
    setState(current);
  }

  // Safety net: if the path-derived values don't match state (e.g.,
  // direct URL manipulation without a locationKey change in some edge
  // cases), reconcile in an effect.
  useEffect(() => {
    const expected = resolveStateFromPath(threadIdFromPath, isNewPath);
    setState((prev) => {
      if (prev.threadId === expected.threadId && prev.isNewThread === expected.isNewThread) {
        return prev;
      }
      return expected;
    });
  }, [locationKey, threadIdFromPath, isNewPath]);

  const setIsNewThread = (v: boolean) => {
    setState((s) => ({ ...s, isNewThread: v }));
  };

  const isMock = env.STATIC_WEBSITE_ONLY && searchParams.get("mock") === "true";
  return {
    threadId: current.threadId,
    isNewThread: current.isNewThread,
    setIsNewThread,
    isMock,
  };
}
