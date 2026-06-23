import { Code2Icon } from "lucide-react";
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
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-5 pt-1 pb-2 text-center sm:px-8",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-2xl font-semibold tracking-tight">
        {isSkillSeed ? (
          t.welcome.createYourOwnSkill
        ) : isCode ? (
          <div className="flex items-center gap-2.5">
            <Code2Icon className="size-7 text-teal-600 dark:text-teal-400" />
            <AuroraText colors={colors}>Code with Octopus</AuroraText>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="inline-block size-2 rounded-full bg-primary/80" />
            <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
          </div>
        )}
        {!isSkillSeed && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-background/60 px-2 py-0.5 text-[10px] font-medium leading-4 text-muted-foreground shadow-xs">
            <span className="size-1 rounded-full bg-primary/70" />
            {modeLabel}
          </span>
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
