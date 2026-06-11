import type { Item } from "@/core/realtime";

import { AgentMessageView } from "./agent-message-view";
import { ApprovalView } from "./approval-view";
import { ArtifactView } from "./artifact-view";
import { CommandExecutionView } from "./command-execution-view";
import { ErrorView } from "./error-view";
import { FileChangeView, type DecideHunkFn } from "./file-change-view";
import { McpToolCallView } from "./mcp-tool-call-view";
import { PlanView } from "./plan-view";
import { ReasoningView } from "./reasoning-view";
import { SubagentView } from "./subagent-view";
import { TodoListView } from "./todo-list-view";
import { UserMessageView } from "./user-message-view";
import { VerificationView } from "./verification-view";

export {
  AgentMessageView,
  ApprovalView,
  ArtifactView,
  CommandExecutionView,
  ErrorView,
  FileChangeView,
  McpToolCallView,
  PlanView,
  ReasoningView,
  SubagentView,
  TodoListView,
  UserMessageView,
  VerificationView,
};
export type { DecideHunkFn };

/**
 * Single dispatch point for rendering any conversation `Item`.
 *
 * The realtime page maps `turn.items` over this; the switch narrows
 * on the discriminated `type` field so each branch passes a precisely-
 * typed item to its dedicated view. New `Item` variants added in
 * `core/realtime/items.ts` will fail the exhaustiveness check below
 * (TypeScript flags the `_exhaustive: never` line) until a case is
 * added here, which is the whole point of routing through this hub.
 *
 * `onDecideHunk` is only consumed by `FileChangeView`; the other
 * branches ignore it. We pass it through unconditionally so callers
 * don't have to type-narrow before rendering.
 */
export function ItemView({
  item,
  onDecideHunk,
}: {
  item: Item;
  onDecideHunk: DecideHunkFn;
}) {
  switch (item.type) {
    case "userMessage":
    case "steeringUserMessage":
      return <UserMessageView item={item} />;
    case "agentMessage":
      return <AgentMessageView item={item} />;
    case "reasoning":
      return <ReasoningView item={item} />;
    case "plan":
      return <PlanView item={item} />;
    case "todo-list":
      return <TodoListView item={item} />;
    case "commandExecution":
      return <CommandExecutionView item={item} />;
    case "fileChange":
      return <FileChangeView item={item} onDecide={onDecideHunk} />;
    case "mcpToolCall":
      return <McpToolCallView item={item} />;
    case "subagent":
      return <SubagentView item={item} />;
    case "approval":
      return <ApprovalView item={item} />;
    case "verification":
      return <VerificationView item={item} />;
    case "artifact":
      return <ArtifactView item={item} />;
    case "error":
      return <ErrorView item={item} />;
    default: {
      // Exhaustiveness sentinel — TS errors here when a new Item
      // variant is added but not wired up above.
      const _exhaustive: never = item;
      void _exhaustive;
      return null;
    }
  }
}
