import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangleIcon,
  ArrowDownToLineIcon,
  CheckCircle2Icon,
  KeyRoundIcon,
  Loader2Icon,
  PackageIcon,
} from "lucide-react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";

type MigrationItem = {
  kind: string;
  name: string;
  source: string;
  summary: string;
  origin: string;
  portable: boolean;
  needs: string[];
};

type MigrationPlan = {
  source: string;
  available: boolean;
  kinds: Record<string, number>;
  items: MigrationItem[];
  needs_attention: MigrationItem[];
};

type PreviewResponse = {
  schema: string;
  supported: string[];
  plans: MigrationPlan[];
};

type ApplyReport = {
  source: string;
  applied: Record<string, number>;
  skipped: Record<string, number>;
  target_root: string;
};

type ApplyResponse = {
  schema: string;
  reports: ApplyReport[];
  activation: {
    memory_added: number;
    memory_skipped: number;
    mcp_snippets: Record<string, string>;
  } | null;
};

export default function MigratePage() {
  const [plans, setPlans] = useState<MigrationPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [activate, setActivate] = useState(true);
  const [report, setReport] = useState<ApplyResponse | null>(null);
  const [oauthServer, setOauthServer] = useState("");
  const [oauthUrl, setOauthUrl] = useState("");
  const [oauthMsg, setOauthMsg] = useState<string | null>(null);
  const [authorizing, setAuthorizing] = useState(false);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/migrate/preview");
      if (!res.ok) throw new Error(`preview failed (${res.status})`);
      const data: PreviewResponse = await res.json();
      setPlans(data.plans);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  const apply = useCallback(async () => {
    setApplying(true);
    setError(null);
    setReport(null);
    try {
      const res = await fetch("/api/migrate/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activate }),
      });
      if (!res.ok) throw new Error(`apply failed (${res.status})`);
      setReport((await res.json()) as ApplyResponse);
      await loadPreview();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  }, [activate, loadPreview]);

  const authorizeMcp = useCallback(async () => {
    const server = oauthServer.trim();
    const url = oauthUrl.trim();
    if (!server || !url) return;
    setAuthorizing(true);
    setOauthMsg(null);
    try {
      const res = await fetch("/api/mcp-oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ server, url }),
      });
      if (!res.ok) throw new Error(`授权启动失败 (${res.status})`);
      const data: { authorize_url: string } = await res.json();
      window.open(data.authorize_url, "_blank", "noopener,noreferrer");
      setOauthMsg("已打开官方授权页;完成后该 MCP 即可用(token 自动保存与刷新)。");
    } catch (err) {
      setOauthMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthorizing(false);
    }
  }, [oauthServer, oauthUrl]);

  const available = (plans ?? []).filter((p) => p.available);
  const total = available.reduce((n, p) => n + p.items.length, 0);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="ui-density-stack mx-auto flex w-full max-w-4xl flex-col gap-4 py-4">
          <div>
            <h1 className="text-lg font-semibold">迁移其他工具 / Migrate</h1>
            <p className="text-sm text-muted-foreground">
              从 Codex / Claude 一键导入技能、记忆、MCP。技能直接可用,记忆暂存索引,
              MCP 仅生成待补凭证的配置片段(不会自动启动)。
            </p>
          </div>

          {loading ? (
            <div className="flex min-h-40 items-center justify-center">
              <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : error ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
              <button className="ml-3 underline" onClick={() => void loadPreview()}>
                重试
              </button>
            </div>
          ) : available.length === 0 ? (
            <div className="rounded-lg border p-4 text-sm text-muted-foreground">
              未检测到可迁移的工具(找不到 ~/.codex 或 ~/.claude)。
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {available.map((plan) => (
                  <div key={plan.source} className="workspace-panel rounded-2xl p-4">
                    <div className="flex items-center gap-2">
                      <PackageIcon className="size-4" />
                      <span className="font-medium capitalize">{plan.source}</span>
                      <span className="text-xs text-muted-foreground">
                        {plan.items.length} 项
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                      {Object.entries(plan.kinds).map(([kind, n]) => (
                        <span key={kind} className="rounded bg-muted px-1.5 py-0.5">
                          {kind}×{n}
                        </span>
                      ))}
                    </div>
                    {plan.needs_attention.length > 0 && (
                      <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-600">
                        <AlertTriangleIcon className="size-3.5 shrink-0" />
                        <span>{plan.needs_attention.length} 项需补凭证/运行时</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="flex items-center gap-3 border-t pt-3">
                <label className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={activate}
                    onChange={(e) => setActivate(e.target.checked)}
                  />
                  同时激活(记忆入库 + 生成 MCP 片段)
                </label>
                <button
                  onClick={() => void apply()}
                  disabled={applying || total === 0}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  {applying ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <ArrowDownToLineIcon className="size-4" />
                  )}
                  一键迁移 {total} 项
                </button>
              </div>
            </>
          )}

          {report && (
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">
              <div className="flex items-center gap-1.5 font-medium text-emerald-700">
                <CheckCircle2Icon className="size-4" /> 迁移完成
              </div>
              <ul className="mt-1.5 space-y-0.5 text-xs">
                {report.reports.map((r) => (
                  <li key={r.source}>
                    <span className="capitalize">{r.source}</span>: applied{" "}
                    {JSON.stringify(r.applied)}
                    {Object.keys(r.skipped).length > 0
                      ? ` · skipped ${JSON.stringify(r.skipped)}`
                      : ""}
                  </li>
                ))}
                {report.activation && (
                  <li>
                    memory: +{report.activation.memory_added} 条入 .octopus/MEMORY.md
                    {Object.keys(report.activation.mcp_snippets).length > 0
                      ? ` · MCP 片段已生成`
                      : ""}
                  </li>
                )}
              </ul>
            </div>
          )}

          <div className="workspace-panel rounded-2xl p-4">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <KeyRoundIcon className="size-4" /> 授权 OAuth MCP
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              远程 MCP(cloudflare / slack / linear …)走 OAuth:填服务器名 + URL,点「授权」会弹官方授权页
              —— 自动发现端点并注册客户端,授权后 token 自动保存与刷新。
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                value={oauthServer}
                onChange={(e) => setOauthServer(e.target.value)}
                placeholder="服务器名 (如 cloudflare)"
                className="rounded-lg border bg-background px-2 py-1 text-sm"
              />
              <input
                value={oauthUrl}
                onChange={(e) => setOauthUrl(e.target.value)}
                placeholder="https://mcp.cloudflare.com/mcp"
                className="min-w-64 flex-1 rounded-lg border bg-background px-2 py-1 text-sm"
              />
              <button
                onClick={() => void authorizeMcp()}
                disabled={authorizing || !oauthServer.trim() || !oauthUrl.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {authorizing ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : (
                  <KeyRoundIcon className="size-4" />
                )}
                授权
              </button>
            </div>
            {oauthMsg && <p className="mt-2 text-xs text-muted-foreground">{oauthMsg}</p>}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
