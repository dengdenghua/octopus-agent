import { useMemo, memo } from "react";
import type { AnchorHTMLAttributes, HTMLAttributes, ReactElement } from "react";
import type { BundledLanguage } from "shiki";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import {
  CodeBlock,
  CodeBlockCopyButton,
} from "@/components/ai-elements/code-block";
import { FileReferenceChip } from "@/components/ui/file-reference-chip";
import { stripLeakedRendererMarkup } from "@/core/messages/utils";
import { useLocalSettings } from "@/core/settings";
import { useStreamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { MermaidBlock } from "./mermaid-block";

/**
 * Chat font-size → ``prose-*`` variant.
 *
 * The old implementation wrapped the markdown content in a
 * ``<div className="text-[Npx] leading-[N]">`` override. That broke
 * tailwindcss-typography's em-based cascade: ``prose`` computes
 * h1/h2/p/ul/blockquote sizes as multiples of the root font-size, so
 * forcing a concrete pixel size at the root collapses the heading
 * hierarchy and throws off paragraph rhythm and list alignment.
 *
 * Using the official ``prose-sm|base|lg`` variants keeps all relative
 * proportions intact — headings stay proportionally larger than body,
 * list indents stay aligned, code and blockquote padding stays sane.
 */
const CHAT_PROSE_SIZE: Record<"small" | "medium" | "large", string> = {
  small: "prose-sm",
  medium: "prose-base",
  large: "prose-lg",
};

function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

/**
 * Hide leaked runtime control tags without changing examples inside fenced
 * code blocks. Historical messages pass through this renderer too, so the
 * display repairs already-persisted replies as well as new streams.
 */
export function stripLeakedControlMarkup(value: string): string {
  return stripLeakedRendererMarkup(value, { trim: false });
}

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
  chatFontSize?: "small" | "medium" | "large";
};

/**
 * Renders markdown content via Streamdown + shiki syntax highlighting.
 *
 * Wrapped in React.memo so that completed (non-streaming) messages
 * skip re-rendering when the parent re-renders due to an unrelated
 * streaming token in a different group. The custom comparator checks
 * only the props that affect output: content, isLoading, prose size,
 * and component overrides.
 */
export const MarkdownContent = memo(
  function MarkdownContent({
    content,
    isLoading,
    rehypePlugins,
    className,
    remarkPlugins,
    components: componentsFromProps,
    chatFontSize: chatFontSizeProp,
  }: MarkdownContentProps) {
    const [settings] = useLocalSettings();
    const streamdownPlugins = useStreamdownPlugins();
    const resolvedRemarkPlugins =
      remarkPlugins ?? streamdownPlugins.remarkPlugins;
    const proseSizeClass =
      CHAT_PROSE_SIZE[chatFontSizeProp ?? settings.display.chat_font_size];
    const components = useMemo(() => {
      return {
        a: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => {
          if (typeof props.children === "string") {
            const match = /^citation:(.+)$/.exec(props.children);
            if (match) {
              const [, text] = match;
              return <CitationLink {...props}>{text}</CitationLink>;
            }
          }
          const { className, target, rel, ...rest } = props;
          const external = isExternalUrl(props.href);
          return (
            <a
              {...rest}
              className={cn(
                "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
                className,
              )}
              target={target ?? (external ? "_blank" : undefined)}
              rel={rel ?? (external ? "noopener noreferrer" : undefined)}
            />
          );
        },
        pre: (
          props: HTMLAttributes<HTMLPreElement> & {
            children?: React.ReactNode;
          },
        ) => {
          const codeChild = Array.isArray(props.children)
            ? props.children.find(
                (
                  c,
                ): c is ReactElement<{
                  className?: string;
                  children?: React.ReactNode;
                }> => c?.props?.className?.includes("language-"),
              )
            : (props.children as
                | ReactElement<{
                    className?: string;
                    children?: React.ReactNode;
                  }>
                | undefined);

          if (codeChild?.props) {
            const className = codeChild.props.className || "";
            const langMatch = className.match(/language-([\w-]+)/);
            const language = langMatch?.[1] ?? "text";
            const code = codeChild.props.children || "";

            if (typeof code === "string") {
              const normalizedLanguage = language.toLowerCase();
              if (
                normalizedLanguage === "mermaid" ||
                normalizedLanguage === "mmd"
              ) {
                return (
                  <MermaidBlock
                    code={code}
                    isStreaming={isLoading}
                    className="my-3"
                  />
                );
              }

              return (
                <CodeBlock
                  code={code}
                  language={language as BundledLanguage}
                  isStreaming={isLoading}
                  showLineNumbers={code.split("\n").length > 3}
                  className="my-3"
                >
                  <CodeBlockCopyButton />
                </CodeBlock>
              );
            }
          }

          return <pre {...props} />;
        },
        // File citation. The rehypeFileReferences plugin has
        // transformed inline `path.ext:12-34` code into a <file-ref> element
        // carrying path + lines as data attributes; we render it as a chip.
        "file-ref": (props: { path?: string; lines?: string }) => {
          if (!props.path) return null;
          return <FileReferenceChip path={props.path} lines={props.lines} />;
        },
        ...componentsFromProps,
      };
    }, [componentsFromProps, isLoading]);

    if (!content) return null;
    const publicContent = stripLeakedControlMarkup(content);
    if (!publicContent) return null;

    // Pass the prose-size variant *into* MessageResponse's className rather
    // than wrapping in an outer <div>. MessageResponse forwards the class
    // onto Streamdown's root prose container, so the cascade inside — h1/h2/
    // p/ul/blockquote — stays relative to prose's baseline.
    // `key` forces a clean remount on the stream→settled transition so the
    // settled state (data-is-animating="false", no aria-busy) is signaled even
    // when Streamdown memoizes parsed blocks by content. Removing it left the
    // busy attributes stuck after completion (regression; see spec fallback).
    return (
      <MessageResponse
        key={isLoading ? "streaming" : "settled"}
        className={cn("chat-markdown", proseSizeClass, className)}
        remarkPlugins={resolvedRemarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
        isAnimating={isLoading}
        aria-busy={isLoading || undefined}
      >
        {publicContent}
      </MessageResponse>
    );
  },
  (prev, next) => {
    return (
      prev.content === next.content &&
      prev.isLoading === next.isLoading &&
      prev.className === next.className &&
      prev.chatFontSize === next.chatFontSize &&
      prev.remarkPlugins === next.remarkPlugins &&
      prev.rehypePlugins === next.rehypePlugins &&
      prev.components === next.components
    );
  },
);
