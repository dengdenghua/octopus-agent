import { useCallback, useEffect, useState } from "react";
import { Check, Cloud, Download, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  installRegistryRole,
  listRegistryRoles,
  type RegistryRole,
} from "@/core/registry/api";
import { cn } from "@/lib/utils";

// 云端角色:从公网 registry 浏览 / 安装角色资产(role + twin-role · 数字分身岗位模板)。
// 安装即在本地 scaffold 一个可用 agent(profile.jsonc + agent-core/SOUL.md),下次刷新
// 角色库即可见。文案暂硬编码(i18n locales 处于活跃 WIP,避开冲突;后续再 i18n 化)。
export function RegistryRolesPanel() {
  const [roles, setRoles] = useState<RegistryRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installed, setInstalled] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRegistryRoles({ limit: 400 });
      setRoles(res.roles);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? roles.filter(
        (r) =>
          r.name.toLowerCase().includes(q) ||
          r.description.toLowerCase().includes(q) ||
          r.id.toLowerCase().includes(q),
      )
    : roles;

  const onInstall = async (role: RegistryRole) => {
    setInstalling((m) => ({ ...m, [role.id]: true }));
    setError(null);
    try {
      await installRegistryRole(role.id);
      setInstalled((m) => ({ ...m, [role.id]: true }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling((m) => ({ ...m, [role.id]: false }));
    }
  };

  return (
    <div className="min-h-[560px] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Cloud className="size-4 text-primary" />
        <span className="text-sm font-medium">
          云端角色 · 从 registry 按需安装
        </span>
        <span className="text-xs text-muted-foreground">
          {filtered.length}/{roles.length}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索角色"
            className="h-8 w-44 rounded-md border border-border/70 bg-background px-2 text-sm outline-none focus:border-primary/50"
          />
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {error ? (
        <div className="mb-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex min-h-[200px] items-center justify-center text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {filtered.map((role) => {
            const done = installed[role.id];
            const busy = installing[role.id];
            return (
              <div
                key={role.id}
                className="rounded-lg border border-border/60 bg-card/40 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {role.name}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {role.category ? (
                        <span className="text-xs text-primary">
                          {role.category}
                        </span>
                      ) : null}
                      <span className="text-xs text-muted-foreground">
                        {role.type === "twin-role" ? "数字分身" : "角色"}
                      </span>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant={done ? "secondary" : "default"}
                    disabled={busy || done}
                    onClick={() => void onInstall(role)}
                  >
                    {busy ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : done ? (
                      <Check className="size-3.5" />
                    ) : (
                      <Download className="size-3.5" />
                    )}
                    <span className="ml-1">
                      {busy ? "安装中" : done ? "已安装" : "安装"}
                    </span>
                  </Button>
                </div>
                <p className="mt-1.5 line-clamp-3 text-xs text-muted-foreground">
                  {role.description}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
