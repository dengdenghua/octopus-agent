import type {
  DesignCanvasDocument,
  DesignCanvasNode,
} from "@/app/workspace/design/canvas-model";
import { listDesignWorkflowStages } from "@/app/workspace/design/canvas-model";

export const DESIGN_CANVAS_CONTEXT_MESSAGE =
  "octopus.design.canvas-context" as const;
export const DESIGN_THREAD_STATE_MESSAGE =
  "octopus.design.thread-state" as const;
export const DESIGN_MODE_CHANGE_MESSAGE = "octopus.design.mode-change" as const;
export const DESIGN_RESULT_MESSAGE = "octopus.design.result" as const;

export type DesignCanvasNodeSummary = Pick<
  DesignCanvasNode,
  "id" | "kind" | "title" | "description" | "tags" | "stage"
>;

export interface DesignCanvasAgentContext {
  version: 1;
  scope: "project" | "creative" | "personal";
  project_id?: string;
  creative_project_id?: string;
  title: string;
  canvas_mode: DesignCanvasDocument["mode"];
  revision: number;
  selected_node_ids: string[];
  selected_nodes: DesignCanvasNodeSummary[];
  nodes: DesignCanvasNodeSummary[];
  edges: Array<{ source: string; target: string }>;
  workflow_stages: ReturnType<typeof listDesignWorkflowStages>;
  active_stage_node_id?: string;
  truncated: boolean;
}

export interface DesignResultMessage {
  type: typeof DESIGN_RESULT_MESSAGE;
  threadId: string;
  messageId: string;
  title: string;
  text: string;
  previewUrl?: string;
  artifacts?: Array<{ path: string; title: string }>;
  targetStageNodeId?: string;
}

const MAX_CONTEXT_NODES = 60;
const MAX_CONTEXT_EDGES = 120;
const MAX_NODE_DESCRIPTION = 500;
const MAX_RESULT_TEXT = 4_000;

function compactNode(node: DesignCanvasNode): DesignCanvasNodeSummary {
  return {
    id: node.id,
    kind: node.kind,
    title: node.title.slice(0, 200),
    description: node.description.slice(0, MAX_NODE_DESCRIPTION),
    tags: node.tags?.slice(0, 12).map((tag) => tag.slice(0, 80)),
    stage: node.stage ? { ...node.stage } : undefined,
  };
}

export function buildDesignCanvasAgentContext({
  document,
  selectedNodeIds,
  revision,
  projectId,
  creativeProjectId,
}: {
  document: DesignCanvasDocument;
  selectedNodeIds: string[];
  revision: number;
  projectId?: string | null;
  creativeProjectId?: string | null;
}): DesignCanvasAgentContext {
  const selected = new Set(selectedNodeIds);
  const selectedNodes = document.nodes.filter((node) => selected.has(node.id));
  const remainingNodes = document.nodes.filter(
    (node) => !selected.has(node.id),
  );
  const nodes = [...selectedNodes, ...remainingNodes]
    .slice(0, MAX_CONTEXT_NODES)
    .map(compactNode);
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = document.edges
    .filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
    )
    .slice(0, MAX_CONTEXT_EDGES)
    .map(({ source, target }) => ({ source, target }));
  const activeStageNodeId = selectedNodes.find((node) => node.stage)?.id;
  return {
    version: 1,
    scope: projectId ? "project" : creativeProjectId ? "creative" : "personal",
    project_id: projectId || undefined,
    creative_project_id: creativeProjectId || undefined,
    title: document.title.slice(0, 240),
    canvas_mode: document.mode,
    revision: Math.max(0, Math.trunc(revision)),
    selected_node_ids: selectedNodes.map((node) => node.id),
    selected_nodes: selectedNodes.slice(0, MAX_CONTEXT_NODES).map(compactNode),
    nodes,
    edges,
    workflow_stages: listDesignWorkflowStages(document),
    active_stage_node_id: activeStageNodeId,
    truncated:
      document.nodes.length > MAX_CONTEXT_NODES ||
      document.edges.length > MAX_CONTEXT_EDGES,
  };
}

export function designWorkspaceRoute({
  threadId,
  projectId,
  projectName,
  creativeProjectId,
  creationSpace,
}: {
  threadId?: string | null;
  projectId?: string | null;
  projectName?: string | null;
  creativeProjectId?: string | null;
  creationSpace?: string | null;
}): string {
  const query = new URLSearchParams();
  if (threadId && threadId !== "new") query.set("thread", threadId);
  if (projectId) query.set("project", projectId);
  if (projectName) query.set("name", projectName);
  if (creativeProjectId) query.set("creative_project", creativeProjectId);
  if (creationSpace) query.set("creation_space", creationSpace);
  const suffix = query.toString();
  return `/workspace/design${suffix ? `?${suffix}` : ""}`;
}

const DESIGN_SCOPE_QUERY_KEYS = [
  "project",
  "name",
  "creative_project",
  "creation_space",
] as const;

/** Start a fresh Design task while retaining its project or creation-space scope. */
export function freshDesignWorkspaceRoute({
  currentSearch,
  taskNonce,
}: {
  currentSearch?: string | URLSearchParams;
  taskNonce: string;
}): string {
  const current =
    currentSearch instanceof URLSearchParams
      ? currentSearch
      : new URLSearchParams(currentSearch || "");
  const query = new URLSearchParams();
  for (const key of DESIGN_SCOPE_QUERY_KEYS) {
    const value = current.get(key)?.trim();
    if (value) query.set(key, value);
  }
  query.set("new_task", taskNonce);
  return `/workspace/design?${query.toString()}`;
}

export function embeddedDesignChatRoute({
  threadId,
  prompt,
  agent,
  projectId,
  creativeProjectId,
  creationSpace,
  parentOrigin,
  targetStageNodeId,
}: {
  threadId?: string | null;
  prompt?: string;
  agent?: string;
  projectId?: string | null;
  creativeProjectId?: string | null;
  creationSpace?: string | null;
  parentOrigin?: string | null;
  targetStageNodeId?: string | null;
}): string {
  const id = threadId && threadId !== "new" ? threadId : "new";
  const query = new URLSearchParams({
    embedded: "design",
    agent_mode: "uxui",
  });
  if (prompt?.trim()) query.set("prompt", prompt.trim());
  if (agent?.trim()) query.set("agent", agent.trim());
  if (projectId) query.set("project", projectId);
  if (creativeProjectId) query.set("creative_project", creativeProjectId);
  if (creationSpace) query.set("creation_space", creationSpace);
  if (parentOrigin) query.set("design_parent_origin", parentOrigin);
  if (targetStageNodeId) query.set("design_stage", targetStageNodeId);
  return `/workspace/realtime/${encodeURIComponent(id)}?${query.toString()}`;
}

export function compactDesignResultText(text: string): string {
  return text.trim().slice(0, MAX_RESULT_TEXT);
}
