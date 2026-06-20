import { useEffect } from "react";

import { useThreadChat } from "@/components/workspace/chats";
import { useThreadSettings } from "@/core/settings";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { AgentThreadState } from "@/core/threads";
import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { extractTextFromMessage } from "@/core/messages/utils";

export function useRegenerateHandler(
  thread: BaseStream<AgentThreadState>,
  sendMessage: (threadId: string, message: PromptInputMessage) => void,
  threadId: string,
) {
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { threadId?: string | null }
        | undefined;
      if (detail && detail.threadId && detail.threadId !== threadId) {
        return;
      }
      const lastHuman = thread.messages
        .filter((m) => m.type === "human")
        .at(-1);
      if (!lastHuman) return;
      const text = extractTextFromMessage(lastHuman);
      if (text) {
        if (thread.isLoading) {
          thread.stop();
        }
        void sendMessage(threadId, { text, files: [] });
      }
    };
    window.addEventListener("octopus:regenerate", handler);
    return () => window.removeEventListener("octopus:regenerate", handler);
  }, [thread.messages, thread.isLoading, thread.stop, sendMessage, threadId]);
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
