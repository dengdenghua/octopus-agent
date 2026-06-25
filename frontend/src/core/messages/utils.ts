import type { AIMessage, Message, ToolMessage } from "@/core/api/types";

interface GenericMessageGroup<T = string> {
  type: T;
  id: string | undefined;
  messages: Message[];
}

interface HumanMessageGroup extends GenericMessageGroup<"human"> {}

interface AssistantProcessingGroup extends GenericMessageGroup<"assistant:processing"> {}

interface AssistantMessageGroup extends GenericMessageGroup<"assistant"> {}

interface AssistantPresentFilesGroup extends GenericMessageGroup<"assistant:present-files"> {}

interface AssistantClarificationGroup extends GenericMessageGroup<"assistant:clarification"> {}

interface AssistantSubagentGroup extends GenericMessageGroup<"assistant:subagent"> {}

export type MessageGroup =
  | HumanMessageGroup
  | AssistantProcessingGroup
  | AssistantMessageGroup
  | AssistantPresentFilesGroup
  | AssistantClarificationGroup
  | AssistantSubagentGroup;

export function groupMessages<T>(
  messages: Message[],
  mapper: (group: MessageGroup) => T,
): T[] {
  if (messages.length === 0) {
    return [];
  }

  const groups: MessageGroup[] = [];

  // Returns the last group if it can still accept tool messages
  // (i.e. it's an in-flight processing group, not a terminal human/assistant group).
  function lastOpenGroup() {
    const last = groups[groups.length - 1];
    if (
      last &&
      last.type !== "human" &&
      last.type !== "assistant" &&
      last.type !== "assistant:clarification"
    ) {
      return last;
    }
    return null;
  }

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]!;
    if (isHiddenFromUIMessage(message)) {
      continue;
    }

    if (
      isSupersededApprovalTimeoutMessage(message, messages.slice(index + 1))
    ) {
      continue;
    }

    if (message.name === "todo_reminder") {
      continue;
    }

    if (message.type === "human") {
      groups.push({ id: message.id, type: "human", messages: [message] });
      continue;
    }

    if (message.type === "tool") {
      if (isClarificationToolMessage(message)) {
        // Add to the preceding processing group to preserve tool-call association,
        // then also open a standalone clarification group for prominent display.
        lastOpenGroup()?.messages.push(message);
        groups.push({
          id: message.id,
          type: "assistant:clarification",
          messages: [message],
        });
      } else {
        const open = lastOpenGroup();
        if (open) {
          open.messages.push(message);
        } else {
          // Orphaned tool message (e.g., approval request from PermissionMiddleware).
          // Wrap it in its own processing group instead of dropping it.
          groups.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        }
      }
      continue;
    }

    if (message.type === "ai") {
      if (hasPresentFiles(message)) {
        groups.push({
          id: message.id,
          type: "assistant:present-files",
          messages: [message],
        });
      } else if (hasSubagent(message)) {
        groups.push({
          id: message.id,
          type: "assistant:subagent",
          messages: [message],
        });
      } else if (hasToolCalls(message)) {
        // Tool-call message: render public thinking / execution first.
        // If this same message carries a long final answer, append it
        // after the processing group so the report streams last.
        // Tool-call message → processing group (rendered as ChainOfThought
        // by MessageGroup, which shows the tool steps + a collapsed fold
        // for the reasoning trace).
        const lastGroup = groups[groups.length - 1];
        if (lastGroup?.type !== "assistant:processing") {
          groups.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        } else {
          lastGroup.messages.push(message);
        }
        if (hasContent(message) && isLikelyFinalAnswerContent(message)) {
          groups.push({
            id: message.id,
            type: "assistant",
            messages: [message],
          });
        }
      } else if (hasContent(message)) {
        // Plain AI response (with or without reasoning). Render as a
        // normal assistant message — MessageListItem will draw a
        // collapsed reasoning fold above the content if reasoning is
        // present, so the chain of thought stays accessible without
        // dominating the visible answer.
        groups.push({ id: message.id, type: "assistant", messages: [message] });
      } else if (hasReasoning(message)) {
        // Reasoning-only intermediate message (no content, no tool
        // calls yet). Group as processing so the user sees a fold for
        // the partial chain of thought.
        const lastGroup = groups[groups.length - 1];
        if (lastGroup?.type !== "assistant:processing") {
          groups.push({
            id: message.id,
            type: "assistant:processing",
            messages: [message],
          });
        } else {
          lastGroup.messages.push(message);
        }
      }
    }
  }

  return groups
    .map(mapper)
    .filter((result) => result !== undefined && result !== null) as T[];
}

