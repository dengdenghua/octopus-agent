import { useEffect, useRef } from "react";

import { useThreadChat } from "@/components/workspace/chats";
import { useThreadSettings } from "@/core/settings";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { AgentThreadState } from "@/core/threads";
import type { PromptInputMessage } from "@/core/uploads";
import { extractTextFromMessage } from "@/core/messages/utils";
import { swallow } from "@/core/utils/log";

export function useRegenerateHandler(
  thread: BaseStream<AgentThreadState>,
  sendMessage: (threadId: string, message: PromptInputMessage) => void,
  threadId: string,
) {
  const threadRef = useRef(thread);
  useEffect(() => {
    threadRef.current = thread;
  }, [thread]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { threadId?: string | null }
        | undefined;
      if (detail && detail.threadId && detail.threadId !== threadId) {
        return;
      }
      const currentThread = threadRef.current;
      const lastHuman = currentThread.messages
        .filter((m) => m.type === "human")
        .at(-1);
      if (!lastHuman) return;
      const text = extractTextFromMessage(lastHuman);
      if (text) {
        // A realtime stop is asynchronous and may be rejected by the active
        // worker. Wait for its acknowledgement before regenerating so the new
        // message cannot race the still-running turn. The event listener itself
        // remains synchronous; the detached task owns and consumes failures.
        void (async () => {
          if (currentThread.isLoading) {
            await currentThread.stop();
          }
          sendMessage(threadId, { text, files: [] });
        })().catch((error) => swallow(error, "regenerate-after-stop"));
      }
    };
    window.addEventListener("octopus:regenerate", handler);
    return () => window.removeEventListener("octopus:regenerate", handler);
  }, [sendMessage, threadId]);
}

export function usePlanActionHandler(
  sendMessage: (
    threadId: string,
    message: PromptInputMessage,
    ...args: unknown[]
  ) => void,
  threadId: string,
) {
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | {
            text: string;
            additionalKwargs: Record<string, unknown>;
          }
        | undefined;
      if (detail) {
        void sendMessage(
          threadId,
          { text: detail.text, files: [] },
          undefined,
          { additionalKwargs: detail.additionalKwargs },
        );
      }
    };
    window.addEventListener("octopus:plan-action", handler);
    return () => window.removeEventListener("octopus:plan-action", handler);
  }, [sendMessage, threadId]);
}

export function useThreadPageBase() {
  const { threadId, isNewThread, setIsNewThread, isMock } = useThreadChat();
  const [settings, setSettings] = useThreadSettings(threadId);

  return {
    threadId,
    isNewThread,
    setIsNewThread,
    isMock,
    settings,
    setSettings,
  };
}
