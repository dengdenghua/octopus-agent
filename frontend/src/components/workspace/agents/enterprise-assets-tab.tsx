/**
 * 企业版角色资产 tab(数字分身归并 C · 消费侧前端)。
 *
 * 只读列举企业版(octopus-enterprise)托管的角色资产——消费而非 fork。配了
 * OCTOPUS_ENTERPRISE_URL(后端)才有数据,否则显示"未接通"提示。「导入到本地」
 * 是下一步(需后端 scaffold + load),这里先把企业版的角色摆出来可浏览/搜索。
 */

import { useEffect, useState } from "react";

import {
  listEnterpriseAssets,
  type EnterpriseAsset,
} from "@/core/agents/agent-world-api";

export function EnterpriseAssetsTab({ query }: { query?: string }) {
  const [items, setItems] = useState<EnterpriseAsset[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listEnterpriseAssets({ search: query || undefined })
      .then((r) => {
        if (!alive) return;
        setAvailable(r.available);
        setItems(r.available ? r.items : []);
      })
      .catch(() => {
        if (alive) {
          setAvailable(false);
          setItems([]);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [query]);

  if (loading) {
    return (
      <div className="py-10 text-center text-xs text-muted-foreground">
        加载中…
      </div>
    );
  }
  if (available === false) {
    return (
      <div className="py-10 text-center text-xs leading-relaxed text-muted-foreground">
        企业版资产库未接通。
        <br />
        后端配置 <code className="rounded bg-muted/50 px-1">OCTOPUS_ENTERPRISE_URL</code>{" "}
        后,这里会列出企业版托管的角色资产。
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="py-10 text-center text-xs text-muted-foreground">
        企业版暂无匹配的角色资产。
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 text-[11px] text-muted-foreground">
        来自企业版资产库 · 共 {items.length} 个(消费而非 fork)
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {items.map((a) => (
          <div
            key={a.id}
            className="flex gap-3 rounded-lg border border-border/50 bg-muted/20 p-3"
          >
            <div className="shrink-0 text-2xl leading-none">{a.icon || "🤖"}</div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium">{a.name}</span>
                {a.category && (
                  <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                    {a.category}
                  </span>
                )}
              </div>
              <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
                {a.description}
              </div>
              {a.tags && a.tags.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {a.tags.slice(0, 4).map((tag) => (
                    <span
                      key={tag}
                      className="rounded bg-muted/50 px-1 py-0.5 text-[9px] text-muted-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