export function extractTextFromMessage(message: Message) {
  if (typeof message.content === "string") {
    const content =
      splitInlineReasoningFromAIMessage(message)?.content ??
      message.content.trim();
    return message.type === "ai" ? visibleAIContent(content) : content;
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) =>
        content.type === "text"
          ? message.type === "ai"
            ? visibleAIContent(content.text)
            : content.text.trim()
          : "",
      )
      .join("\n")
      .trim();
  }
  return "";
}

const THINK_TAG_RE = /<think>\s*([\s\S]*?)\s*<\/think>/g;

function splitInlineReasoning(content: string) {
  const reasoningParts: string[] = [];
  const cleaned = content
    .replace(THINK_TAG_RE, (_, reasoning: string) => {
      const normalized = reasoning.trim();
      if (normalized) {
        reasoningParts.push(normalized);
      }
      return "";
    })
    .trim();

  return {
    content: cleaned,
    reasoning: reasoningParts.length > 0 ? reasoningParts.join("\n\n") : null,
  };
}

function splitInlineReasoningFromAIMessage(message: Message) {
  if (message.type !== "ai" || typeof message.content !== "string") {
    return null;
  }
  return splitInlineReasoning(message.content);
}

const INTERNAL_TOOL_FENCE_RE =
  /```(?:tool|tools?|tool_call|octopus-tool)\b[\s\S]*?(?:```|$)/gi;
const JSON_COMMAND_TOOL_FENCE_RE =
  /(?:\*\*Task:[^\n]*\*\*\s*)?```json\s*\{\s*"command"\s*:\s*"(?:fs_writer|fs_writen|fs_written|write_file|write_text_file|edit_text_file|str_replace|apply_patch)"[\s\S]*?(?:```|$)/gi;
const BARE_INTERNAL_TOOL_PAYLOAD_RE =
  /^\s*(?:fs_writer|fs_writen|fs_written|write_file|write_text_file|edit_text_file|str_replace|apply_patch)\s*(?:\n|\()\s*[\s\S]*$/i;
const XML_TOOL_CALL_RE = /<tool_call>[\s\S]*?(?:<\/tool_call>|$)/gi;
const XML_TOOL_INVOCATION_RE =
  /<tool_invocation\b[^>]*(?:\/>|>[\s\S]*?(?:<\/tool_invocation>|$))/gi;
const XML_FUNCTION_CALL_RE =
  /<function=(?:fs_writer|fs_writen|fs_written|write_file|write_text_file|edit_text_file|str_replace|apply_patch|deep_research|web_search|search)>[\s\S]*?(?:<\/function>|$)/gi;
const REACT_ACTION_BLOCK_RE =
  /^\s*Action:\s*(?!(?:none|null|n\/a)\s*$).*?(?=\n\s*(?:Thought|Action|Observation|Final Answer):|\s*$)/gims;
const ROLE_NO_OUTPUT_PLACEHOLDER_RE =
  /^\s*\[[^\]\n]{1,80}\]\s*\((?:no output|no visible output|empty output)\)\s*$/i;
const NO_OUTPUT_PLACEHOLDER_RE =
  /^\s*\((?:no output|no visible output|empty output)\)\s*$/i;
const TEAM_ROLE_START_RE =
  /^\s*\[(?:planner|researcher|critic|arbiter|synthesizer|writer|reviewer|analyst|coder|designer|executor|tester)\]\s*starting\s*(?:[·•-]|\u00b7)\s*agent=[^\n]*\n*/i;
const TEAM_ROLE_PREFIX_RE =
  /^\s*\[(?:planner|researcher|critic|arbiter|synthesizer|writer|reviewer|analyst|coder|designer|executor|tester)\]\s*/i;
const NULLISH_PLACEHOLDER_RE = /^\s*(?:null|undefined|none|n\/a)\s*$/i;
const REPEATED_NULL_PLACEHOLDER_RE = /^\s*(?:null\s*)+$/i;

function stripLeakedTeamRoleNoise(content: string): string {
  return content
    .replace(TEAM_ROLE_START_RE, "")
    .replace(TEAM_ROLE_PREFIX_RE, "")
    .trim();
}

function stripReactProtocol(content: string): string {
  let cleaned = content.replace(REACT_ACTION_BLOCK_RE, "").trim();
  const finalAnswer = cleaned.match(/(?:^|\n)Final Answer:\s*([\s\S]*)$/i);
  if (finalAnswer?.[1]?.trim()) {
    cleaned = finalAnswer[1].trim();
  }
  return cleaned
    .replace(
      /^\s*Thought:\s*[\s\S]*?(?=\n\s*Final Answer:|\n\s*Action:|$)/gim,
      "",
    )
    .replace(/^\s*Final Answer:\s*/gim, "")
    .trim();
}

