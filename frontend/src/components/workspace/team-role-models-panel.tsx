import { useCallback, useEffect, useState } from "react";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  CoinsIcon,
  Loader2Icon,
} from "lucide-react";

import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

interface RoleRow {
  role: string;
  default: string;
  tier: string;
}

interface RoleModelsData {
  roles: RoleRow[];
  tiers: string[];
}

export default function TeamRoleModelsPanel() {
  const { t } = useI18n();
  const roleModels = t.createTeamDialog.roleModels;
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
  const tierLabel = (tier: string) =>
    roleModels.tiers[tier as keyof typeof roleModels.tiers] ?? tier;
  const roleLabel = (role: string) =>
    roleModels.roles[role as keyof typeof roleModels.roles] ?? role;

  return (
    <div className="relative rounded-lg border border-border/50 bg-muted/15">
      <div className="flex items-center gap-2 px-3 py-2">
        <CoinsIcon className="size-3.5 shrink-0 text-muted-foreground" />
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span className="shrink-0 text-xs font-medium">
            {roleModels.title}
          </span>
          <span className="truncate text-[11px] text-muted-foreground">
            {roleModels.description}
            {overridden > 0 ? ` ${roleModels.customCount(overridden)}` : ""}
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
        <div className="absolute bottom-[calc(100%+0.5rem)] left-0 right-0 z-50 rounded-lg border border-border/70 bg-popover px-3 py-2 shadow-md">
          <div className="grid max-h-56 grid-cols-1 gap-1.5 overflow-y-auto pr-1 md:grid-cols-2 md:gap-x-3">
            {(data?.roles ?? []).map((r) => (
              <div
                key={r.role}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/45"
              >
                <div className="min-w-0 text-[11px]">
                  <div className="truncate font-medium">
                    {roleLabel(r.role)}
                  </div>
                  <div className="truncate text-muted-foreground">
                    {roleModels.defaultPrefix}
                    {tierLabel(r.default)}
                  </div>
                </div>
                <select
                  value={r.tier}
                  onChange={(e) => void setTier(r.role, e.target.value)}
                  className="h-7 rounded-md border border-border/60 bg-background px-1.5 text-[11px]"
                  style={{ minWidth: 96 }}
                >
                  {(data?.tiers ?? ["default", "cheap", "primary"]).map((t) => (
                    <option key={t} value={t}>
                      {tierLabel(t)}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <p className="mt-2 border-t border-border/40 pt-2 text-[11px] leading-snug text-muted-foreground">
            {roleModels.help}
          </p>
        </div>
      )}
    </div>
  );
}
