import { useSearchParams } from "react-router-dom";
import { InfinityIcon } from "lucide-react";

import { type Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function Welcome({
  className,
}: {
  className?: string;
  agent?: Agent | null;
  agentName?: string | null;
}) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const isSkillSeed = searchParams.get("mode") === "skill";

  return (
    <div
      data-composer-welcome="true"
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center px-5 pt-8 pb-6 text-center sm:px-8",
        className,
      )}
    >
      {isSkillSeed ? (
        <>
          <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-2xl font-semibold tracking-tight">
            {t.welcome.createYourOwnSkill}
          </div>
          <p className="max-w-xl text-muted-foreground/90 whitespace-pre-line text-sm leading-relaxed">
            {t.welcome.createYourOwnSkillDescription}
          </p>
        </>
      ) : (
        <div className="inline-flex items-center justify-center gap-2.5 sm:gap-3">
          <span
            className="grid size-9 shrink-0 place-items-center rounded-[11px] bg-[#111] text-white shadow-sm sm:size-10 sm:rounded-xl dark:bg-white dark:text-black"
            aria-hidden="true"
          >
            <InfinityIcon className="size-5 sm:size-6" strokeWidth={2} />
          </span>
          <h2 className="whitespace-nowrap text-[26px] leading-tight font-semibold tracking-[-0.035em] text-foreground sm:text-[32px]">
            Echo Everything
          </h2>
        </div>
      )}
    </div>
  );
}
