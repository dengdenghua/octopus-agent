import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { useThread } from "@/components/workspace/messages/context";

import {
  loadArtifactContent,
  loadArtifactContentFromToolCall,
  loadOriginalFileContent,
  loadToolCallInfo,
} from "./loader";

export function useArtifactContent({
  filepath,
  threadId,
  enabled,
}: {
  filepath: string;
  threadId: string;
  enabled?: boolean;
}) {
  const isWriteFile = useMemo(() => {
    return filepath.startsWith("write-file:");
  }, [filepath]);
  const { thread, isMock } = useThread();
  const content = useMemo(() => {
    if (isWriteFile) {
      return loadArtifactContentFromToolCall({ url: filepath, thread });
    }
    return null;
  }, [filepath, isWriteFile, thread]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact", filepath, threadId, isMock],
    queryFn: () => {
      return loadArtifactContent({ filepath, threadId, isMock });
    },
    enabled,
    staleTime: 5 * 60 * 1000,
  });
  return {
    content: isWriteFile ? content : data?.content,
    url: isWriteFile ? undefined : data?.url,
    isLoading,
    error,
  };
}

export function useArtifactDiff({
  filepath,
  threadId,
  enabled,
}: {
  filepath: string;
  threadId?: string;
  enabled?: boolean;
}) {
  const isWriteFile = useMemo(() => {
    return filepath.startsWith("write-file:");
  }, [filepath]);
  const { thread } = useThread();

  const toolCallInfo = useMemo(() => {
    if (!isWriteFile) return null;
    return loadToolCallInfo({ url: filepath, thread });
  }, [filepath, isWriteFile, thread]);

  const filePath = toolCallInfo?.path;

  const { data: originalContent, isLoading: isLoadingOriginal } = useQuery({
    queryKey: ["artifact-original", filePath, threadId],
    queryFn: () => loadOriginalFileContent(filePath!, threadId),
    enabled: enabled && isWriteFile && !!filePath,
    staleTime: 5 * 60 * 1000,
  });

  const newContent = useMemo(() => {
    if (!toolCallInfo) return "";
    if (toolCallInfo.name === "str_replace" && toolCallInfo.oldStr) {
      const original = originalContent ?? "";
      return original.replace(toolCallInfo.oldStr, toolCallInfo.newStr ?? "");
    }
    return toolCallInfo.content ?? "";
  }, [toolCallInfo, originalContent]);

  return {
    originalContent: originalContent ?? "",
    newContent,
    toolCallInfo,
    isDiffAvailable: isWriteFile && !!filePath,
    isLoading: isLoadingOriginal,
  };
}
