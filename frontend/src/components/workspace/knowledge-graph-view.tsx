import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type NodeMouseHandler,
  MarkerType,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  SearchIcon,
  RefreshCwIcon,
  Loader2Icon,
  Maximize2Icon,
  OrbitIcon,
  GripIcon,
  CircleIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  memo,
} from "react";

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ApiNode {
  id: string;
  label: string;
  entity_type?: string;
}
interface ApiEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  confidence: number;
}

type GraphLayout = "force" | "ring" | "star" | "layers" | "clusters";

const ENTITY_TYPE_COLORS: Record<string, string> = {
  center: "#7c3aed",
  subject: "#2563eb",
  object: "#059669",
  neighbor: "#d97706",
};
const DEFAULT_COLOR = "#64748b";

function entityColor(entityType?: string): string {
  return ENTITY_TYPE_COLORS[entityType ?? ""] ?? DEFAULT_COLOR;
}

function nodeDegree(edges: Edge[]): Map<string, number> {
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  return degree;
}

function connectedTo(edges: Edge[], centerId: string): Set<string> {
  const ids = new Set<string>();
  for (const edge of edges) {
    if (edge.source === centerId) ids.add(edge.target);
    if (edge.target === centerId) ids.add(edge.source);
  }
  return ids;
}

function circularLayout(count: number, cx: number, cy: number, radius: number) {
  if (count === 1) return [{ x: cx, y: cy }];
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    return {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });
}

function applyStaticLayout(
  layout: Exclude<GraphLayout, "force">,
  inputNodes: Node[],
  inputEdges: Edge[],
  selectedEntity: string | null,
): Node[] {
  if (inputNodes.length === 0) return inputNodes;
  const cx = 400;
  const cy = 300;
  const degree = nodeDegree(inputEdges);

  if (layout === "ring") {
    const positions = circularLayout(
      inputNodes.length,
      cx,
      cy,
      Math.min(360, Math.max(170, Math.sqrt(inputNodes.length) * 28)),
    );
    return inputNodes.map((node, index) => ({
      ...node,
      position: positions[index] ?? { x: cx, y: cy },
    }));
  }

  if (layout === "star") {
    const centerId =
      selectedEntity && inputNodes.some((node) => node.id === selectedEntity)
        ? selectedEntity
        : [...inputNodes].sort(
            (a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0),
          )[0]?.id;
    const firstRing = connectedTo(inputEdges, centerId ?? "");
    const firstRingNodes = inputNodes.filter((node) => firstRing.has(node.id));
    const outerNodes = inputNodes.filter(
      (node) => node.id !== centerId && !firstRing.has(node.id),
    );
    const firstPositions = circularLayout(
      firstRingNodes.length,
      cx,
      cy,
      Math.max(150, firstRingNodes.length * 18),
    );
    const outerPositions = circularLayout(
      outerNodes.length,
      cx,
      cy,
      Math.min(420, Math.max(250, Math.sqrt(outerNodes.length) * 34)),
    );
    const pos = new Map<string, { x: number; y: number }>();
    if (centerId) pos.set(centerId, { x: cx, y: cy });
    firstRingNodes.forEach((node, index) => {
      pos.set(node.id, firstPositions[index] ?? { x: cx, y: cy });
    });
    outerNodes.forEach((node, index) => {
      pos.set(node.id, outerPositions[index] ?? { x: cx, y: cy });
    });
    return inputNodes.map((node) => ({
      ...node,
      position: pos.get(node.id) ?? node.position,
    }));
  }

  if (layout === "layers") {
    const incoming = new Map<string, number>();
    const outgoing = new Map<string, number>();
    for (const edge of inputEdges) {
      outgoing.set(edge.source, (outgoing.get(edge.source) ?? 0) + 1);
      incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
    }
    const columns: [Node[], Node[], Node[]] = [[], [], []];
    for (const node of inputNodes) {
      const inc = incoming.get(node.id) ?? 0;
      const out = outgoing.get(node.id) ?? 0;
      if (out > 0 && inc === 0) columns[0].push(node);
      else if (inc > 0 && out === 0) columns[2].push(node);
      else columns[1].push(node);
    }
    const columnX: [number, number, number] = [80, 400, 720];
    const pos = new Map<string, { x: number; y: number }>();
    columns.forEach((column, colIndex) => {
      const x = columnX[colIndex] ?? cx;
      const gap = Math.max(72, 420 / Math.max(column.length, 1));
      const startY = cy - ((column.length - 1) * gap) / 2;
      column
        .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))
        .forEach((node, index) => {
          pos.set(node.id, { x, y: startY + index * gap });
        });
    });
    return inputNodes.map((node) => ({
      ...node,
      position: pos.get(node.id) ?? node.position,
    }));
  }

  const groups = new Map<string, Node[]>();
  for (const node of inputNodes) {
    const entityType = String(node.data?.entityType ?? "other");
    const group = groups.get(entityType) ?? [];
    group.push(node);
    groups.set(entityType, group);
  }
  const groupEntries = [...groups.entries()].sort(([a], [b]) =>
    a.localeCompare(b),
  );
  const groupCenters = circularLayout(
    groupEntries.length,
    cx,
    cy,
    Math.max(180, groupEntries.length * 90),
  );
  const pos = new Map<string, { x: number; y: number }>();
  groupEntries.forEach(([, group], groupIndex) => {
    const center = groupCenters[groupIndex] ?? { x: cx, y: cy };
    const positions = circularLayout(
      group.length,
      center.x,
      center.y,
      Math.max(48, group.length * 12),
    );
    group.forEach((node, nodeIndex) => {
      pos.set(node.id, positions[nodeIndex] ?? center);
    });
  });
  return inputNodes.map((node) => ({
    ...node,
    position: pos.get(node.id) ?? node.position,
  }));
}

