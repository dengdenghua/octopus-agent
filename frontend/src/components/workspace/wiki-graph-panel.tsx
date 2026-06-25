import { useEffect, useMemo, useState } from "react";
import { NetworkIcon, RefreshCwIcon } from "lucide-react";

import { getBackendBaseURL } from "@/core/config";

// Wiki dependency graph (ADR-009): the zero-LLM page→page import edges that
// gen_wiki derives from the AST, rendered as a navigable graph. A circular
// layout keeps it dependency-free; hovering a node highlights its edges.

type GraphNode = { path: string; title: string };
type GraphEdge = { from: string; to: string; type: string };
type GraphData = { nodes: GraphNode[]; edges: GraphEdge[]; generated_at?: string };

const W = 760;
const H = 520;

function shortLabel(node: GraphNode): string {
  const last = node.path.split("/").pop()?.replace(/\.md$/, "") ?? node.path;
  return node.title?.split("·")[0]?.trim() || last;
}

export function WikiGraphPanel() {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    fetch(`${getBackendBaseURL()}/api/wiki/graph`, { credentials: "include" })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: GraphData) => setData(d))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pos = useMemo(() => {
    const nodes = data?.nodes ?? [];
    const cx = W / 2;
    const cy = H / 2;
    const r = Math.min(W, H) / 2 - 80;
    const m = new Map<string, { x: number; y: number }>();
    nodes.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, nodes.length) - Math.PI / 2;
      m.set(n.path, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
    });
    return m;
  }, [data]);

  if (loading && !data) {
    return (
      <div className="flex min-h-72 items-center justify-center text-sm text-muted-foreground">
        加载依赖图…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-destructive">加载失败 · {error}</p>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted"
        >
          <RefreshCwIcon className="size-3.5" /> 重试
        </button>
      </div>
    );
  }
  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center gap-3 py-12 text-center">
        <NetworkIcon className="size-8 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">
          暂无依赖图 · 运行 <code className="rounded bg-muted px-1">python scripts/gen_wiki.py</code> 生成
        </p>
      </div>
    );
  }

  const connected = new Set<string>();
  if (hover) {
    for (const e of data.edges) {
      if (e.from === hover) connected.add(e.to);
      if (e.to === hover) connected.add(e.from);
    }
  }

  return (
    <div className="flex flex-col gap-2 p-2 text-foreground">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2 text-sm font-medium">
          <NetworkIcon className="size-4 text-primary" />
          Wiki 依赖图
          <span className="text-xs font-normal text-muted-foreground">
            {data.nodes.length} 页 · {data.edges.length} 条依赖边
          </span>
        </div>
        <button
          onClick={load}
          title="刷新"
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
        >
          <RefreshCwIcon className="size-3.5" />
        </button>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full rounded-xl border border-border bg-muted/20"
        role="img"
        aria-label="Wiki page dependency graph"
      >
        {data.edges.map((e, i) => {
          const a = pos.get(e.from);
          const b = pos.get(e.to);
          if (!a || !b) return null;
          const active = hover && (e.from === hover || e.to === hover);
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className={active ? "stroke-primary" : "stroke-border"}
              strokeWidth={active ? 1.5 : 0.7}
              opacity={hover && !active ? 0.15 : 0.6}
            />
          );
        })}
        {data.nodes.map((n) => {
          const p = pos.get(n.path);
          if (!p) return null;
          const isHover = hover === n.path;
          const isNeighbor = connected.has(n.path);
          const dim = hover && !isHover && !isNeighbor;
          return (
            <g
              key={n.path}
              transform={`translate(${p.x},${p.y})`}
              opacity={dim ? 0.3 : 1}
              onMouseEnter={() => setHover(n.path)}
              onMouseLeave={() => setHover(null)}
              className="cursor-pointer"
            >
              <circle
                r={isHover ? 7 : 5}
                className={isHover || isNeighbor ? "fill-primary" : "fill-muted-foreground"}
              />
              <text
                x={p.x < W / 2 ? -9 : 9}
                y={3}
                textAnchor={p.x < W / 2 ? "end" : "start"}
                className="fill-foreground"
                fontSize={9.5}
                fontWeight={isHover ? 600 : 400}
              >
                {shortLabel(n)}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="px-1 text-[11px] text-muted-foreground">
        悬停某页高亮它的依赖 · 边由 gen_wiki 从 AST import 图零-LLM 抽取（ADR-009）
      </p>
    </div>
  );
}
