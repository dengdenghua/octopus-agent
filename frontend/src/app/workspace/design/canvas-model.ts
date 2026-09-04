export type DesignCanvasMode = "freeform" | "workflow";
export type DesignStageStatus =
  | "pending"
  | "running"
  | "review"
  | "approved"
  | "failed"
  | "skipped";
export type DesignNodeKind =
  | "brief"
  | "agent"
  | "skill"
  | "plugin"
  | "frame"
  | "component"
  | "token"
  | "preview"
  | "text"
  | "table"
  | "image"
  | "video"
  | "audio"
  | "file"
  | "placeholder"
  | "group"
  | "sticker"
  | "director"
  | "editor"
  | "comfyui"
  | "output";

export interface DesignCanvasNode {
  id: string;
  kind: DesignNodeKind;
  title: string;
  description: string;
  x: number;
  y: number;
  positions?: Partial<Record<DesignCanvasMode, { x: number; y: number }>>;
  childIds?: string[];
  color?: string;
  emoji?: string;
  attachedTo?: string;
  copyOrdinal?: number;
  tags?: string[];
  width?: number;
  height?: number;
  binding?: {
    type: "agent" | "skill" | "plugin" | "workflow" | "asset";
    id: string;
  };
  asset?: {
    id: string;
    kind: string;
    path?: string;
    url?: string;
    projectId?: string;
    source?: string;
  };
  /** Durable provenance for content returned by the embedded Design agent. */
  origin?: {
    type: "agent-result";
    threadId: string;
    messageId: string;
  };
  /** Stable execution identity and review state for workflow-stage nodes. */
  stage?: {
    id: string;
    order: number;
    status: DesignStageStatus;
    attempt: number;
    reviewRequired?: boolean;
    updatedAt?: string;
    lastError?: string;
  };
}

export interface DesignCanvasEdge {
  id: string;
  source: string;
  target: string;
}

export interface DesignCanvasDocument {
  version: 1;
  title: string;
  mode: DesignCanvasMode;
  nodes: DesignCanvasNode[];
  edges: DesignCanvasEdge[];
}

export interface DesignCanvasClipboard {
  nodes: DesignCanvasNode[];
  edges: DesignCanvasEdge[];
  inheritedEdges?: DesignCanvasEdge[];
}

export interface DesignCanvasDeletionPlan {
  nodeIds: string[];
  edgeIds: string[];
  highBlast: boolean;
}

export const DESIGN_CANVAS_STORAGE_KEY = "octopus:design-canvas:v1";

export interface DesignCanvasMergeResult {
  document: DesignCanvasDocument;
  conflicts: string[];
}

export interface DesignWorkflowStageSummary {
  id: string;
  nodeId: string;
  title: string;
  order: number;
  status: DesignStageStatus;
  attempt: number;
  reviewRequired: boolean;
  dependencies: string[];
}

export const DEFAULT_DESIGN_CANVAS: DesignCanvasDocument = {
  version: 1,
  title: "品牌发布创作流",
  mode: "workflow",
  nodes: [
    {
      id: "brief",
      kind: "brief",
      title: "创作需求",
      description: "面向年轻用户，完成新品发布的视觉内容套件",
      x: 40,
      y: 160,
    },
    {
      id: "agent",
      kind: "agent",
      title: "视觉导演",
      description: "理解品牌与受众，拆解镜头、版式和内容节奏",
      x: 340,
      y: 80,
    },
    {
      id: "skill",
      kind: "skill",
      title: "图像生成技能",
      description: "生成主视觉、社媒配图与多尺寸变体",
      x: 340,
      y: 270,
    },
    {
      id: "output",
      kind: "output",
      title: "交付物",
      description: "海报 · 短视频 · 营销文案 · 发布清单",
      x: 660,
      y: 160,
    },
  ],
  edges: [
    { id: "brief-agent", source: "brief", target: "agent" },
    { id: "brief-skill", source: "brief", target: "skill" },
    { id: "agent-output", source: "agent", target: "output" },
    { id: "skill-output", source: "skill", target: "output" },
  ],
};

/** Original, provider-neutral drama workflow. The stages mirror a real
 * production dependency chain without copying any vendor prompt or asset. */