function runForceLayout(
  nodes: Node[],
  edges: Edge[],
  iterations = 180,
): Node[] {
  if (nodes.length === 0) return nodes;
  const width = 720;
  const height = 520;
  const centerX = width / 2;
  const centerY = height / 2;
  const margin = 60;

  const positions = new Map<
    string,
    { x: number; y: number; vx: number; vy: number }
  >();
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1);
    const r = Math.min(width, height) * 0.28;
    positions.set(n.id, {
      x: centerX + r * Math.cos(angle),
      y: centerY + r * Math.sin(angle),
      vx: 0,
      vy: 0,
    });
  });

  const k = Math.sqrt((width * height) / Math.max(nodes.length, 1)) * 0.65;

  for (let iter = 0; iter < iterations; iter++) {
    const t = 1 - iter / iterations;

    const nodeIds = nodes.map((n) => n.id);
    for (let i = 0; i < nodeIds.length; i++) {
      const a = positions.get(nodeIds[i]!)!;
      for (let j = i + 1; j < nodeIds.length; j++) {
        const b = positions.get(nodeIds[j]!)!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 1) dist = 1;
        const force = (k * k) / dist;
        const fx = (dx / dist) * force * 0.05;
        const fy = (dy / dist) * force * 0.05;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }

    for (const edge of edges) {
      const a = positions.get(edge.source);
      const b = positions.get(edge.target);
      if (!a || !b) continue;
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = ((dist - k) / k) * 0.03;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    for (const p of positions.values()) {
      p.vx += (centerX - p.x) * 0.0008;
      p.vy += (centerY - p.y) * 0.0008;
      if (p.x < margin) p.vx += (margin - p.x) * 0.008;
      if (p.x > width - margin) p.vx -= (p.x - (width - margin)) * 0.008;
      if (p.y < margin) p.vy += (margin - p.y) * 0.008;
      if (p.y > height - margin) p.vy -= (p.y - (height - margin)) * 0.008;

      p.vx *= 0.55;
      p.vy *= 0.55;
      p.x += p.vx * t;
      p.y += p.vy * t;
      p.x = Math.max(margin, Math.min(width - margin, p.x));
      p.y = Math.max(margin, Math.min(height - margin, p.y));
    }
  }

  return nodes.map((n) => {
    const p = positions.get(n.id);
    return { ...n, position: { x: p?.x ?? 0, y: p?.y ?? 0 } };
  });
}

