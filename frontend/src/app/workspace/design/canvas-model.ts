export type DesignCanvasMode = "freeform" | "workflow";
export type DesignNodeKind =
  | "brief"
  | "agent"
  | "skill"
  | "plugin"
  | "text"
  | "table"
  | "image"
  | "video"
  | "audio"
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
  width?: number;
  binding?: {
    type: "agent" | "skill" | "plugin" | "workflow";
    id: string;
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

export const DESIGN_CANVAS_STORAGE_KEY = "octopus:design-canvas:v1";

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
      nodes: parsed.nodes.filter(isDesignCanvasNode),
      edges: parsed.edges.filter(isDesignCanvasEdge),
    };
  } catch {
    return structuredClone(DEFAULT_DESIGN_CANVAS);
  }
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

export function tidyDesignCanvas(
  document: DesignCanvasDocument,
): DesignCanvasDocument {
  if (document.nodes.length === 0) return document;
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
    .map(
      (node, index) =>
        `${index + 1}. [${node.kind}] ${node.title}：${node.description}${node.binding ? `（绑定 ${node.binding.type}:${node.binding.id}）` : ""}`,
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