export function createDramaSeriesCanvas(): DesignCanvasDocument {
  const stages: Array<
    Omit<DesignCanvasNode, "stage"> & {
      stage: NonNullable<DesignCanvasNode["stage"]>;
    }
  > = [
    {
      id: "drama-script",
      kind: "text",
      title: "01 剧本与集数范围",
      description:
        "确认目标集、时长、对白和事实边界；有原剧本时只做结构化，不擅自改写。",
      x: 60,
      y: 150,
      binding: { type: "skill", id: "creative-microdrama-writer" },
      stage: {
        id: "script",
        order: 1,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
    {
      id: "drama-production-plan",
      kind: "table",
      title: "02 制作方案",
      description:
        "锁定真人/漫剧、时代地域、画幅、语言、风格、模型和声音方案。",
      x: 360,
      y: 150,
      stage: {
        id: "production-plan",
        order: 2,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
    {
      id: "drama-asset-anchors",
      kind: "image",
      title: "03 角色与场景锚点",
      description:
        "建立角色脸型、体态、服装、道具和场景多角度参考，作为连续性基准。",
      x: 660,
      y: 150,
      binding: { type: "skill", id: "creative-multi-angle-render" },
      stage: {
        id: "asset-anchors",
        order: 3,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
    {
      id: "drama-storyboard",
      kind: "image",
      title: "04 分镜与站位",
      description:
        "按对白和动作计算镜头时长，记录人物站位、视线与轴线；单镜头组不超过 15 秒。",
      x: 960,
      y: 150,
      binding: { type: "skill", id: "creative-storyboard-assets" },
      stage: {
        id: "storyboard",
        order: 4,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
    {
      id: "drama-keyframes",
      kind: "director",
      title: "05 场景关键帧",
      description: "在导演台复核构图、角色 blocking、机位和动作连续性。",
      x: 1260,
      y: 150,
      binding: { type: "plugin", id: "director-stage" },
      stage: {
        id: "keyframes",
        order: 5,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
    {
      id: "drama-visual-generation",
      kind: "comfyui",
      title: "06 镜头生成",
      description: "按已通过的锚点与关键帧逐镜生成；失败时只重跑对应镜头。",
      x: 1560,
      y: 150,
      stage: {
        id: "visual-generation",
        order: 6,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
    {
      id: "drama-post",
      kind: "editor",
      title: "07 剪辑与交付",
      description:
        "完成节奏、配音、字幕、音乐、转场和导出，并以真实快照/成片复核。",
      x: 1860,
      y: 150,
      binding: { type: "plugin", id: "clip-studio" },
      stage: {
        id: "post",
        order: 7,
        status: "pending",
        attempt: 0,
        reviewRequired: true,
      },
    },
  ];
  const output: DesignCanvasNode = {
    id: "drama-delivery",
    kind: "output",
    title: "剧集交付",
    description: "已审核的剧本、资产锚点、分镜、镜头和最终成片。",
    x: 2160,
    y: 150,
  };
  const nodes: DesignCanvasNode[] = [...stages, output];
  return {
    version: 1,
    title: "AI 漫剧制作流",
    mode: "workflow",
    nodes,
    edges: nodes.slice(0, -1).map((node, index) => ({
      id: `${node.id}-${nodes[index + 1]!.id}`,
      source: node.id,
      target: nodes[index + 1]!.id,
    })),
  };
}

export function listDesignWorkflowStages(
  document: DesignCanvasDocument,
): DesignWorkflowStageSummary[] {
  const stageByNodeId = new Map(
    document.nodes
      .filter((node) => node.stage)
      .map((node) => [node.id, node.stage!.id]),
  );
  return document.nodes
    .filter(
      (
        node,
      ): node is DesignCanvasNode & {
        stage: NonNullable<DesignCanvasNode["stage"]>;
      } => Boolean(node.stage),
    )
    .map((node) => ({
      id: node.stage.id,
      nodeId: node.id,
      title: node.title,
      order: node.stage.order,
      status: node.stage.status,
      attempt: node.stage.attempt,
      reviewRequired: node.stage.reviewRequired !== false,
      dependencies: document.edges
        .filter((edge) => edge.target === node.id)
        .map((edge) => stageByNodeId.get(edge.source))
        .filter((id): id is string => Boolean(id)),
    }))
    .sort((left, right) => left.order - right.order);
}

export function designStageBlockers(
  document: DesignCanvasDocument,
  nodeId: string,
): DesignWorkflowStageSummary[] {
  const stages = listDesignWorkflowStages(document);
  const target = stages.find((stage) => stage.nodeId === nodeId);
  if (!target) return [];
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  return target.dependencies
    .map((id) => byId.get(id))
    .filter(
      (stage): stage is DesignWorkflowStageSummary =>
        Boolean(stage) &&
        stage!.status !== "approved" &&
        stage!.status !== "skipped",
    );
}

export function setDesignStageStatus(
  document: DesignCanvasDocument,
  nodeId: string,
  status: DesignStageStatus,
  options?: { error?: string; incrementAttempt?: boolean },
): DesignCanvasDocument {
  let changed = false;
  const updatedAt = new Date().toISOString();
  const nodes = document.nodes.map((node) => {
    if (node.id !== nodeId || !node.stage) return node;
    changed = true;
    return {
      ...node,
      stage: {
        ...node.stage,
        status,
        attempt:
          node.stage.attempt + (options?.incrementAttempt === true ? 1 : 0),
        updatedAt,
        lastError: options?.error,
      },
    };
  });
  return changed ? { ...document, nodes } : document;
}

/** Start or retry one stage. Accepted upstream work stays locked while every
 * downstream stage becomes pending because its inputs may have changed. */
export function beginDesignStage(
  document: DesignCanvasDocument,
  nodeId: string,
): DesignCanvasDocument {
  if (designStageBlockers(document, nodeId).length > 0) return document;
  const downstream = new Set<string>();
  const queue = [nodeId];
  while (queue.length > 0) {
    const source = queue.shift()!;
    for (const edge of document.edges) {
      if (edge.source !== source || downstream.has(edge.target)) continue;
      downstream.add(edge.target);
      queue.push(edge.target);
    }
  }
  const updatedAt = new Date().toISOString();
  return {
    ...document,
    nodes: document.nodes.map((node) => {
      if (!node.stage) return node;
      if (node.id === nodeId) {
        return {
          ...node,
          stage: {
            ...node.stage,
            status: "running",
            attempt: node.stage.attempt + 1,
            updatedAt,
            lastError: undefined,
          },
        };
      }
      if (!downstream.has(node.id)) return node;
      return {
        ...node,
        stage: {
          ...node.stage,
          status: "pending",
          updatedAt,
          lastError: undefined,
        },
      };
    }),
  };
}

export function designStageRunPrompt(
  document: DesignCanvasDocument,
  nodeId: string,
): string {
  const stages = listDesignWorkflowStages(document);
  const target = stages.find((stage) => stage.nodeId === nodeId);
  const node = document.nodes.find((item) => item.id === nodeId);
  if (!target || !node) return designCanvasRunPrompt(document);
  const approved = stages
    .filter(
      (stage) => stage.status === "approved" || stage.status === "skipped",
    )
    .map((stage) => `${stage.id}(${stage.status})`)
    .join("、");
  const attempt =
    target.status === "running" ? target.attempt : target.attempt + 1;
  return `只执行创作画布「${document.title}」的当前阶段，不要重做其他已通过阶段。\n\n当前阶段：${target.id}\n稳定节点 ID：${target.nodeId}\n阶段目标：${node.title}：${node.description}\n本次尝试：${Math.max(1, attempt)}\n已锁定阶段：${approved || "无"}\n直接完成该阶段所需工作并给出可审核结果；需要修改剪辑、导演台或 ComfyUI 时调用对应的真实工具。不要虚构画布已被修改。`;
}

export function parseDesignCanvas(value: string | null): DesignCanvasDocument {
  if (!value) return structuredClone(DEFAULT_DESIGN_CANVAS);
  try {
    const parsed = JSON.parse(value) as Partial<DesignCanvasDocument>;
    if (
      parsed.version !== 1 ||
      !Array.isArray(parsed.nodes) ||
      !Array.isArray(parsed.edges)
    ) {
      return structuredClone(DEFAULT_DESIGN_CANVAS);
    }
    return {
      version: 1,
      title:
        typeof parsed.title === "string" && parsed.title.trim()
          ? parsed.title
          : DEFAULT_DESIGN_CANVAS.title,
      mode: parsed.mode === "freeform" ? "freeform" : "workflow",
      nodes: parsed.nodes.filter(isDesignCanvasNode).map((node) => ({
        ...node,
        stage: isDesignStage(node.stage) ? node.stage : undefined,
      })),
      edges: parsed.edges.filter(isDesignCanvasEdge),
    };
  } catch {
    return structuredClone(DEFAULT_DESIGN_CANVAS);
  }
}

const DESIGN_STAGE_STATUSES = new Set<DesignStageStatus>([
  "pending",
  "running",
  "review",
  "approved",
  "failed",
  "skipped",
]);

function isDesignStage(
  value: unknown,
): value is NonNullable<DesignCanvasNode["stage"]> {
  if (!value || typeof value !== "object") return false;
  const stage = value as Partial<NonNullable<DesignCanvasNode["stage"]>>;
  return (
    typeof stage.id === "string" &&
    stage.id.length > 0 &&
    stage.id.length <= 160 &&
    typeof stage.order === "number" &&
    Number.isInteger(stage.order) &&
    stage.order >= 0 &&
    typeof stage.attempt === "number" &&
    Number.isInteger(stage.attempt) &&
    stage.attempt >= 0 &&
    typeof stage.status === "string" &&
    DESIGN_STAGE_STATUSES.has(stage.status as DesignStageStatus)
  );
}

function isDesignCanvasNode(value: unknown): value is DesignCanvasNode {
  if (!value || typeof value !== "object") return false;
  const node = value as Partial<DesignCanvasNode>;
  return (
    typeof node.id === "string" &&
    typeof node.kind === "string" &&
    typeof node.title === "string" &&
    typeof node.description === "string" &&
    typeof node.x === "number" &&
    Number.isFinite(node.x) &&
    typeof node.y === "number" &&
    Number.isFinite(node.y)
  );
}

function isDesignCanvasEdge(value: unknown): value is DesignCanvasEdge {
  if (!value || typeof value !== "object") return false;
  const edge = value as Partial<DesignCanvasEdge>;
  return (
    typeof edge.id === "string" &&
    typeof edge.source === "string" &&
    typeof edge.target === "string"
  );
}

export function appendDesignNode(
  document: DesignCanvasDocument,
  node: DesignCanvasNode,
  sourceId?: string | null,
): DesignCanvasDocument {
  const source = sourceId
    ? document.nodes.find((item) => item.id === sourceId)
    : undefined;
  const edges = source
    ? [
        ...document.edges,
        {
          id: `${source.id}-${node.id}`,
          source: source.id,
          target: node.id,
        },
      ]
    : document.edges;
  return { ...document, nodes: [...document.nodes, node], edges };
}

export function connectDesignNodes(
  document: DesignCanvasDocument,
  sourceId: string,
  targetId: string,
): DesignCanvasDocument {
  if (sourceId === targetId) return document;
  const source = document.nodes.find((node) => node.id === sourceId);
  const target = document.nodes.find((node) => node.id === targetId);
  if (!source || !target) return document;
  if (
    source.kind === "group" ||
    source.kind === "sticker" ||
    source.kind === "placeholder" ||
    target.kind === "group" ||
    target.kind === "sticker" ||
    target.kind === "placeholder"
  )
    return document;
  if (
    document.edges.some(
      (edge) => edge.source === sourceId && edge.target === targetId,
    )
  )
    return document;
  const reachable = new Set<string>([targetId]);
  const queue = [targetId];
  while (queue.length) {
    const current = queue.shift()!;
    for (const edge of document.edges) {
      if (edge.source !== current || reachable.has(edge.target)) continue;
      reachable.add(edge.target);
      queue.push(edge.target);
    }
  }
  if (reachable.has(sourceId)) return document;
  return {
    ...document,
    edges: [
      ...document.edges,
      {
        id: `${sourceId}-${targetId}-${Date.now().toString(36)}`,
        source: sourceId,
        target: targetId,
      },
    ],
  };
}

export function disconnectDesignEdge(
  document: DesignCanvasDocument,
  edgeId: string,
): DesignCanvasDocument {
  return {
    ...document,
    edges: document.edges.filter((edge) => edge.id !== edgeId),
  };
}

const HIGH_BLAST_DELETE_MIN_ELEMENTS = 10;
const HIGH_BLAST_DELETE_REMAINING_RATIO = 0.5;

function isHighBlastDeletion(currentCount: number, incomingCount: number) {
  return (
    currentCount >= HIGH_BLAST_DELETE_MIN_ELEMENTS &&
    incomingCount < currentCount * HIGH_BLAST_DELETE_REMAINING_RATIO
  );
}

export function planDesignSelectionDeletion(
  document: DesignCanvasDocument,
  nodeIds: string[],
): DesignCanvasDeletionPlan {
  const removing = new Set(nodeIds);
  let expanded = true;
  while (expanded) {
    expanded = false;
    for (const node of document.nodes) {
      if (node.kind === "group" && removing.has(node.id)) {
        for (const childId of node.childIds ?? []) {
          if (!removing.has(childId)) {
            removing.add(childId);
            expanded = true;
          }
        }
      }
      if (
        node.kind === "sticker" &&
        node.attachedTo &&
        removing.has(node.attachedTo) &&
        !removing.has(node.id)
      ) {
        removing.add(node.id);
        expanded = true;
      }
    }
  }
  const edgeIds = document.edges
    .filter((edge) => removing.has(edge.source) || removing.has(edge.target))
    .map((edge) => edge.id);
  return {
    nodeIds: Array.from(removing),
    edgeIds,
    highBlast:
      isHighBlastDeletion(
        document.nodes.length,
        document.nodes.length - removing.size,
      ) ||
      isHighBlastDeletion(
        document.edges.length,
        document.edges.length - edgeIds.length,
      ),
  };
}

export function deleteDesignSelection(
  document: DesignCanvasDocument,
  nodeIds: string[],
): DesignCanvasDocument {
  const plan = planDesignSelectionDeletion(document, nodeIds);
  const removing = new Set(plan.nodeIds);
  return {
    ...document,
    nodes: document.nodes
      .filter((node) => !removing.has(node.id))
      .map((node) =>
        node.kind === "group"
          ? {
              ...node,
              childIds: (node.childIds ?? []).filter(
                (childId) => !removing.has(childId),
              ),
            }
          : node,
      ),
    edges: document.edges.filter(
      (edge) => !removing.has(edge.source) && !removing.has(edge.target),
    ),
  };
}

export function copyDesignSelection(
  document: DesignCanvasDocument,
  nodeIds: string[],
): DesignCanvasClipboard {
  const selected = new Set(nodeIds);
  document.nodes.forEach((node) => {
    if (node.kind === "group" && selected.has(node.id))
      node.childIds?.forEach((id) => selected.add(id));
  });
  document.nodes.forEach((node) => {
    if (
      node.kind === "sticker" &&
      node.attachedTo &&
      selected.has(node.attachedTo)
    )
      selected.add(node.id);
  });
  return {
    nodes: document.nodes
      .filter((node) => selected.has(node.id))
      .map((node) => structuredClone(node)),
    edges: document.edges
      .filter((edge) => selected.has(edge.source) && selected.has(edge.target))
      .map((edge) => structuredClone(edge)),
    inheritedEdges: document.edges
      .filter((edge) => !selected.has(edge.source) && selected.has(edge.target))
      .map((edge) => structuredClone(edge)),
  };
}

export function pasteDesignSelection(
  document: DesignCanvasDocument,
  clipboard: DesignCanvasClipboard,
  suffix: string,
  offset = 32,
  targetCenter?: { x: number; y: number },
): { document: DesignCanvasDocument; nodeIds: string[] } {
  if (!clipboard.nodes.length) return { document, nodeIds: [] };
  const visibleNodes = clipboard.nodes.filter(
    (node) => node.kind !== "sticker",
  );
  const boundsNodes = visibleNodes.length ? visibleNodes : clipboard.nodes;
  const minX = Math.min(...boundsNodes.map((node) => node.x));
  const minY = Math.min(...boundsNodes.map((node) => node.y));
  const maxX = Math.max(
    ...boundsNodes.map((node) => node.x + (node.width ?? 236)),
  );
  const maxY = Math.max(
    ...boundsNodes.map((node) => node.y + (node.height ?? 132)),
  );
  const shiftX = targetCenter ? targetCenter.x - (minX + maxX) / 2 : offset;
  const shiftY = targetCenter ? targetCenter.y - (minY + maxY) / 2 : offset;
  const ids = new Map(
    clipboard.nodes.map((node) => [node.id, `${node.id}-copy-${suffix}`]),
  );
  const nextComfyOrdinal = new Map<string, number>();
  for (const node of document.nodes) {
    if (node.kind !== "comfyui" || node.binding?.type !== "workflow") continue;
    nextComfyOrdinal.set(
      node.binding.id,
      Math.max(
        nextComfyOrdinal.get(node.binding.id) ?? 0,
        node.copyOrdinal ?? 0,
      ),
    );
  }
  const nodes = clipboard.nodes.map((node) => {
    const x = node.x + shiftX;
    const y = node.y + shiftY;
    const positions = node.positions
      ? Object.fromEntries(
          Object.entries(node.positions).map(([mode, position]) => [
            mode,
            position
              ? { x: position.x + shiftX, y: position.y + shiftY }
              : position,
          ]),
        )
      : undefined;
    const comfyWorkflowId =
      node.kind === "comfyui" && node.binding?.type === "workflow"
        ? node.binding.id
        : null;
    const copyOrdinal = comfyWorkflowId
      ? (nextComfyOrdinal.get(comfyWorkflowId) ?? 0) + 1
      : undefined;
    if (comfyWorkflowId && copyOrdinal)
      nextComfyOrdinal.set(comfyWorkflowId, copyOrdinal);
    const baseTitle = node.copyOrdinal
      ? node.title.replace(/ 副本 \d+$/, "")
      : node.title;
    return {
      ...structuredClone(node),
      id: ids.get(node.id)!,
      title: copyOrdinal
        ? `${baseTitle} 副本 ${copyOrdinal}`
        : node.kind === "group" || node.kind === "sticker"
          ? node.title
          : `${node.title} 副本`,
      copyOrdinal,
      x,
      y,
      positions,
      childIds: node.childIds
        ?.map((id) => ids.get(id))
        .filter((id): id is string => Boolean(id)),
      attachedTo: node.attachedTo ? ids.get(node.attachedTo) : undefined,
    } satisfies DesignCanvasNode;
  });
  const edges = [
    ...clipboard.edges,
    ...(clipboard.inheritedEdges ?? []),
  ].flatMap((edge, index) => {
    const source = ids.get(edge.source) ?? edge.source;
    const target = ids.get(edge.target);
    return source && target
      ? [
          {
            ...structuredClone(edge),
            id: `${source}-${target}-${suffix}-${index}`,
            source,
            target,
          },
        ]
      : [];
  });
  return {
    document: {
      ...document,
      nodes: [...document.nodes, ...nodes],
      edges: [...document.edges, ...edges],
    },
    nodeIds: nodes.map((node) => node.id),
  };
}

/** MiniMax keeps freeform exploration and executable workflow layouts apart.
 * The visible x/y pair is the active layout so existing renderers and persisted
 * v1 documents remain compatible; positions retains the inactive layout. */
export function switchDesignCanvasMode(
  document: DesignCanvasDocument,
  mode: DesignCanvasMode,
): DesignCanvasDocument {
  if (document.mode === mode) return document;
  return {
    ...document,
    mode,
    nodes: document.nodes.map((node) => {
      const positions = {
        ...node.positions,
        [document.mode]: { x: node.x, y: node.y },
      };
      const target = positions[mode] ?? { x: node.x, y: node.y };
      return { ...node, positions, x: target.x, y: target.y };
    }),
  };
}

export function groupDesignNodes(
  document: DesignCanvasDocument,
  nodeIds: string[],
  groupId: string,
): DesignCanvasDocument {
  const selected = document.nodes.filter(
    (node) => nodeIds.includes(node.id) && node.kind !== "group",
  );
  if (selected.length < 2) return document;
  const minX = Math.min(...selected.map((node) => node.x));
  const minY = Math.min(...selected.map((node) => node.y));
  const maxX = Math.max(
    ...selected.map((node) => node.x + (node.width ?? 236)),
  );
  const maxY = Math.max(
    ...selected.map((node) => node.y + (node.height ?? 122)),
  );
  const group: DesignCanvasNode = {
    id: groupId,
    kind: "group",
    title: "节点组",
    description: `${selected.length} 个节点`,
    childIds: selected.map((node) => node.id),
    color: "purple",
    x: minX - 24,
    y: minY - 40,
    width: maxX - minX + 48,
    height: maxY - minY + 64,
    positions: {
      [document.mode]: { x: minX - 24, y: minY - 40 },
    },
  };
  return { ...document, nodes: [group, ...document.nodes] };
}

export function ungroupDesignNode(
  document: DesignCanvasDocument,
  groupId: string,
): DesignCanvasDocument {
  const group = document.nodes.find(
    (node) => node.id === groupId && node.kind === "group",
  );
  if (!group) return document;
  return {
    ...document,
    nodes: document.nodes.filter((node) => node.id !== groupId),
    edges: document.edges.filter(
      (edge) => edge.source !== groupId && edge.target !== groupId,
    ),
  };
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function mergeValue<T>(
  label: string,
  base: T | undefined,
  local: T | undefined,
  remote: T | undefined,
  conflicts: string[],
): T | undefined {
  if (sameValue(local, remote)) return local;
  if (sameValue(local, base)) return remote;
  if (sameValue(remote, base)) return local;
  conflicts.push(label);
  // A conflict is never written automatically. Keeping the local version in
  // the preview lets the member explicitly choose "merge and save" later.
  return local;
}

function mergeEntities<T extends { id: string }>(
  label: string,
  base: T[],
  local: T[],
  remote: T[],
  conflicts: string[],
): T[] {
  const baseById = new Map(base.map((item) => [item.id, item]));
  const localById = new Map(local.map((item) => [item.id, item]));
  const remoteById = new Map(remote.map((item) => [item.id, item]));
  const ids = [
    ...local.map((item) => item.id),
    ...remote.map((item) => item.id).filter((id) => !localById.has(id)),
    ...base
      .map((item) => item.id)
      .filter((id) => !localById.has(id) && !remoteById.has(id)),
  ];
  return ids.flatMap((id) => {
    const merged = mergeValue(
      `${label}:${id}`,
      baseById.get(id),
      localById.get(id),
      remoteById.get(id),
      conflicts,
    );
    return merged ? [merged] : [];
  });
}

/** Three-way merge for project canvases. Disjoint node/edge edits merge
 * automatically; edits to the same entity are reported for explicit review. */
export function mergeDesignCanvases(
  base: DesignCanvasDocument,
  local: DesignCanvasDocument,
  remote: DesignCanvasDocument,
): DesignCanvasMergeResult {
  const conflicts: string[] = [];
  return {
    document: {
      version: 1,
      title:
        mergeValue("title", base.title, local.title, remote.title, conflicts) ??
        local.title,
      mode:
        mergeValue("mode", base.mode, local.mode, remote.mode, conflicts) ??
        local.mode,
      nodes: mergeEntities(
        "node",
        base.nodes,
        local.nodes,
        remote.nodes,
        conflicts,
      ),
      edges: mergeEntities(
        "edge",
        base.edges,
        local.edges,
        remote.edges,
        conflicts,
      ),
    },
    conflicts,
  };
}

export type DesignCanvasTidyMode =
  | "connections"
  | "media"
  | "grid"
  | "horizontal"
  | "vertical";

export function tidyDesignCanvas(
  document: DesignCanvasDocument,
  mode: DesignCanvasTidyMode = "connections",
): DesignCanvasDocument {
  if (document.nodes.length === 0) return document;
  const groups = document.nodes.filter((node) => node.kind === "group");
  const stickers = document.nodes.filter((node) => node.kind === "sticker");
  if (groups.length > 0 || stickers.length > 0) {
    const tidied = tidyDesignCanvas(
      {
        ...document,
        nodes: document.nodes.filter(
          (node) => node.kind !== "group" && node.kind !== "sticker",
        ),
      },
      mode,
    );
    const reconciled = groups.map((group) => {
      const children = tidied.nodes.filter((node) =>
        group.childIds?.includes(node.id),
      );
      if (!children.length) return group;
      const minX = Math.min(...children.map((node) => node.x));
      const minY = Math.min(...children.map((node) => node.y));
      const maxX = Math.max(
        ...children.map((node) => node.x + (node.width ?? 236)),
      );
      const maxY = Math.max(
        ...children.map((node) => node.y + (node.height ?? 122)),
      );
      const x = minX - 24;
      const y = minY - 40;
      return {
        ...group,
        x,
        y,
        width: maxX - minX + 48,
        height: maxY - minY + 64,
        positions: {
          ...group.positions,
          [document.mode]: { x, y },
        },
      };
    });
    const movedStickers = stickers.map((sticker) => {
      if (!sticker.attachedTo) return sticker;
      const before = document.nodes.find(
        (node) => node.id === sticker.attachedTo,
      );
      const after = tidied.nodes.find((node) => node.id === sticker.attachedTo);
      if (!before || !after) return sticker;
      const x = sticker.x + after.x - before.x;
      const y = sticker.y + after.y - before.y;
      return {
        ...sticker,
        x,
        y,
        positions: {
          ...sticker.positions,
          [document.mode]: { x, y },
        },
      };
    });
    return {
      ...tidied,
      nodes: [...reconciled, ...movedStickers, ...tidied.nodes],
    };
  }
  const ordered = [...document.nodes];
  if (mode === "media") {
    const order: DesignNodeKind[] = [
      "text",
      "table",
      "image",
      "video",
      "audio",
      "file",
      "placeholder",
      "sticker",
      "group",
      "director",
      "editor",
      "comfyui",
      "agent",
      "skill",
      "plugin",
      "output",
    ];
    ordered.sort(
      (left, right) => order.indexOf(left.kind) - order.indexOf(right.kind),
    );
  }
  if (mode === "grid" || mode === "media") {
    const columns = Math.max(1, Math.ceil(Math.sqrt(ordered.length)));
    return {
      ...document,
      nodes: ordered.map((node, index) => ({
        ...node,
        x: 80 + (index % columns) * 320,
        y: 90 + Math.floor(index / columns) * 190,
      })),
    };
  }
  if (mode === "horizontal" || mode === "vertical") {
    return {
      ...document,
      nodes: ordered.map((node, index) => ({
        ...node,
        x: 80 + (mode === "horizontal" ? index * 320 : 0),
        y: 90 + (mode === "vertical" ? index * 190 : 0),
      })),
    };
  }
  const incoming = new Map<string, number>();
  document.nodes.forEach((node) => incoming.set(node.id, 0));
  document.edges.forEach((edge) =>
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1),
  );
  const level = new Map<string, number>();
  const queue = document.nodes
    .filter((node) => (incoming.get(node.id) ?? 0) === 0)
    .map((node) => node.id);
  queue.forEach((id) => level.set(id, 0));
  while (queue.length > 0) {
    const source = queue.shift()!;
    for (const edge of document.edges.filter(
      (item) => item.source === source,
    )) {
      const nextLevel = (level.get(source) ?? 0) + 1;
      level.set(edge.target, Math.max(level.get(edge.target) ?? 0, nextLevel));
      incoming.set(edge.target, (incoming.get(edge.target) ?? 1) - 1);
      if (incoming.get(edge.target) === 0) queue.push(edge.target);
    }
  }
  const rows = new Map<number, number>();
  return {
    ...document,
    nodes: document.nodes.map((node, index) => {
      const column = level.get(node.id) ?? index;
      const row = rows.get(column) ?? 0;
      rows.set(column, row + 1);
      return { ...node, x: 80 + column * 320, y: 90 + row * 190 };
    }),
  };
}

export function designCanvasRunPrompt(document: DesignCanvasDocument): string {
  const nodeSummary = document.nodes
    .filter(
      (node) =>
        node.kind !== "group" &&
        node.kind !== "sticker" &&
        node.kind !== "placeholder",
    )
    .map(
      (node, index) =>
        `${index + 1}. [${node.kind}] ${node.title}：${node.description}${node.binding ? `（绑定 ${node.binding.type}:${node.binding.id}）` : ""}${node.asset?.path ? `（工作区路径 ${node.asset.path}）` : ""}`,
    )
    .join("\n");
  const edgeSummary = document.edges
    .map((edge) => {
      const source = document.nodes.find((node) => node.id === edge.source);
      const target = document.nodes.find((node) => node.id === edge.target);
      return source && target ? `${source.title} → ${target.title}` : null;
    })
    .filter(Boolean)
    .join("；");
  return `请执行创作画布「${document.title}」。\n\n节点：\n${nodeSummary}\n\n编排关系：${edgeSummary || "按画布顺序执行"}\n\n请先给出执行计划，然后调用已绑定的角色、技能和插件逐步产出，并将结果作为项目交付物保存。`;
}

export function fitDesignMediaNodeDimensions(
  mediaWidth: number,
  mediaHeight: number,
): { width: number; height: number } {
  if (mediaWidth <= 0 || mediaHeight <= 0) return { width: 236, height: 240 };
  const aspect = mediaWidth / mediaHeight;
  const width = aspect <= 0.8 ? 190 : aspect >= 1.35 ? 260 : 220;
  const previewHeight = Math.round(Math.min(360, Math.max(96, width / aspect)));
  return { width, height: previewHeight + 25 };
}
