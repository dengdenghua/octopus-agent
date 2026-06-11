import { CheckIcon, CopyIcon, TriangleAlertIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { copyTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

type MermaidRenderResult = {
  svg: string;
  bindFunctions?: (element: Element) => void;
};

type MermaidRuntime = {
  initialize?: (config?: Record<string, unknown>) => void;
  render: (
    id: string,
    source: string,
  ) => MermaidRenderResult | Promise<MermaidRenderResult>;
};

type MermaidBlockProps = {
  code: string;
  isStreaming?: boolean;
  className?: string;
};

export function MermaidBlock({
  code,
  isStreaming = false,
  className,
}: MermaidBlockProps) {
  const rootId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [bindFunctions, setBindFunctions] = useState<
    ((element: Element) => void) | null
  >(null);
  const trimmedCode = code.trim();

  useEffect(() => {
    if (isStreaming || !trimmedCode) {
      setSvg("");
      setError(null);
      setBindFunctions(null);
      return;
    }

    let cancelled = false;
    setSvg("");
    setError(null);
    setBindFunctions(null);

    void (async () => {
      try {
        const mod = (await import("mermaid-real")) as { default: MermaidRuntime };
        if (cancelled) return;
        const mermaid = mod.default;
        mermaid.initialize?.({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "neutral",
          fontFamily: "inherit",
          flowchart: {
            htmlLabels: false,
            useMaxWidth: true,
          },
        });
        const result = await mermaid.render(
          `mermaid-chat-${rootId}`,
          trimmedCode,
        );
        if (cancelled) return;
        setSvg(result.svg);
        setBindFunctions(() => result.bindFunctions ?? null);
      } catch (caught) {
        swallow(caught);
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Render failed");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isStreaming, rootId, trimmedCode]);

  useEffect(() => {
    if (!svg || !bindFunctions || !containerRef.current) return;
    bindFunctions(containerRef.current);
  }, [bindFunctions, svg]);

  if (isStreaming || error || !svg) {
    return (
      <MermaidSourceBlock
        code={code}
        error={error}
        isStreaming={isStreaming}
        className={className}
      />
    );
  }

  return (
    <div
      className={cn(
        "not-prose my-3 overflow-hidden rounded-lg border bg-background text-foreground",
        className,
      )}
    >
      <MermaidBlockHeader code={code} />
      <div
        ref={containerRef}
        className={cn(
          "overflow-auto bg-muted/20 p-3",
          "[&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full",
        )}
        // Mermaid returns SVG markup after applying its own strict security mode.
        // biome-ignore lint/security/noDangerouslySetInnerHtml: Mermaid renderer output.
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );
}

function MermaidSourceBlock({
  code,
  error,
  isStreaming,
  className,
}: {
  code: string;
  error: string | null;
  isStreaming: boolean;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "not-prose my-3 overflow-hidden rounded-lg border bg-muted/30 text-foreground",
        className,
      )}
    >
      <MermaidBlockHeader code={code} isStreaming={isStreaming} />
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 border-b bg-destructive/5 px-3 py-2 text-xs text-destructive"
        >
          <TriangleAlertIcon className="size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Mermaid render failed</span>
        </div>
      )}
      <pre className="m-0 overflow-auto bg-transparent p-4 text-sm leading-6 whitespace-pre-wrap">
        <code>{code}</code>
        {isStreaming && (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary/60 align-middle" />
        )}
      </pre>
      {isStreaming && (
        <span className="sr-only">{t.streaming.generating}</span>
      )}
    </div>
  );
}

function MermaidBlockHeader({
  code,
  isStreaming = false,
}: {
  code: string;
  isStreaming?: boolean;
}) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await copyTextToClipboard(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (caught) {
      swallow(caught);
    }
  }, [code]);

  const Icon = copied ? CheckIcon : CopyIcon;

  return (
    <div className="flex h-8 items-center justify-between gap-2 border-b bg-muted/40 px-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="font-mono text-[10px] text-muted-foreground uppercase">
          mermaid
        </span>
        {isStreaming && (
          <>
            <span className="text-[10px] text-muted-foreground">·</span>
            <span className="animate-pulse text-[10px] text-muted-foreground">
              {t.streaming.generating}
            </span>
          </>
        )}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Copy Mermaid source"
        title="Copy Mermaid source"
        onClick={handleCopy}
      >
        <Icon className="size-3.5" />
      </Button>
    </div>
  );
}