export function stripInternalToolProtocol(content: string): string {
  const cleaned = content
    .replace(INTERNAL_TOOL_FENCE_RE, "")
    .replace(JSON_COMMAND_TOOL_FENCE_RE, "")
    .replace(XML_TOOL_CALL_RE, "")
    .replace(XML_TOOL_INVOCATION_RE, "")
    .replace(XML_FUNCTION_CALL_RE, "")
    .replace(BARE_INTERNAL_TOOL_PAYLOAD_RE, "")
    .trim();
  const reactCleaned = stripReactProtocol(cleaned);
  if (!reactCleaned.startsWith("{")) return reactCleaned;

  try {
    const payload = JSON.parse(reactCleaned) as unknown;
    if (
      payload &&
      typeof payload === "object" &&
      "command" in payload &&
      typeof (payload as { command?: unknown }).command === "string" &&
      /^(?:fs_writer|fs_writen|fs_written|write_file|write_text_file|edit_text_file|str_replace|apply_patch)$/i.test(
        (payload as { command: string }).command,
      )
    ) {
      return "";
    }
  } catch {
    return reactCleaned;
  }

  return reactCleaned;
}

function visibleAIContent(content: string): string {
  const visible = stripLeakedTeamRoleNoise(
    stripInternalToolProtocol(content.trim()),
  );
  return ROLE_NO_OUTPUT_PLACEHOLDER_RE.test(visible) ||
    NO_OUTPUT_PLACEHOLDER_RE.test(visible) ||
    NULLISH_PLACEHOLDER_RE.test(visible) ||
    REPEATED_NULL_PLACEHOLDER_RE.test(visible)
    ? ""
    : visible;
}

export function extractContentFromMessage(message: Message) {
  if (typeof message.content === "string") {
    const content =
      splitInlineReasoningFromAIMessage(message)?.content ??
      message.content.trim();
    return message.type === "ai" ? visibleAIContent(content) : content;
  }
  if (Array.isArray(message.content)) {
    return message.content
      .map((content) => {
        switch (content.type) {
          case "text":
            return message.type === "ai"
              ? visibleAIContent(content.text)
              : content.text.trim();
          case "image_url":
            const imageURL = extractURLFromImageURLContent(content.image_url);
            return `![image](${imageURL})`;
          default:
            return "";
        }
      })
      .join("\n")
      .trim();
  }
  return "";
}

export function extractReasoningContentFromMessage(message: Message) {
  if (message.type !== "ai") {
    return null;
  }
  if (
    message.additional_kwargs &&
    "reasoning_content" in message.additional_kwargs
  ) {
    return message.additional_kwargs.reasoning_content as string | null;
  }
  if (Array.isArray(message.content)) {
    const part = message.content[0];
    if (part && "thinking" in part) {
      return part.thinking as string;
    }
  }
  if (typeof message.content === "string") {
    return splitInlineReasoning(message.content).reasoning;
  }
  return null;
}

export function removeReasoningContentFromMessage(message: Message) {
  if (message.type !== "ai" || !message.additional_kwargs) {
    return;
  }
  delete message.additional_kwargs.reasoning_content;
}

export function extractURLFromImageURLContent(
  content:
    | string
    | {
        url: string;
      },
) {
  if (typeof content === "string") {
    return content;
  }
  return content.url;
}

export function hasContent(message: Message) {
  if (typeof message.content === "string") {
    return extractContentFromMessage(message).length > 0;
  }
  if (Array.isArray(message.content)) {
    return extractContentFromMessage(message).length > 0;
  }
  return false;
}

export function isLikelyFinalAnswerContent(message: Message) {
  const text = extractContentFromMessage(message);
  if (!text) return false;
  if (text.length > 320) return true;
  if (/^#{1,3}\s+\S+/m.test(text)) return true;
  if (/^\s*[一二三四五六七八九十]+[、.．]\s*\S+/m.test(text)) return true;
  if (/^\s*\d+[.)、]\s+\S+/m.test(text) && text.split(/\n+/).length >= 4) {
    return true;
  }
  if (/\|.+\|/.test(text) && /-{3,}/.test(text)) return true;
  return false;
}

export function hasReasoning(message: Message) {
  if (message.type !== "ai") {
    return false;
  }
  if (typeof message.additional_kwargs?.reasoning_content === "string") {
    return true;
  }
  if (Array.isArray(message.content)) {
    const part = message.content[0];
    // Compatible with the Anthropic gateway
    return (part as unknown as { type: "thinking" })?.type === "thinking";
  }
  if (typeof message.content === "string") {
    return splitInlineReasoning(message.content).reasoning !== null;
  }
  return false;
}

