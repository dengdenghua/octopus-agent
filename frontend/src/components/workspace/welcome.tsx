import { BriefcaseIcon, SparklesIcon } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "chat" | "code" | "deep" | "thinking" | "flash" | "react";
}) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const isCode = useMemo(() => mode === "code", [mode]);
  const isSkillSeed = searchParams.get("mode") === "skill";
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-3 px-5 pt-2 pb-4 text-center sm:px-8",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-2xl font-semibold tracking-tight">
        {isSkillSeed ? (
          t.welcome.createYourOwnSkill
        ) : isCode ? (
          <div className="flex flex-col items-center gap-3">
            <div className="relative">
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/20 via-primary/5 to-transparent blur-lg" />
              <div className="relative flex size-14 items-center justify-center rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-primary/5 to-card shadow-[var(--shadow-sm)]">
                <BriefcaseIcon className="size-7 text-primary" strokeWidth={1.5} />
              </div>
              <SparklesIcon className="absolute -top-1 -right-1 size-4 text-primary/50" strokeWidth={2} />
            </div>
            <span className="bg-gradient-to-r from-foreground to-foreground/80 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
              {t.welcome.greeting}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2.5">
            <span className="relative flex size-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/40 opacity-75 motion-reduce:animate-none" />
              <span className="relative inline-flex size-3 rounded-full bg-primary/80 shadow-[0_0_8px_rgba(138,127,255,0.4)]" />
            </span>
            <span className="text-foreground">{t.welcome.greeting}</span>
          </div>
        )}
      </div>
      {isSkillSeed ? (
        <p className="max-w-xl text-muted-foreground/90 whitespace-pre-line text-sm leading-relaxed">
          {t.welcome.createYourOwnSkillDescription}
        </p>
      ) : isCode ? (
        <p className="max-w-md text-muted-foreground/80 whitespace-pre-line text-[13px] leading-relaxed">
          {t.welcome.description}
        </p>
      ) : (
        <p className="max-w-xl text-muted-foreground/90 whitespace-pre-line text-sm leading-relaxed">
          {t.welcome.description}
        </p>
      )}
    </div>
  );
}
