import { Button } from "@/components/ui/button";
import { swallow } from "@/core/utils/log";
import { copyTextToClipboard } from "@/core/clipboard";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import { CheckIcon, CopyIcon } from "lucide-react";
import { useTheme } from "next-themes";
import {
  type ComponentProps,
  createContext,
  type HTMLAttributes,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { BundledLanguage, ShikiTransformer } from "shiki";

type CodeBlockProps = HTMLAttributes<HTMLDivElement> & {
  code: string;
  language: BundledLanguage;
  showLineNumbers?: boolean;
  isStreaming?: boolean;
};

type CodeBlockContextType = {
  code: string;
  isStreaming: boolean;
};

const CodeBlockContext = createContext<CodeBlockContextType>({
  code: "",
  isStreaming: false,
});

const lineNumberTransformer: ShikiTransformer = {
  name: "line-numbers",
  line(node, line) {
    node.children.unshift({
      type: "element",
      tagName: "span",
      properties: {
        className: [
          "inline-block",
          "min-w-10",
          "mr-4",
          "text-right",
          "select-none",
          "text-muted-foreground",
        ],
      },
      children: [{ type: "text", value: String(line) }],
    });
  },
};

export async function highlightCode(
  code: string,
  language: BundledLanguage,
  showLineNumbers = false,
  theme: "one-light" | "one-dark-pro" = "one-dark-pro",
) {
  const { codeToHtml } = await import("shiki");
  const transformers: ShikiTransformer[] = showLineNumbers
    ? [lineNumberTransformer]
    : [];

  return await codeToHtml(code, {
    lang: language,
    theme,
    transformers,
  });
}

/**
 * Classes applied to the <pre> element in BOTH modes (plain stream and
 * Shiki-highlighted). Kept identical so that when we swap from the
 * streaming plain <pre> to Shiki's highlighted <pre> there is zero
 * geometry change — no height jump, no padding shift, no margin
 * re-collapse. The visual difference is only colors.
 */
const PRE_CLASS_OVERRIDES =
  "[&>pre]:m-0 [&>pre]:p-4 [&>pre]:text-sm [&>pre]:leading-6 " +
  "[&>pre]:whitespace-pre-wrap [&>pre]:bg-transparent! " +
  "[&_code]:font-mono [&_code]:text-sm";

function LightweightCodeBlock({ code }: { code: string }) {
  // Exactly the same <pre> shape the Shiki output uses — just without
  // syntax coloring. The `overflow-auto` wrapper and class contract
  // matches the highlighted variant below.
  return (
    <pre className="m-0 p-4 text-sm leading-6 whitespace-pre-wrap bg-transparent font-mono">
      <code>{code}</code>
      <span className="inline-block w-0.5 h-4 bg-primary/60 ml-0.5 align-middle animate-pulse" />
    </pre>
  );
}

export const CodeBlock = ({
  code,
  language,
  showLineNumbers = false,
  isStreaming = false,
  className,
  children,
  ...props
}: CodeBlockProps) => {
  const { resolvedTheme } = useTheme();
  const { t } = useI18n();
  const isDark = resolvedTheme === "dark";
  const shikiTheme = isDark ? "one-dark-pro" : "one-light";
  const [html, setHtml] = useState<string>("");
  const mountedRef = useRef(false);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const highlightRequestRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      highlightRequestRef.current++;
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
        highlightTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const requestId = ++highlightRequestRef.current;
    const applyHighlight = (result: string) => {
      if (mountedRef.current && highlightRequestRef.current === requestId) {
        setHtml(result);
      }
    };

    if (highlightTimerRef.current) {
      clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
    setHtml("");

    if (isStreaming) {
      highlightTimerRef.current = setTimeout(() => {
        highlightTimerRef.current = null;
        void highlightCode(code, language, showLineNumbers, shikiTheme).then(
          applyHighlight,
        );
      }, 150);
    } else {
      void highlightCode(code, language, showLineNumbers, shikiTheme).then(
        applyHighlight,
      );
    }

    return () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
        highlightTimerRef.current = null;
      }
    };
  }, [code, language, showLineNumbers, isStreaming, shikiTheme]);

  const showHighlighted = !!html;
  const streamingHeader = isStreaming && !showHighlighted;

  return (
    <CodeBlockContext.Provider value={{ code, isStreaming }}>
      <div
        className={cn(
          "group bg-muted/30 text-foreground relative size-full overflow-hidden rounded-lg border",
          className,
        )}
        {...props}
      >
        <div className="flex h-8 items-center justify-between gap-2 border-b bg-muted/40 px-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground font-mono uppercase">
              {language}
            </span>
            {streamingHeader && (
              <>
                <span className="text-[10px] text-muted-foreground">·</span>
                <span className="text-[10px] text-muted-foreground animate-pulse">
                  {t.streaming.generating}
                </span>
              </>
            )}
          </div>
          {children && (
            <div className="flex items-center gap-2">{children}</div>
          )}
        </div>

        <div className="relative size-full">
          {showHighlighted ? (
            <div
              className={cn("size-full overflow-auto", PRE_CLASS_OVERRIDES)}
              // biome-ignore lint/security/noDangerouslySetInnerHtml: "shiki output is sanitized html"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <div className="size-full overflow-auto">
              <LightweightCodeBlock code={code} />
            </div>
          )}
        </div>
      </div>
    </CodeBlockContext.Provider>
  );
};

export type CodeBlockCopyButtonProps = ComponentProps<typeof Button> & {
  onCopy?: () => void;
  onError?: (error: Error) => void;
  timeout?: number;
  showWhileStreaming?: boolean;
};

export const CodeBlockCopyButton = ({
  onCopy,
  onError,
  timeout = 2000,
  showWhileStreaming = false,
  children,
  className,
  ...props
}: CodeBlockCopyButtonProps) => {
  const [isCopied, setIsCopied] = useState(false);
  const { code, isStreaming } = useContext(CodeBlockContext);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const copyToClipboard = async () => {
    if (typeof window === "undefined" || !navigator?.clipboard?.writeText) {
      onError?.(new Error("Clipboard API not available"));
      return;
    }

    try {
      await copyTextToClipboard(code);
      setIsCopied(true);
      onCopy?.();
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setIsCopied(false), timeout);
    } catch (error) {
      swallow(error);
      onError?.(error as Error);
    }
  };

  const Icon = isCopied ? CheckIcon : CopyIcon;

  if (isStreaming && !showWhileStreaming) {
    return null;
  }

  return (
    <Button
      className={cn("shrink-0 h-6 w-6", className)}
      onClick={copyToClipboard}
      size="icon"
      variant="ghost"
      {...props}
    >
      {children ?? <Icon size={12} />}
    </Button>
  );
};
