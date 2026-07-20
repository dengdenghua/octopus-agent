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
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

import {
  useSearxngControl,
  useSearxngStatus,
} from "@/core/searxng/use-searxng-status";

const LABELS = {
  zh: {
    title: "本地网页搜索 (SearXNG)",
    desc: "一键用 Docker 在本机部署一个私有 SearXNG 作为网页搜索后端，查询不经过云搜索 API。关闭后回退到零配置的 DuckDuckGo。",
    needDocker:
      "需要先安装并启动 Docker；未安装时网页搜索自动使用 DuckDuckGo。",
    up: "运行中",
    down: "未运行",
    checking: "检测中…",
    deploying: "部署中（首次需拉取镜像，请稍候）…",
    unavailable: "暂时无法读取本地搜索状态。",
    retry: "重新检测",
    enableFailed: "本地搜索启动失败，请确认 Docker 正在运行。",
    disableFailed: "本地搜索停止失败，请稍后重试。",
  },
  en: {
    title: "Local web search (SearXNG)",
    desc: "One-click deploy a private SearXNG via Docker as the web-search backend; queries never hit a cloud search API. Off falls back to zero-config DuckDuckGo.",
    needDocker:
      "Requires Docker installed and running; without it web search uses DuckDuckGo.",
    up: "Running",
    down: "Stopped",
    checking: "Checking…",
    deploying: "Deploying (first run pulls the image)…",
    unavailable: "Local search status is temporarily unavailable.",
    retry: "Check again",
    enableFailed: "Local search could not start. Make sure Docker is running.",
    disableFailed: "Local search could not stop. Please try again.",
  },
  ja: {
    title: "ローカル Web 検索 (SearXNG)",
    desc: "Docker でプライベートな SearXNG をデプロイします。オフの場合は DuckDuckGo を使用します。",
    needDocker:
      "Docker のインストールと起動が必要です。Docker がない場合は DuckDuckGo を使用します。",
    up: "実行中",
    down: "停止中",
    checking: "確認中…",
    deploying: "デプロイ中（初回はイメージを取得します）…",
    unavailable: "ローカル検索の状態を取得できません。",
    retry: "再確認",
    enableFailed:
      "ローカル検索を起動できません。Docker が実行中か確認してください。",
    disableFailed: "ローカル検索を停止できません。もう一度お試しください。",
  },
  ko: {
    title: "로컬 웹 검색(SearXNG)",
    desc: "Docker로 비공개 SearXNG를 배포합니다. 끄면 DuckDuckGo를 사용합니다.",
    needDocker:
      "Docker가 설치되어 실행 중이어야 합니다. Docker가 없으면 DuckDuckGo를 사용합니다.",
    up: "실행 중",
    down: "중지됨",
    checking: "확인 중…",
    deploying: "배포 중(첫 실행 시 이미지 다운로드)…",
    unavailable: "로컬 검색 상태를 확인할 수 없습니다.",
    retry: "다시 확인",
    enableFailed:
      "로컬 검색을 시작하지 못했습니다. Docker가 실행 중인지 확인하세요.",
    disableFailed: "로컬 검색을 중지하지 못했습니다. 다시 시도하세요.",
  },
};

export function SearxngControl() {
  const { locale } = useI18n();
  const language = (locale || "en").slice(0, 2).toLowerCase();
  const t = LABELS[language as keyof typeof LABELS] ?? LABELS.en;
  const { status, isLoading, isError, refetch } = useSearxngStatus();
  const { setEnabled, isPending } = useSearxngControl();

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

  const toggle = async (checked: boolean) => {
    try {
      await setEnabled(checked);
    } catch {
      toast.error(checked ? t.enableFailed : t.disableFailed);
    }
  };

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
            <span className="text-xs text-muted-foreground">
              {t[state]}
            </span>
          </div>
          {isError ? (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p role="alert" className="text-xs text-destructive">
                {t.unavailable}
              </p>
              <Button
                type="button"
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs"
                onClick={refetch}
              >
                {t.retry}
              </Button>
            </div>
          ) : (
            <p className="mt-1 text-xs leading-snug text-muted-foreground">
              {dockerMissing ? t.needDocker : t.desc}
            </p>
          )}
        </div>
        <Switch
          checked={Boolean(status?.up || status?.managed)}
          disabled={isError || isLoading || dockerMissing || isPending}
          onCheckedChange={(checked) => void toggle(checked)}
          aria-label={t.title}
        />
      </div>
    </div>
  );
}
