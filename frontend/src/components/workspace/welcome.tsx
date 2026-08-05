import {
  BriefcaseIcon,
  Code2Icon,
  FileTextIcon,
  LayoutIcon,
  PaletteIcon,
  SparklesIcon,
  BarChart3Icon,
  BotIcon,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type SceneId = "daily" | "code" | "design" | "data" | "doc" | "agent";

const SCENES: { id: SceneId; label: string; icon: typeof BriefcaseIcon }[] = [
  { id: "daily", label: "日常办公", icon: LayoutIcon },
  { id: "code", label: "代码开发", icon: Code2Icon },
  { id: "design", label: "设计创意", icon: PaletteIcon },
  { id: "data", label: "数据分析", icon: BarChart3Icon },
  { id: "doc", label: "文档处理", icon: FileTextIcon },
  { id: "agent", label: "Agent 编排", icon: BotIcon },
];

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "chat" | "code" | "deep" | "thinking" | "flash" | "react";
}) {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const isCode = useMemo(() => mode === "code", [mode]);
  const isSkillSeed = searchParams.get("mode") === "skill";
  const [activeScene, setActiveScene] = useState<SceneId>("daily");

  const handleSceneClick = (sceneId: SceneId) => {
    setActiveScene(sceneId);
    if (sceneId === "code") {
      setSearchParams({ mode: "code" });
    } else {
      searchParams.delete("mode");
      setSearchParams(searchParams);
    }
  };

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-6 px-5 pt-8 pb-6 text-center sm:px-8",
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
      ) : isCode ? (
        <>
          <div className="flex flex-col items-center gap-4">
            <div className="relative">
              <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-primary/15 via-primary/5 to-transparent blur-xl" />
              <div className="relative flex size-16 items-center justify-center rounded-3xl border border-primary/20 bg-gradient-to-br from-primary/10 via-primary/5 to-card">
                <BriefcaseIcon className="size-8 text-primary" strokeWidth={1.5} />
              </div>
              <SparklesIcon className="absolute -top-1 -right-1 size-5 text-primary/60" strokeWidth={2} />
            </div>
            <h1 className="text-[32px] font-bold tracking-tight leading-tight">
              {t.welcome.greeting}
            </h1>
          </div>
          <p className="max-w-md text-muted-foreground/80 whitespace-pre-line text-base leading-relaxed">
            {t.welcome.description}
          </p>
        </>
      ) : (
        <>
          <div className="flex flex-col items-center gap-4">
            <h1 className="text-[32px] font-bold tracking-tight leading-tight bg-gradient-to-b from-foreground to-foreground/70 bg-clip-text text-transparent">
              Octopus，我帮你
            </h1>
            <p className="text-muted-foreground/80 text-base">
              多智能体协作 · 一个输入框，直接解决问题
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2 max-w-xl">
            {SCENES.map((scene) => {
              const Icon = scene.icon;
              const isActive = activeScene === scene.id;
              return (
                <Button
                  key={scene.id}
                  variant={isActive ? "default" : "outline"}
                  size="sm"
                  onClick={() => handleSceneClick(scene.id)}
                  className={cn(
                    "gap-1.5 rounded-full px-4",
                    isActive ? "" : "bg-transparent hover:bg-accent/50",
                  )}
                >
                  <Icon className="size-3.5" strokeWidth={2} />
                  <span className="text-sm">{scene.label}</span>
                </Button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
