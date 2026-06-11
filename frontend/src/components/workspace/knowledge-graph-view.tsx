/* Implementation note. */
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { SearchIcon, RefreshCwIcon, Loader2Icon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";

interface ApiNode { id: string; label: string; entity_type?: string }
interface ApiEdge { id: string; source: string; target: string; label: string; confidence: number }
type GraphLayout = "ring" | "star" | "layers" | "clusters";

const NODE_COLORS: Record<string, string> = {
  center: "#8b5cf6",
  subject: "#3b82f6",
  object: "#10b981",
};

function circularLayout(count: number, cx: number, cy: number, radius: number) {
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });
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

function applyGraphLayout(
  layout: GraphLayout,
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
      Math.max(180, inputNodes.length * 13),
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
      Math.max(310, outerNodes.length * 12),
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

export function KnowledgeGraphView() {
  const { t } = useI18n();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [layout, setLayout] = useState<GraphLayout>("ring");
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const expandedRef = useRef<Set<string>>(new Set());
  const layoutRef = useRef<GraphLayout>("ring");
  const selectedEntityRef = useRef<string | null>(null);
  const layoutOptions = useMemo(
    () =>
      [
        { key: "ring", label: t.knowledgePanel.layouts.ring },
        { key: "star", label: t.knowledgePanel.layouts.star },
        { key: "layers", label: t.knowledgePanel.layouts.layers },
        { key: "clusters", label: t.knowledgePanel.layouts.clusters },
      ] as const,
    [t.knowledgePanel.layouts],
  );

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${getBackendBaseURL()}/api/knowledge/graph?limit=200`, {
        headers: authHeaders(),
      });
      if (!r.ok) return;
      const data = await r.json();
      const entities: Array<{ id: string; name: string; entity_type: string }> = data.entities ?? [];
      const rels: Array<{ id: string; source_name: string; target_name: string; relationship_type: string; confidence: number }> = data.relationships ?? [];

      const newNodes: Node[] = entities.map((e, i) => ({
        id: e.id,
        position: { x: 400, y: 300 },
        data: { label: e.name, entityType: e.entity_type },
        style: {
          background: NODE_COLORS[e.entity_type] ?? "#6b7280",
          color: "#fff",
          borderRadius: "9999px",
          padding: "6px 14px",
          fontSize: "11px",
          fontWeight: 500,
          border: "2px solid rgba(255,255,255,0.15)",
          cursor: "pointer",
        },
      }));
      const newEdges: Edge[] = rels.map((r) => ({
        id: r.id,
        source: r.source_name,
        target: r.target_name,
        label: r.relationship_type,
        style: { stroke: "#6b7280", strokeWidth: Math.max(1, (r.confidence ?? 0.5) * 3) },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "#6b7280" },
        labelStyle: { fontSize: 9, fill: "#9ca3af" },
      }));
      setNodes(
        applyGraphLayout(
          layoutRef.current,
          newNodes,
          newEdges,
          selectedEntityRef.current,
        ),
      );
      setEdges(newEdges);
      expandedRef.current.clear();
    } catch (e) { swallow(e); }
    setLoading(false);
  }, [setNodes, setEdges]);

  useEffect(() => { void loadGraph(); }, [loadGraph]);

  const onNodeClick: NodeMouseHandler = useCallback(async (_event, node) => {
    setSelectedEntity(node.id);
    selectedEntityRef.current = node.id;
    if (expandedRef.current.has(node.id)) return;
    expandedRef.current.add(node.id);

    try {
      const r = await fetch(
        `${getBackendBaseURL()}/api/knowledge/neighbors?entity=${encodeURIComponent(node.id)}&hops=1&limit=30`,
        { headers: authHeaders() },
      );
      if (!r.ok) return;
      const data: { nodes: ApiNode[]; edges: ApiEdge[] } = await r.json();

      setNodes((prev) => {
        const existing = new Set(prev.map((n) => n.id));
        const newOnes = data.nodes
          .filter((n) => !existing.has(n.id))
          .map((n, i) => {
            const angle = (2 * Math.PI * i) / Math.max(data.nodes.length, 1);
            const r = 120;
            return {
              id: n.id,
              position: {
                x: (node.position?.x ?? 400) + r * Math.cos(angle),
                y: (node.position?.y ?? 300) + r * Math.sin(angle),
              },
              data: { label: n.label, entityType: n.entity_type ?? "neighbor" },
              style: {
                background: "#6366f1",
                color: "#fff",
                borderRadius: "9999px",
                padding: "6px 14px",
                fontSize: "11px",
                fontWeight: 500,
                border: "2px solid rgba(255,255,255,0.15)",
                cursor: "pointer",
              },
            } satisfies Node;
          });
        return applyGraphLayout(layout, [...prev, ...newOnes], edges, node.id);
      });
      setEdges((prev) => {
        const existing = new Set(prev.map((e) => e.id));
        const newOnes = data.edges
          .filter((e) => !existing.has(e.id))
          .map((e) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.label,
            style: { stroke: "#8b5cf6", strokeWidth: Math.max(1, (e.confidence ?? 0.5) * 3) },
            markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "#8b5cf6" },
            labelStyle: { fontSize: 9, fill: "#a78bfa" },
          } satisfies Edge));
        const nextEdges = [...prev, ...newOnes];
        setNodes((current) => applyGraphLayout(layout, current, nextEdges, node.id));
        return nextEdges;
      });
    } catch (e) { swallow(e); }
  }, [edges, layout, setNodes, setEdges]);

  const changeLayout = useCallback(
    (nextLayout: GraphLayout) => {
      layoutRef.current = nextLayout;
      setLayout(nextLayout);
      setNodes((prev) => applyGraphLayout(nextLayout, prev, edges, selectedEntity));
    },
    [edges, selectedEntity, setNodes],
  );

  useEffect(() => {
    if (!search) {
      setNodes((prev) => prev.map((n) => ({
        ...n,
        style: { ...n.style, opacity: 1, boxShadow: undefined },
      })));
      return;
    }
    const q = search.toLowerCase();
    setNodes((prev) => prev.map((n) => {
      const match = String(n.data?.label ?? "").toLowerCase().includes(q);
      return {
        ...n,
        style: {
          ...n.style,
          opacity: match ? 1 : 0.25,
          boxShadow: match ? "0 0 12px rgba(139,92,246,0.6)" : undefined,
        },
      };
    }));
  }, [search, setNodes]);

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
        <SearchIcon className="size-4 text-muted-foreground" />
        <input
          className="h-8 min-w-[180px] flex-1 rounded-lg border border-border/60 bg-background/60 px-3 text-xs outline-none placeholder:text-muted-foreground focus:border-primary/50"
          placeholder={t.knowledgePanel.searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="flex h-8 items-center rounded-lg border border-border/60 bg-muted/35 p-0.5">
          {layoutOptions.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => changeLayout(option.key)}
              className={`h-7 rounded-md px-2 text-[11px] transition-colors ${
                layout === option.key
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => void loadGraph()}
          className="rounded-lg border border-border/60 px-3 py-1.5 text-xs hover:bg-muted"
        >
          <RefreshCwIcon className="size-3.5" />
        </button>
        <div className="text-[11px] text-muted-foreground">
          {t.knowledgePanel.nodeAndEdgeStats(nodes.length, edges.length)}
          {selectedEntity && ` · ${selectedEntity.slice(0, 20)}`}
        </div>
      </div>
      <div className="h-[500px] rounded-xl border border-border/40 bg-background/30 overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          fitView
          minZoom={0.1}
          maxZoom={3}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} color="rgba(255,255,255,0.03)" />
          <Controls position="bottom-right" />
          <MiniMap
            nodeColor={(n) => (n.style as Record<string, string>)?.background ?? "#6b7280"}
            maskColor="rgba(0,0,0,0.7)"
            style={{ borderRadius: 8 }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}