const GraphNode = memo(function GraphNode({
  data,
  selected,
}: {
  data: { label: string; entityType?: string; size?: number; dimmed?: boolean };
  selected?: boolean;
}) {
  const color = entityColor(data.entityType);
  const dimmed = data.dimmed ?? false;

  return (
    <div
      className={cn(
        "rounded-md border px-2.5 py-1 text-[11px] font-medium shadow-sm transition-all duration-150",
        selected && "ring-2 ring-white/60",
      )}
      style={{
        borderColor: color,
        backgroundColor: `${color}18`,
        color,
        opacity: dimmed ? 0.25 : 1,
      }}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <span className="whitespace-nowrap">{data.label}</span>
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
});

function GraphEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  selected,
  data,
  markerEnd,
}: {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  selected?: boolean;
  data?: { dimmed?: boolean; highlighted?: boolean };
  markerEnd?: string;
}) {
  const dimmed = data?.dimmed;
  const highlighted = selected || data?.highlighted;

  return (
    <g className="transition-opacity duration-150">
      <line
        x1={sourceX}
        y1={sourceY}
        x2={targetX}
        y2={targetY}
        strokeWidth={highlighted ? 1.5 : 1}
        stroke={highlighted ? "rgba(124,58,237,0.7)" : "rgba(148,163,184,0.3)"}
        opacity={dimmed ? 0.08 : 1}
        markerEnd={markerEnd}
      />
    </g>
  );
}

const nodeTypes = { graph: GraphNode };
const edgeTypes = { graph: GraphEdge };

