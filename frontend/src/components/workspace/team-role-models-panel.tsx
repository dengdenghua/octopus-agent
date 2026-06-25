import { useCallback, useEffect, useState } from "react";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  CoinsIcon,
  Loader2Icon,
} from "lucide-react";

import { getBackendBaseURL } from "@/core/config";

interface RoleRow {
  role: string;
  default: string;
  tier: string;
}

interface RoleModelsData {
  roles: RoleRow[];
  tiers: string[];
}

const TIER_LABEL: Record<string, string> = {
  default: "默认",
  cheap: "便宜模型",
  primary: "前沿模型",
};

const ROLE_LABEL: Record<string, string> = {
  planner: "规划",
  generator: "生成",
  synthesizer: "综合",
  researcher: "研究",
  critic: "批判",
  evaluator: "评估",
  reviewer: "审查",
  fact_checker: "事实核查",
  verifier: "验证",
  arbiter: "仲裁",
};

export default function TeamRoleModelsPanel() {
  const [data, setData] = useState<RoleModelsData | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/team/role-models`);
      if (res.ok) setData((await res.json()) as RoleModelsData);
    } catch {
      /* offline → leave null */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setTier = useCallback(
    async (role: string, tier: string) => {
      if (!data) return;
      const roles = data.roles.map((r) =>
        r.role === role ? { ...r, tier } : r,
      );
      setData({ ...data, roles });
      const overrides: Record<string, string> = {};
      for (const r of roles) {
        if (r.tier && r.tier !== "default") overrides[r.role] = r.tier;
      }
      setSaving(true);
      try {
        await fetch(`${getBackendBaseURL()}/api/team/role-models`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ overrides }),
        });
      } catch {
        /* best-effort */
      } finally {
        setSaving(false);
      }
    },
    [data],
  );

  const overridden = (data?.roles ?? []).filter(
    (r) => r.tier && r.tier !== "default",
  ).length;

  return (
    <div className="mb-2 overflow-hidden rounded-lg border border-border/55 bg-card">
      <div className="flex items-center gap-2 px-3 py-1.5">
        <CoinsIcon className="size-4 shrink-0 text-muted-foreground" />
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span className="shrink-0 text-xs font-medium">团队成员模型分层</span>
          <span className="truncate text-[11px] text-muted-foreground">
            简单角色默认走便宜模型省钱;在这里可逐角色覆盖。
            {overridden > 0 ? ` 已自定义 ${overridden} 个` : ""}
          </span>
          {saving && (
            <Loader2Icon className="size-3 shrink-0 animate-spin text-muted-foreground" />
          )}
          {expanded ? (
            <ChevronDownIcon className="ml-auto size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRightIcon className="ml-auto size-3.5 shrink-0 text-muted-foreground" />
          )}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-border/40 px-3 py-2">
          <div className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5">
            {(data?.roles ?? []).map((r) => (
              <div key={r.role} className="contents">
                <div className="flex items-center gap-1.5 text-[11px]">
                  <span className="font-medium">
                    {ROLE_LABEL[r.role] ?? r.role}
                  </span>
                  <span className="text-muted-foreground">
                    默认{TIER_LABEL[r.default] ?? r.default}
                  </span>
                </div>
                <select
                  value={r.tier}
                  onChange={(e) => void setTier(r.role, e.target.value)}
                  className="text-[11px]"
                  style={{ minWidth: 96 }}
                >
                  {(data?.tiers ?? ["default", "cheap", "primary"]).map((t) => (
                    <option key={t} value={t}>
                      {TIER_LABEL[t] ?? t}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
            「便宜模型」走 glm-4-flash
            类廉价模型省成本;「前沿」用主力模型。改动即时生效于之后的团队运行。
          </p>
        </div>
      )}
    </div>
  );
}
