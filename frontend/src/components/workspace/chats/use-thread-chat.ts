import { useParams, useLocation, useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";

import { env } from "@/env";
import { uuid } from "@/core/utils/uuid";

export function useThreadChat() {
  const params = useParams();
  const threadIdFromPath = params.threadId ?? params.thread_id;
  const { pathname } = useLocation();
  const isNewPath = threadIdFromPath === "new" || pathname.endsWith("/new");

  const [searchParams] = useSearchParams();
  const [threadId, setThreadId] = useState(() => {
    return isNewPath ? uuid() : (threadIdFromPath ?? uuid());
  });

  const [isNewThread, setIsNewThread] = useState(() => isNewPath);

  useEffect(() => {
    if (pathname.endsWith("/new")) {
      setIsNewThread(true);
      setThreadId(uuid());
    } else if (threadIdFromPath && threadIdFromPath !== "new") {
      setIsNewThread(false);
      setThreadId(threadIdFromPath);
    }
  }, [pathname, threadIdFromPath]);

  const isMock = env.STATIC_WEBSITE_ONLY && searchParams.get("mock") === "true";
  return { threadId, isNewThread, setIsNewThread, isMock };
}
