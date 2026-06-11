// Public surface for the realtime protocol client.
//
// Import from ``@/core/realtime`` in React components and stores. The
// lower-level modules (client, reducer, envelope) remain reachable for
// test harnesses and non-React consumers.

export type {
  Envelope,
  JsonRpcRequest,
  JsonRpcResponse,
  JsonRpcError,
  JsonRpcId,
  Notification,
} from "./envelope";
export {
  JsonRpcErrorCode,
  isNotification,
  isRequest,
  isResponse,
} from "./envelope";

export type {
  AgentPhaseSnapshot,
  AgentMessageItem,
  ApprovalItem,
  ArtifactItem,
  CommandExecutionItem,
  Conversation,
  ErrorItem,
  FileChange,
  FileChangeItem,
  FileHunk,
  Item,
  ItemBase,
  ItemStatus,
  ItemType,
  McpToolProgress,
  McpToolCallItem,
  PendingApproval,
  PlanItem,
  ReasoningItem,
  SubagentItem,
  ThreadSummary,
  TodoListItem,
  Turn,
  TurnStatus,
  UserMessageItem,
  VerificationItem,
  WorkspaceFocus,
  WorkspaceFocusView,
} from "./items";
export { emptyConversation } from "./items";

export type { ConversationEvent, ReducerOutput } from "./reducer";
export { reduce } from "./reducer";

export type { RealtimeClientOptions } from "./client";
export { RealtimeClient, createDefaultClient } from "./client";

export type {
  UseRealtimeThreadArgs,
  UseRealtimeThreadValue,
} from "./use-realtime-thread";
export { useRealtimeThread } from "./use-realtime-thread";
