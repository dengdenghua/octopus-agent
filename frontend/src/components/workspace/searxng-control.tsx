/**
 * One-click local SearXNG control (private web-search backend).
 *
 * A self-contained card (its own zh/en labels, not the shared i18n bundle, to
 * stay decoupled from concurrently-edited locale files). Reads the public
 * `/api/searxng/status` and toggles deploy/stop via the auth-gated control
 * endpoints. When Docker is absent the switch is disabled and the card explains
 * that web search falls back to DuckDuckGo.
 */
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { useSearxngControl, useSearxngStatus } from "@/core/searxng/use-searxng-status";

const LABELS = {
  zh: {
    title: "本地网页搜索 (SearXNG)",
    desc: "一键用 Docker 在本机部署一个私有 SearXNG 作为网页搜索后端，查询不经过云搜索 API。关闭后回退到零配置的 DuckDuckGo。",
    needDocker: "需要先安装并启动 Docker；未安装时网页搜索自动使用 DuckDuckGo。",
    up: "运行中",
    down: "未运行",
    checking: "检测中…",
    deploying: "部署中（首次需拉取镜像，请稍候）…",
  },
  en: {
    title: "Local web search (SearXNG)",
    desc: "One-click deploy a private SearXNG via Docker as the web-search backend; queries never hit a cloud search API. Off falls back to zero-config DuckDuckGo.",
    needDocker: "Requires Docker installed and running; without it web search uses DuckDuckGo.",
    up: "Running",
    down: "Stopped",
    checking: "Checking…",
    deploying: "Deploying (first run pulls the image)…",
  },
};

export function SearxngControl() {
  const { locale } = useI18n();
  const t = (locale || "en").slice(0, 2).toLowerCase() === "zh" ? LABELS.zh : LABELS.en;
  const { status, isLoading } = useSearxngStatus();
  const { enable, disable, isPending } = useSearxngControl();

  const dockerMissing = status ? !status.docker_present : false;
  const deploying = isPending || Boolean(status?.managed && !status?.up);
  const state =
    isLoading && !status
      ? "checking"
      : deploying
        ? "deploying"
        : status?.up
          ? "up"
          : "down";

  const tone =
    state === "up"
      ? "bg-emerald-500"
      : state === "deploying" || state === "checking"
        ? "bg-amber-500 animate-pulse"
        : "bg-muted-foreground/50";

  return (
    <div className="rounded-lg border border-border-default bg-card/50 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn("size-2 shrink-0 rounded-full", tone)}
              aria-hidden="true"
            />
            <h4 className="text-sm font-medium">{t.title}</h4>
            <span className="text-[11px] text-muted-foreground">{t[state]}</span>
          </div>
          <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
            {dockerMissing ? t.needDocker : t.desc}
          </p>
        </div>
        <Switch
          checked={Boolean(status?.up || status?.managed)}
          disabled={dockerMissing || isPending}
          onCheckedChange={(checked) => (checked ? enable() : disable())}
          aria-label={t.title}
        />
      </div>
    </div>
  );
}
