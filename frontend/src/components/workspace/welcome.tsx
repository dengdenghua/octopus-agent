import { useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useRef } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "chat" | "deep" | "thinking" | "flash" | "react";
}) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const wavedRef = useRef(false);
  const isDeep = useMemo(() => mode === "deep", [mode]);
  const isSkillSeed = searchParams.get("mode") === "skill";
  const colors = useMemo(() => {
    if (isDeep) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isDeep]);
  useEffect(() => {
    wavedRef.current = true;
  }, []);
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      <div className="text-2xl font-bold">
        {isSkillSeed ? (
          `✨ ${t.welcome.createYourOwnSkill} ✨`
        ) : (
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "inline-block",
                !wavedRef.current ? "animate-wave" : "",
              )}
            >
              {isDeep ? "🚀" : "👋"}
            </div>
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
        <p className="text-muted-foreground whitespace-pre-line text-sm">
          {t.welcome.createYourOwnSkillDescription}
        </p>
      ) : (
        <p className="text-muted-foreground whitespace-pre-line text-sm">
          {t.welcome.description}
        </p>
      )}
    </div>
  );
}