export function hasToolCalls(message: Message) {
  if (message.type !== "ai") return false;
  const aiMsg = message as AIMessage;
  return aiMsg.tool_calls != null && aiMsg.tool_calls.length > 0;
}

export function hasPresentFiles(message: Message) {
  if (message.type !== "ai") return false;
  const aiMsg = message as AIMessage;
  return (
    aiMsg.tool_calls?.some((toolCall) => toolCall.name === "present_files") ??
    false
  );
}

export function isClarificationToolMessage(message: Message) {
  return (
    message.type === "tool" &&
    (message.name === "ask_clarification" ||
      message.name === "ask_user_question")
  );
}

export function extractPresentFilesFromMessage(message: Message) {
  if (message.type !== "ai" || !hasPresentFiles(message)) {
    return [];
  }
  const aiMsg = message as AIMessage;
  const files: string[] = [];
  for (const toolCall of aiMsg.tool_calls ?? []) {
    if (
      toolCall.name === "present_files" &&
      Array.isArray(toolCall.args.filepaths)
    ) {
      files.push(...(toolCall.args.filepaths as string[]));
    }
  }
  return files;
}

export function hasSubagent(message: Message) {
  if (message.type !== "ai") return false;
  const aiMsg = message as AIMessage;
  for (const toolCall of aiMsg.tool_calls ?? []) {
    if (toolCall.name === "task") {
      return true;
    }
  }
  return false;
}

export function findToolCallResult(toolCallId: string, messages: Message[]) {
  for (const message of messages) {
    if (
      message.type === "tool" &&
      (message as ToolMessage).tool_call_id === toolCallId
    ) {
      const content = extractTextFromMessage(message);
      if (content) {
        return content;
      }
    }
  }
  return undefined;
}

export function isHiddenFromUIMessage(message: Message) {
  return message.additional_kwargs?.hide_from_ui === true;
}

function isSupersededApprovalTimeoutMessage(
  message: Message,
  laterMessages: Message[],
) {
  if (message.type !== "ai") return false;
  const error = message.additional_kwargs?.error;
  if (!error || typeof error !== "object") return false;
  const text = extractTextFromMessage(message);
  if (
    !/timed out waiting for item\/commandExecution\/requestApproval/i.test(text)
  ) {
    return false;
  }
  return laterMessages.some(
    (later) =>
      (later.type === "ai" || later.type === "assistant") &&
      !later.additional_kwargs?.error &&
      hasContent(later),
  );
}

/**
 * Represents a file stored in message additional_kwargs.files.
 * Used for optimistic UI (uploading state) and structured file metadata.
 */
export interface FileInMessage {
  filename: string;
  size: number; // bytes
  path?: string; // virtual path, may not be set during upload
  status?: "uploading" | "uploaded";
}

/**
 * Strip <uploaded_files> tag from message content.
 * Returns the content with the tag removed.
 */
export function stripUploadedFilesTag(content: string): string {
  return content
    .replace(/<uploaded_files>[\s\S]*?<\/uploaded_files>/g, "")
    .trim();
}

export function parseUploadedFiles(content: string): FileInMessage[] {
  // Match <uploaded_files>...</uploaded_files> tag
  const uploadedFilesRegex = /<uploaded_files>([\s\S]*?)<\/uploaded_files>/;

  const match = content.match(uploadedFilesRegex);

  if (!match) {
    return [];
  }

  const uploadedFilesContent = match[1];

  // Check if it's "No files have been uploaded yet."
  if (uploadedFilesContent?.includes("No files have been uploaded yet.")) {
    return [];
  }

  // Check if the backend reported no new files were uploaded in this message
  if (uploadedFilesContent?.includes("(empty)")) {
    return [];
  }

  // Parse file list
  // Format: - filename (size)\n  Path: /path/to/file
  const fileRegex = /- ([^\n(]+)\s*\(([^)]+)\)\s*\n\s*Path:\s*([^\n]+)/g;
  const files: FileInMessage[] = [];
  let fileMatch;

  while ((fileMatch = fileRegex.exec(uploadedFilesContent ?? "")) !== null) {
    const name = fileMatch[1]?.trim();
    const sizeRaw = fileMatch[2]?.trim();
    const path = fileMatch[3]?.trim();
    if (!name || !path) continue;
    files.push({
      filename: name,
      size: parseInt(sizeRaw ?? "", 10) || 0,
      path,
    });
  }

  return files;
}
