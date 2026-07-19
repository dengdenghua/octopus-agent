import { ChevronDownIcon } from "lucide-react";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

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
  const { t } = useI18n();
  const [configModel, setConfigModel] = useState("");
  const [source, setSource] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [draft, setDraft] = useState(value ?? "");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  useEffect(() => {
    if (!partnerId) return;
    let cancelled = false;
    setConfigModel("");
    setSource("");
    setModelOptions([]);
    void (async () => {
      try {
        const r = await fetch(
          `${getBackendBaseURL()}/api/agents/local-partners/${encodeURIComponent(
            partnerId,
          )}/model`,
          { headers: jsonAuthHeaders() },
        );
        if (!r.ok || cancelled) return;
        const j = (await r.json()) as {
          model?: string;
          source?: string;
          models?: string[];
        };
        if (cancelled) return;
        setConfigModel(String(j?.model ?? ""));
        setSource(String(j?.source ?? ""));
        setModelOptions(Array.isArray(j?.models) ? j.models.map(String) : []);
      } catch {
        // best-effort: leave the default empty, the override box still works
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [partnerId]);

  const override = (value ?? "").trim();
  const supportsModelOverride =
    partnerId === "codex-cli" ||
    partnerId === "claude-code" ||
    partnerId === "codebuddy-cli";
  // What the trigger shows: the user's override, else the CLI's configured
  // model, else a neutral placeholder.
  const label =
    (supportsModelOverride ? override : "") || configModel || "CLI 默认";

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
          <span className="max-w-[140px] truncate">{label}</span>
          <ChevronDownIcon className="size-3 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        side="top"
        sideOffset={6}
        className="w-64 space-y-2 p-2"
      >
        <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
          本地伙伴模型
        </div>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          由 CLI 自身决定，与 Octopus 模型无关。
          {configModel ? (
            <>
              {" "}
              当前默认 <span className="font-medium text-foreground">{configModel}</span>
              {source ? `（${source}）` : ""}。
            </>
          ) : (
            " 未读到默认模型。"
          )}
          {!supportsModelOverride ? " 此伙伴暂不从 Octopus 传模型覆盖。" : ""}
        </p>
        {supportsModelOverride ? (
          <>
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit(draft);
                }
              }}
              placeholder={
                configModel ? `留空＝用 ${configModel}` : "留空＝用 CLI 默认"
              }
              className="h-7 text-xs"
            />
            {modelOptions.length > 0 ? (
              <div className="space-y-1">
                <div className="text-[10px] text-muted-foreground/70">
                  CLI 可选模型，也可以继续手填新模型名
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
                      className="max-w-full truncate rounded border border-border-default/70 px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:border-primary/50 hover:bg-primary/10 hover:text-foreground"
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
                className="text-[11px] text-muted-foreground transition hover:text-foreground"
              >
                用 CLI 默认
              </button>
              <button
                type="button"
                onClick={() => commit(draft)}
                className="rounded-md bg-primary px-2 py-1 text-[11px] text-primary-foreground transition hover:opacity-90"
              >
                应用
              </button>
            </div>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