function Legend() {
  const items = [
    { type: "center", label: "中心" },
    { type: "subject", label: "主体" },
    { type: "object", label: "对象" },
    { type: "neighbor", label: "邻居" },
  ];
  return (
    <div className="absolute left-3 top-3 z-10 rounded-lg border border-border/40 bg-background/70 px-3 py-2 text-[10px] backdrop-blur">
      <div className="mb-1.5 font-medium text-muted-foreground">实体类型</div>
      <div className="space-y-1">
        {items.map((item) => (
          <div key={item.type} className="flex items-center gap-2">
            <span
              className="size-2.5 rounded-full"
              style={{ backgroundColor: entityColor(item.type) }}
            />
            <span className="text-muted-foreground">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function KnowledgeGraphViewInner() {
  const { t } = useI18n();
  const { fitView } = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [layout, setLayout] = useState<GraphLayout>("force");
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const layoutRef = useRef<GraphLayout>("force");

  const layoutOptions = useMemo(
    () =>
      [
        { key: "force" as const, label: t.knowledgePanel.layouts.force },
        { key: "ring" as const, label: t.knowledgePanel.layouts.ring },
        { key: "star" as const, label: t.knowledgePanel.layouts.star },
        { key: "layers" as const, label: t.knowledgePanel.layouts.layers },
        { key: "clusters" as const, label: t.knowledgePanel.layouts.clusters },
      ] as const,
    [t.knowledgePanel.layouts],
  );

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(
        `${getBackendBaseURL()}/api/knowledge/graph?limit=200`,
        { headers: authHeaders() },
      );
      if (!r.ok) return;
      const data = await r.json();
      const entities: Array<{ id: string; name: string; entity_type: string }> =
        (data.entities ?? []).slice(0, 120);
      const rels: Array<{
        id: string;
        source_name: string;
        target_name: string;
        relationship_type: string;
        confidence: number;
      }> = data.relationships ?? [];

      const edgeList: Edge[] = rels.map((r) => ({
        id: r.id,
        type: "graph",
        source: r.source_name,
        target: r.target_name,
        label: r.relationship_type,
        data: {},
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 8,
          height: 8,
          color: "rgba(148,163,184,0.35)",
        },
      }));

      const degree = nodeDegree(edgeList);

      const nodeList: Node[] = entities.map((e) => {
        const deg = degree.get(e.id) ?? 0;
        return {
          id: e.id,
          type: "graph",
          position: { x: 400, y: 300 },
          data: {
            label: e.name,
            entityType: e.entity_type,
            size: Math.min(20, Math.max(4, 3 + deg * 1.1)),
          },
        };
      });

      const laidOut =
        layoutRef.current === "force"
          ? runForceLayout(nodeList, edgeList)
          : applyStaticLayout(layoutRef.current, nodeList, edgeList, null);

      setNodes(laidOut);
      setEdges(edgeList);
    } catch (e) {
      swallow(e);
    }
    setLoading(false);
  }, [setNodes, setEdges]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    if (!loading && nodes.length > 0) {
      const t = setTimeout(() => fitView({ padding: 0.1, maxZoom: 1.4 }), 50);
      return () => clearTimeout(t);
    }
  }, [loading, nodes.length, fitView]);

  const applyLayout = useCallback(
    (nextLayout: GraphLayout) => {
      layoutRef.current = nextLayout;
      setLayout(nextLayout);
      setNodes((prev) => {
        const next =
          nextLayout === "force"
            ? runForceLayout(prev, edges)
            : applyStaticLayout(nextLayout, prev, edges, null);
        setTimeout(() => fitView({ padding: 0.1, maxZoom: 1.4 }), 50);
        return next;
      });
    },
    [edges, fitView, setNodes],
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    async (_event, node) => {
      try {
        const r = await fetch(
          `${getBackendBaseURL()}/api/knowledge/neighbors?entity=${encodeURIComponent(node.id)}&hops=1&limit=30`,
          { headers: authHeaders() },
        );
        if (!r.ok) return;
        const data: { nodes: ApiNode[]; edges: ApiEdge[] } = await r.json();

        setNodes((prev) => {
          const existing = new Set(prev.map((n) => n.id));
          const degree = nodeDegree(edges);
          const newOnes = data.nodes
            .filter((n) => !existing.has(n.id))
            .map((n, i) => {
              const angle = (2 * Math.PI * i) / Math.max(data.nodes.length, 1);
              const radius = 100;
              const deg = degree.get(n.id) ?? 0;
              return {
                id: n.id,
                type: "graph" as const,
                position: {
                  x: (node.position?.x ?? 400) + radius * Math.cos(angle),
                  y: (node.position?.y ?? 300) + radius * Math.sin(angle),
                },
                data: {
                  label: n.label,
                  entityType: n.entity_type ?? "neighbor",
                  size: Math.min(16, Math.max(4, 3 + deg)),
                },
              } satisfies Node;
            });
          const merged = [...prev, ...newOnes];
          return layoutRef.current === "force"
            ? runForceLayout(merged, edges)
            : applyStaticLayout(layoutRef.current, merged, edges, node.id);
        });

        setEdges((prev) => {
          const existing = new Set(prev.map((e) => e.id));
          const newOnes = data.edges
            .filter((e) => !existing.has(e.id))
            .map(
              (e) =>
                ({
                  id: e.id,
                  type: "graph" as const,
                  source: e.source,
                  target: e.target,
                  label: e.label,
                  data: {},
                  markerEnd: {
                    type: MarkerType.ArrowClosed,
                    width: 8,
                    height: 8,
                    color: "rgba(148,163,184,0.35)",
                  },
                }) satisfies Edge,
            );
          return [...prev, ...newOnes];
        });
      } catch (e) {
        swallow(e);
      }
    },
    [edges, setEdges, setNodes],
  );

  const onNodeMouseEnter: NodeMouseHandler = useCallback(
    (_event, node) => setHoveredNode(node.id),
    [setHoveredNode],
  );
  const onNodeMouseLeave: NodeMouseHandler = useCallback(
    () => setHoveredNode(null),
    [setHoveredNode],
  );

  const neighbors = useMemo(() => {
    if (!hoveredNode) return new Set<string>();
    const set = new Set<string>([hoveredNode]);
    for (const edge of edges) {
      if (edge.source === hoveredNode) set.add(edge.target);
      if (edge.target === hoveredNode) set.add(edge.source);
    }
    return set;
  }, [hoveredNode, edges]);

  const styledNodes = useMemo(() => {
    if (!hoveredNode && !search) return nodes;
    const q = search.toLowerCase();
    return nodes.map((n) => {
      const inNeighbors = neighbors.has(n.id);
      const matchesSearch =
        !search ||
        String(n.data?.label ?? "").toLowerCase().includes(q);
      const dimmed = (hoveredNode ? !inNeighbors : false) || (search && !matchesSearch);
      return {
        ...n,
        data: { ...n.data, dimmed },
        style: {
          ...n.style,
          opacity: dimmed ? 0.2 : 1,
          transition: "opacity 0.15s ease",
        },
      };
    });
  }, [nodes, hoveredNode, neighbors, search]);

  const styledEdges = useMemo(() => {
    if (!hoveredNode) return edges;
    return edges.map((e) => {
      const isRelated =
        e.source === hoveredNode || e.target === hoveredNode;
      return {
        ...e,
        data: {
          ...e.data,
          dimmed: !isRelated,
          highlighted: isRelated,
        },
      };
    });
  }, [edges, hoveredNode]);

  if (loading) {
    return (
      <div className="flex h-[500px] items-center justify-center">
        <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-9 rounded-full border-border/60 bg-muted/40 pl-9 text-xs placeholder:text-muted-foreground focus-visible:ring-primary/30"
            placeholder={t.knowledgePanel.searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-1 rounded-full border border-border/60 bg-muted/35 p-0.5">
          {layoutOptions.map((option) => (
            <Button
              key={option.key}
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => applyLayout(option.key)}
              className={cn(
                "h-7 rounded-full px-3 text-[11px]",
                layout === option.key
                  ? "bg-background text-foreground shadow-sm hover:bg-background"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {option.key === "force" ? (
                <OrbitIcon className="mr-1 size-3" />
              ) : (
                <GripIcon className="mr-1 size-3" />
              )}
              {option.label}
            </Button>
          ))}
        </div>

        <Button
          variant="outline"
          size="icon"
          onClick={() => void loadGraph()}
          className="rounded-full border-border/60"
          aria-label={t.knowledgeGraph.refresh}
        >
          <RefreshCwIcon className="size-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={() => fitView({ padding: 0.1, maxZoom: 1.4 })}
          className="rounded-full border-border/60"
          aria-label="Fit view"
        >
          <Maximize2Icon className="size-4" />
        </Button>

        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <CircleIcon className="size-3" />
          {t.knowledgePanel.nodeAndEdgeStats(nodes.length, edges.length)}
        </div>
      </div>

      <div className="relative h-[620px] overflow-hidden rounded-2xl border border-border/50 bg-background shadow-inner">
        <Legend />
        <ReactFlow
          nodes={styledNodes}
          edges={styledEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onNodeMouseEnter={onNodeMouseEnter}
          onNodeMouseLeave={onNodeMouseLeave}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.1, maxZoom: 1.4 }}
          minZoom={0.2}
          maxZoom={4}
          proOptions={{ hideAttribution: true }}
          className="!bg-transparent"
        >
          <Background
            gap={24}
            size={1}
            color="hsl(var(--border) / 0.2)"
            className="opacity-25"
          />
          <Controls
            position="bottom-right"
            className="!rounded-lg !border-border/40 !bg-background/80 !shadow"
          />
          <MiniMap
            nodeColor={(n) =>
              entityColor((n.data as { entityType?: string })?.entityType)
            }
            maskColor="rgba(15,23,42,0.3)"
            pannable
            zoomable
            className="!rounded-lg !border !border-border/40 !bg-background/80 !shadow"
            style={{ width: 140, height: 90 }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}

export function KnowledgeGraphView() {
  return (
    <ReactFlowProvider>
      <KnowledgeGraphViewInner />
    </ReactFlowProvider>
  );
}
