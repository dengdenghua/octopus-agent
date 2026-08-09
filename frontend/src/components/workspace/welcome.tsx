import {
  Code2Icon,
  FileTextIcon,
  LayoutIcon,
  PaletteIcon,
  BarChart3Icon,
  BotIcon,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";

import { type Agent, useAgents } from "@/core/agents";
import { useActiveAgentId } from "@/core/agents/active";
import { getAssistantDisplayName } from "@/core/agents/assistant-naming";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type SceneId = "daily" | "code" | "design" | "data" | "doc" | "agent";

const SCENES: { id: SceneId; icon: typeof LayoutIcon }[] = [
  { id: "daily", icon: LayoutIcon },
  { id: "code", icon: Code2Icon },
  { id: "design", icon: PaletteIcon },
  { id: "data", icon: BarChart3Icon },
  { id: "doc", icon: FileTextIcon },
  { id: "agent", icon: BotIcon },
];

/** Pseudo agent IDs used in URLs that are not real agent names. */
const PSEUDO_AGENT_IDS = new Set(["", "new", "general", "octopus-assistant"]);

function agentDisplayName(a: Agent | null | undefined): string | null {
  if (!a) return null;
  const d = a.display_name?.trim();
  if (d) return d;
  const n = a.name?.trim();
  if (n && !PSEUDO_AGENT_IDS.has(n)) return n;
  return null;
}

function pickGreetingName(
  agentProp: Agent | null | undefined,
  agentNameProp: string | null | undefined,
  allAgents: Agent[],
  footerAgentId: string | null,
): string {
  // 1) Assistant (octopus) uses the customizable name.
  if (agentNameProp === "octopus") return getAssistantDisplayName();

  // 2) If the page resolved a real agent (not pseudo ids), use its name.
  const propDisplay = agentDisplayName(agentProp);
  if (propDisplay) return propDisplay;

  // 3) If agentName is a real agent id (not "new"/"general"/etc), look it up.
  const nameFromProp = agentNameProp?.trim() ?? "";
  if (nameFromProp && !PSEUDO_AGENT_IDS.has(nameFromProp)) {
    const found = allAgents.find((a) => a.name === nameFromProp);
    const foundDisplay = agentDisplayName(found);
    if (foundDisplay) return foundDisplay;
  }

  // 4) Fall back to the agent selected in the footer (user's last pick).
  if (footerAgentId && !PSEUDO_AGENT_IDS.has(footerAgentId)) {
    const footerAgent = allAgents.find((a) => a.name === footerAgentId);
    const footerDisplay = agentDisplayName(footerAgent);
    if (footerDisplay) return footerDisplay;
  }

  // 5) Ultimate default: Octopus brand.
  return "Octopus";
}

export function Welcome({
  className,
  agent,
  agentName,
}: {
  className?: string;
  agent?: Agent | null;
  agentName?: string | null;
}) {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const { agents: allAgents } = useAgents();
  const footerAgentId = useActiveAgentId();
  const isSkillSeed = searchParams.get("mode") === "skill";
  const isOctopus = agentName === "octopus";
  const [activeScene, setActiveScene] = useState<SceneId>("daily");

  const greetingName = useMemo(
    () => pickGreetingName(agent ?? null, agentName ?? null, allAgents, footerAgentId),
    [agent, agentName, allAgents, footerAgentId],
  );
  const agentDescription = agent?.description?.trim();

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
      ) : (
        <>
          <div className="flex flex-col items-center gap-4">
            <h1 className="text-[32px] font-bold tracking-tight leading-tight bg-gradient-to-b from-foreground to-foreground/70 bg-clip-text text-transparent">
              {t.welcome.greeting.replace("{name}", greetingName)}
            </h1>
            <p className="text-muted-foreground/80 text-base">
              {greetingName === "Octopus"
                ? t.welcome.octopusTagline
                : agentDescription || t.welcome.description}
            </p>
          </div>

          {(isOctopus || greetingName === "Octopus") && (
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
                    <span className="text-sm">{t.welcome.scenes[scene.id]}</span>
                  </Button>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
