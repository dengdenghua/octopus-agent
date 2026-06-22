import { useCallback, useEffect, useState } from "react";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  Loader2Icon,
  RefreshCwIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { getBackendBaseURL } from "@/core/config";

// One plain-language readiness item from GET /api/local-brain/status.
// All copy (label / what / detail / action) is authored on the backend in
// plain Chinese, so this panel just renders it — no i18n keys to drift.
interface BrainItem {
  id: string;
  label: string;
  what: string;
  ok: boolean;
  detail: string;
  action: string;
}

interface BrainStatus {
  ready: boolean;
  core_ready: boolean;
  summary: string;
  ollama_url: string;
  items: BrainItem[];
}

export default function LocalBrainSetup() {
  const [status, setStatus] = useState<BrainStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/local-brain/status`, {
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus((await res.json()) as BrainStatus);
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="mb-2 rounded-lg border border-border/55 bg-white p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">本地大脑 · 一键检测</h2>
          <p className="mt-0.5 text-xs text-muted-foreground leading-snug">
            {status?.summary ?? "正在检测你的本地 AI 是否就绪…"}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          disabled={loading}
          className="shrink-0"
        >
          {loading ? (
            <Loader2Icon className="size-3.5 animate-spin" />
          ) : (
            <RefreshCwIcon className="size-3.5" />
          )}
          <span className="ml-1.5">重新检测</span>
        </Button>
      </div>

      {error && (
        <p className="mb-2 text-xs text-red-600">检测失败:{error}(后端没起?)</p>
      )}

      <ol className="space-y-1.5">
        {status?.items.map((it, i) => (
          <li
            key={it.id}
            className="flex items-start gap-2.5 rounded-md border border-border/40 px-3 py-2"
          >
            <span className="mt-0.5 shrink-0">
              {it.ok ? (
                <CheckCircle2Icon className="size-4 text-emerald-600" />
              ) : (
                <AlertCircleIcon className="size-4 text-amber-500" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">
                  {i + 1}. {it.label}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] ${
                    it.ok
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-amber-50 text-amber-700"
                  }`}
                >
                  {it.ok ? "已就绪" : "待配置"}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-muted-foreground leading-snug">
                {it.what}
              </p>
              <p className="mt-0.5 text-[11px] text-foreground/70">
                现状:{it.detail}
              </p>
              {!it.ok && it.action && (
                <p className="mt-1 text-[11px] leading-snug text-blue-700">
                  下一步:{it.action}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
