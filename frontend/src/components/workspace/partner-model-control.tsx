import { ChevronDownIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

const COPY = {
  zh: {
    cliDefault: "CLI 默认",
    title: "本地伙伴模型",
    description: "由 CLI 自身决定，与 Octopus 模型无关。",
    current: (model: string, source: string) =>
      `当前默认 ${model}${source ? `（${source}）` : ""}。`,
    loading: "正在读取 CLI 默认模型…",
    loadFailed: "未读到 CLI 默认模型。",
    retry: "重试",
    noOverride: "此伙伴暂不从 Octopus 传递模型覆盖。",
    overrideLabel: "本次 CLI 模型覆盖",
    placeholder: (model: string) =>
      model ? `留空＝用 ${model}` : "留空＝用 CLI 默认",
    optionsHint: "CLI 可选模型，也可以继续手填新模型名",
    useDefault: "用 CLI 默认",
    apply: "应用",
  },
  en: {
    cliDefault: "CLI default",
    title: "Local partner model",
    description:
      "Controlled by the CLI itself, independently of Octopus models.",
    current: (model: string, source: string) =>
      `Current default: ${model}${source ? ` (${source})` : ""}.`,
    loading: "Loading the CLI default model…",
    loadFailed: "The CLI default model could not be read.",
    retry: "Retry",
    noOverride: "This partner does not accept model overrides from Octopus.",
    overrideLabel: "Model override for this CLI run",
    placeholder: (model: string) =>
      model
        ? `Leave blank to use ${model}`
        : "Leave blank to use the CLI default",
    optionsHint:
      "Models reported by the CLI; you can also enter another model name.",
    useDefault: "Use CLI default",
    apply: "Apply",
  },
  ja: {
    cliDefault: "CLI の既定値",
    title: "ローカルパートナーのモデル",
    description: "Octopus のモデルとは別に、CLI 自身が管理します。",
    current: (model: string, source: string) =>
      `現在の既定値: ${model}${source ? `（${source}）` : ""}。`,
    loading: "CLI の既定モデルを読み込み中…",
    loadFailed: "CLI の既定モデルを取得できません。",
    retry: "再試行",
    noOverride: "このパートナーは Octopus からのモデル上書きに未対応です。",
    overrideLabel: "この CLI 実行のモデル上書き",
    placeholder: (model: string) =>
      model ? `空欄＝${model} を使用` : "空欄＝CLI の既定値を使用",
    optionsHint: "CLI が報告したモデル。別の名前も入力できます。",
    useDefault: "CLI の既定値を使用",
    apply: "適用",
  },
  ko: {
    cliDefault: "CLI 기본값",
    title: "로컬 파트너 모델",
    description: "Octopus 모델과 별개로 CLI 자체가 관리합니다.",
    current: (model: string, source: string) =>
      `현재 기본값: ${model}${source ? ` (${source})` : ""}.`,
    loading: "CLI 기본 모델 불러오는 중…",
    loadFailed: "CLI 기본 모델을 읽지 못했습니다.",
    retry: "다시 시도",
    noOverride: "이 파트너는 Octopus의 모델 재정의를 지원하지 않습니다.",
    overrideLabel: "이 CLI 실행의 모델 재정의",
    placeholder: (model: string) =>
      model ? `비우면 ${model} 사용` : "비우면 CLI 기본값 사용",
    optionsHint: "CLI가 알려준 모델이며 다른 모델 이름도 입력할 수 있습니다.",
    useDefault: "CLI 기본값 사용",
    apply: "적용",
  },
};

/**
 * Model control for local CLI partners.
 *
 * The Octopus model selector (mimo…) does NOT apply here — a local partner
 * runs on its own CLI with its own model namespace. This shows the CLI's
 * configured default (read from its config on the backend). For CLIs with a
 * stable model override flag (Codex / Claude Code), the user can free-text an
 * override that is passed straight to that CLI. Other partners keep their own
 * configured default.
 */
export function PartnerModelControl({
  partnerId,
  value,
  onChange,
}: {
  /** e.g. "codex-cli" / "claude-code" — the CLI partner id. */
  partnerId: string;
  /** User override; empty string ⇒ use the CLI's configured default. */
  value?: string;
  onChange: (model: string) => void;
}) {
  const { t, locale } = useI18n();
  const language = (locale || "en").slice(0, 2).toLowerCase();
  const copy = COPY[language as keyof typeof COPY] ?? COPY.en;
  const [configModel, setConfigModel] = useState("");
  const [source, setSource] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [draft, setDraft] = useState(value ?? "");
  const [open, setOpen] = useState(false);
  const loadRequestRef = useRef(0);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );

  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  const loadModel = useCallback(async () => {
    if (!partnerId) return;
    const requestId = ++loadRequestRef.current;
    setConfigModel("");
    setSource("");
    setModelOptions([]);
    setLoadState("loading");
    try {
      const r = await fetch(
        `${getBackendBaseURL()}/api/agents/local-partners/${encodeURIComponent(
          partnerId,
        )}/model`,
        { headers: jsonAuthHeaders() },
      );
      if (!r.ok) throw new Error("model unavailable");
      const j = (await r.json()) as {
        model?: string;
        source?: string;
        models?: string[];
      };
      if (requestId !== loadRequestRef.current) return;
      setConfigModel(typeof j.model === "string" ? j.model : "");
      setSource(typeof j.source === "string" ? j.source : "");
      setModelOptions(
        Array.isArray(j.models)
          ? j.models.filter(
              (model): model is string => typeof model === "string",
            )
          : [],
      );
      setLoadState("ready");
    } catch {
      if (requestId === loadRequestRef.current) setLoadState("error");
    }
  }, [partnerId]);

  useEffect(() => {
    void loadModel();
    return () => {
      loadRequestRef.current += 1;
    };
  }, [loadModel]);

  const override = (value ?? "").trim();
  const supportsModelOverride =
    partnerId === "codex-cli" ||
    partnerId === "claude-code" ||
    partnerId === "codebuddy-cli";
  // What the trigger shows: the user's override, else the CLI's configured
  // model, else a neutral placeholder.
  const label =
    (supportsModelOverride ? override : "") || configModel || copy.cliDefault;

  const commit = (next: string) => {
    onChange(next.trim());
    setOpen(false);
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-testid="partner-model-trigger"
          title={t.common.localPartnerModel}
          className="inline-flex min-w-0 items-center gap-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-xs text-muted-foreground outline-none transition hover:border-border-default hover:bg-muted/60 hover:text-foreground data-[state=open]:bg-muted data-[state=open]:text-foreground"
        >
          <span className="max-w-[var(--text-truncate-md)] truncate">{label}</span>
          <ChevronDownIcon className="size-3 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        side="top"
        sideOffset={6}
        className="w-64 space-y-2 p-2"
      >
        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground/70">
          {copy.title}
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {copy.description}{" "}
          {loadState === "loading"
            ? copy.loading
            : configModel
              ? copy.current(configModel, source)
              : copy.loadFailed}
          {!supportsModelOverride ? ` ${copy.noOverride}` : ""}
        </p>
        {loadState === "error" ? (
          <button
            type="button"
            className="text-left text-xs text-primary hover:underline"
            onClick={() => void loadModel()}
          >
            {copy.retry}
          </button>
        ) : null}
        {supportsModelOverride ? (
          <>
            <Input
              value={draft}
              aria-label={copy.overrideLabel}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit(draft);
                }
              }}
              placeholder={copy.placeholder(configModel)}
              className="h-7 text-xs"
            />
            {modelOptions.length > 0 ? (
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground/70">
                  {copy.optionsHint}
                </div>
                <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto rounded-md border border-border-default/70 bg-muted/20 p-1">
                  {modelOptions.map((model) => (
                    <button
                      key={model}
                      type="button"
                      onClick={() => {
                        setDraft(model);
                        commit(model);
                      }}
                      className="max-w-full truncate rounded border border-border-default/70 px-1.5 py-0.5 text-xs text-muted-foreground transition hover:border-primary/50 hover:bg-primary/10 hover:text-foreground"
                      title={model}
                    >
                      {model}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => {
                  setDraft("");
                  commit("");
                }}
                className="text-xs text-muted-foreground transition hover:text-foreground"
              >
                {copy.useDefault}
              </button>
              <button
                type="button"
                onClick={() => commit(draft)}
                className="rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground transition hover:opacity-90"
              >
                {copy.apply}
              </button>
            </div>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
