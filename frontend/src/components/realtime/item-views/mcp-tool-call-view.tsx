import { useState } from "react";
import {
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  PlugIcon,
  XCircleIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { swallow } from "@/core/utils/log";
import type { McpToolCallItem } from "@/core/realtime";

/**
 * Compact card for an MCP tool call — `server::tool` label, collapsed
 * JSON arguments, and a green tick / red cross for the outcome.
 *
 * Failed calls (errors set or status === "failed") get a red border;
 * inProgress calls show a pulsing indicator on the server::tool line.
 */
export function McpToolCallView({ item }: { item: McpToolCallItem }) {
  const [argsOpen, setArgsOpen] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const failed = !!item.error || item.status === "failed";
  const inProgress = item.status === "inProgress";
  const argsJson = safeStringify(item.arguments);
  const resultJson = safeStringify(item.result);
  return (
    <div
      className={cn(
        "rounded-md border p-2 text-xs",
        failed
          ? "border-red-500/40 bg-red-500/5"
          : "border-border/50 bg-muted/20",
      )}
      data-status={item.status}
    >
      <div className="flex items-center gap-2">
        <PlugIcon
          className={cn(
            "size-3.5 shrink-0",
            failed ? "text-red-500" : "text-primary",
            inProgress && "animate-pulse",
          )}
        />
        <code className="min-w-0 flex-1 truncate font-mono text-[11px] font-medium">
          <span className="text-muted-foreground">{item.server}</span>
          <span className="mx-0.5 text-muted-foreground/60">::</span>
          <span className="text-foreground">{item.tool}</span>
        </code>
        {item.durationMs != null && !inProgress && (
          <span className="font-mono text-[10px] text-muted-foreground">
            {item.durationMs}ms
          </span>
        )}
        {failed ? (
          <XCircleIcon className="size-3.5 shrink-0 text-red-500" />
        ) : !inProgress ? (
          <CheckCircle2Icon className="size-3.5 shrink-0 text-emerald-500" />
        ) : null}
      </div>

      {argsJson && argsJson !== "{}" && (
        <Collapsible
          open={argsOpen}
          onToggle={() => setArgsOpen(p => !p)}
          label="arguments"
        >
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-background/60 p-2 font-mono text-[10px] leading-snug">
            {argsJson}
          </pre>
        </Collapsible>
      )}

      {failed ? (
        <p className="mt-1.5 rounded bg-red-500/10 px-2 py-1 font-mono text-[11px] text-red-700 dark:text-red-400">
          {item.error || "(error)"}
        </p>
      ) : resultJson && resultJson !== "null" ? (
        <Collapsible
          open={resultOpen}
          onToggle={() => setResultOpen(p => !p)}
          label="result"
        >
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-background/60 p-2 font-mono text-[10px] leading-snug">
            {resultJson}
          </pre>
        </Collapsible>
      ) : null}
    </div>
  );
}

function Collapsible({
  open,
  onToggle,
  label,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDownIcon className="size-3" />
        ) : (
          <ChevronRightIcon className="size-3" />
        )}
        {label}
      </button>
      {open && children}
    </div>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch (e) {
    swallow(e);
    return String(value);
  }
}
