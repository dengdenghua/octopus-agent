import { BriefcaseIcon } from "lucide-react";
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
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-5 pt-1 pb-2 text-center sm:px-8",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-2xl font-semibold tracking-tight">
        {isSkillSeed ? (
          t.welcome.createYourOwnSkill
        ) : isCode ? (
          <div className="flex items-center gap-2.5">
            <BriefcaseIcon className="size-7 text-teal-600 dark:text-teal-400" />
            <span className="text-foreground">Work with Octopus</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="inline-block size-2 rounded-full bg-primary/80" />
            <span className="text-foreground">{t.welcome.greeting}</span>
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
