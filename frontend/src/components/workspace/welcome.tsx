import { useSearchParams } from "react-router-dom";
import { useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "chat" | "code" | "deep" | "thinking" | "flash" | "react";
}) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const isDeep = useMemo(() => mode === "deep", [mode]);
  const isCode = useMemo(() => mode === "code", [mode]);
  const isSkillSeed = searchParams.get("mode") === "skill";
  const colors = useMemo(() => {
    if (isDeep) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    if (isCode) {
      return ["#d1fae5", "#34d399", "#0f766e"];
    }
    return ["var(--color-foreground)"];
  }, [isCode, isDeep]);
  const modeLabel = isDeep
    ? "Deep Research"
    : isCode
      ? "Project Mode"
      : "Agent Mode";

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-3 px-5 py-4 text-center sm:px-8",
        className,
      )}
    >
      <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/72 px-2.5 py-1 text-[11px] font-medium text-muted-foreground shadow-sm">
        <span className="size-1.5 rounded-full bg-primary" />
        {modeLabel}
      </div>
      <div className="text-2xl font-semibold tracking-tight">
        {isSkillSeed ? (
          t.welcome.createYourOwnSkill
        ) : (
          <div className="flex items-center gap-2">
            <span className="inline-block size-2 rounded-full bg-primary/80" />
            <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
          </div>
        )}
      </div>
      {/* Use ``whitespace-pre-line`` so the \n in the i18n string
          still forces a line break, but the text also wraps
          naturally on narrow viewports. Pre-fix this used ``<pre>``
          which inherits the browser's monospace default font and
          refused to wrap — on mobile the description overflowed
          horizontally, and on desktop it rendered Latin text in
          monospace while the rest of the UI was sans-serif. */}
      {isSkillSeed ? (
        <p className="max-w-xl text-muted-foreground whitespace-pre-line text-sm leading-6">
          {t.welcome.createYourOwnSkillDescription}
        </p>
      ) : (
        <p className="max-w-xl text-muted-foreground whitespace-pre-line text-sm leading-6">
          {t.welcome.description}
        </p>
      )}
    </div>
  );
}
