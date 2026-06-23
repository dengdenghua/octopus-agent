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

/**
 * Model control for local CLI partners (Codex / Claude Code).
 *
 * The Octopus model selector (mimo…) does NOT apply here — a local partner
 * runs on its own CLI with its own model namespace. This shows the CLI's
 * configured default (read from its config on the backend) and lets the user
 * free-text an override that is passed straight to the CLI via ``-m``. An empty
 * override means "use the CLI's own configured default" (no ``-m``).
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
  const [configModel, setConfigModel] = useState("");
  const [source, setSource] = useState("");
  const [draft, setDraft] = useState(value ?? "");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  useEffect(() => {
    if (!partnerId) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await fetch(
          `${getBackendBaseURL()}/api/agents/local-partners/${encodeURIComponent(
            partnerId,
          )}/model`,
          { headers: jsonAuthHeaders() },
        );
        if (!r.ok || cancelled) return;
        const j = (await r.json()) as { model?: string; source?: string };
        if (cancelled) return;
        setConfigModel(String(j?.model ?? ""));
        setSource(String(j?.source ?? ""));
      } catch {
        // best-effort: leave the default empty, the override box still works
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [partnerId]);

  const override = (value ?? "").trim();
  // What the trigger shows: the user's override, else the CLI's configured
  // model, else a neutral placeholder.
  const label = override || configModel || "CLI 默认";

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
          title="本地伙伴模型（透传给 CLI 的 -m）"
          className="inline-flex min-w-0 items-center gap-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-xs text-muted-foreground outline-none transition hover:border-border/60 hover:bg-muted/60 hover:text-foreground data-[state=open]:bg-muted data-[state=open]:text-foreground"
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
        </p>
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
