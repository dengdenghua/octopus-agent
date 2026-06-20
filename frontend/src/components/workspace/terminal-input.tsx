import { ArrowUpIcon, SquareIcon } from "lucide-react";
import { useCallback, useRef, type KeyboardEvent } from "react";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface TerminalInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  workDir?: string;
  disabled?: boolean;
  isLoading?: boolean;
  onStop?: () => void;
  placeholder?: string;
  className?: string;
}

export function TerminalInput({
  value,
  onChange,
  onSubmit,
  onKeyDown,
  workDir,
  disabled,
  isLoading,
  onStop,
  placeholder,
  className,
}: TerminalInputProps) {
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const finalPlaceholder = placeholder ?? t.codeMode.terminalPlaceholder;

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (onKeyDown) {
        onKeyDown(e);
        if (e.defaultPrevented) return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSubmit();
      }
    },
    [onSubmit, onKeyDown],
  );

  const _shortPath = workDir ? workDir.split(/[/\\]/).slice(-2).join("/") : "~";

  return (
    <div
      className={cn(
        "rounded-lg border border-transparent bg-card overflow-hidden hover:border-border/60 focus-within:border-transparent transition-[border-color,box-shadow] duration-200",
        className,
      )}
    >
      <div className="flex items-end gap-1.5 px-2.5 py-1.5">
        <textarea
          ref={textareaRef}
          data-chat-input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={finalPlaceholder}
          rows={1}
          className={cn(
            "text-foreground flex-1 resize-none bg-transparent outline-none text-[13px] leading-snug py-1",
            "placeholder:text-muted-foreground/50",
            "disabled:opacity-50",
          )}
          style={{
            minHeight: "1.5rem",
            maxHeight: "8rem",
            height: "auto",
            overflow: value.includes("\n") ? "auto" : "hidden",
          }}
          onInput={(e) => {
            const t = e.currentTarget;
            t.style.height = "auto";
            t.style.height = `${Math.min(t.scrollHeight, 128)}px`;
          }}
        />
        {isLoading ? (
          <button
            onClick={onStop}
            title={t.codeMode.stop}
            className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground text-background hover:opacity-80 transition-opacity"
          >
            <SquareIcon className="size-3" fill="currentColor" />
          </button>
        ) : (
          <button
            onClick={onSubmit}
            disabled={disabled || !value.trim()}
            title={t.codeMode.send}
            className={cn(
              "flex size-7 shrink-0 items-center justify-center rounded-lg transition-[background-color,transform] duration-150",
              "bg-foreground text-background hover:bg-foreground/90 active:scale-95",
              "disabled:bg-muted disabled:text-muted-foreground disabled:cursor-not-allowed",
            )}
          >
            <ArrowUpIcon className="size-3.5" strokeWidth={2.25} />
          </button>
        )}
      </div>
    </div>
  );
}
