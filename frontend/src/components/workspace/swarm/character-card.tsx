import { cn } from "@/lib/utils";

import type { SwarmAgent } from "./types";

interface CharacterCardProps {
  agent: SwarmAgent;
  onHire?: () => void;
  className?: string;
}

/**
 * "Character standee" used when an agent first spawns. Gives creation
 * narrative weight — named teammate is joining rather than a numbered
 * worker booting up.
 */
export function AgentCharacterCard({
  agent,
  onHire,
  className,
}: CharacterCardProps) {
  const bg = `hsl(${agent.hue} 55% 96%)`;
  const accent = `hsl(${agent.hue} 65% 45%)`;
  return (
    <div className={cn("flex flex-col items-center gap-4", className)}>
      {/* String that the card hangs from */}
      <div className="flex flex-col items-center">
        <div className="h-6 w-px bg-foreground/70" />
        <div
          className="h-1.5 w-10 rounded-lg"
          style={{ background: "var(--foreground)" }}
        />
      </div>

      <div
        className="relative w-64 overflow-hidden rounded-lg border border-border bg-card shadow-xl"
        style={{ background: bg }}
      >
        {/* Name header */}
        <div className="px-4 pt-4">
          <div className="text-lg font-semibold text-foreground">
            {agent.name}
          </div>
        </div>

        {/* Avatar */}
        <div
          className="mx-4 my-3 flex aspect-square items-center justify-center rounded-lg"
          style={{ background: "white" }}
        >
          <span style={{ fontSize: 64 }}>{agent.avatarEmoji}</span>
        </div>

        {/* Role & motto */}
        <div className="px-4 pb-3 text-center">
          <div className="text-sm font-bold" style={{ color: accent }}>
            {agent.role}
          </div>
          <div className="text-muted-foreground mt-1 text-xs italic">
            "{agent.motto}"
          </div>
        </div>

        {/* Skill badges */}
        {agent.skills.length > 0 && (
          <div className="flex flex-wrap justify-center gap-1 px-4 pb-3">
            {agent.skills.slice(0, 3).map((s) => (
              <span
                key={s}
                className="rounded-lg border border-border/60 bg-white/70 px-2 py-0.5 text-[10px] text-foreground/70"
              >
                ⚙ {s}
              </span>
            ))}
          </div>
        )}

        {/* Stats row */}
        {agent.stats && (
          <div className="border-t border-border/40 bg-white/40 px-4 py-2 text-center text-[10px] text-muted-foreground">
            战绩 {agent.stats.taskCount ?? 0}
            {agent.stats.rating ? ` · ★ ${agent.stats.rating.toFixed(1)}` : ""}
            {agent.personality && agent.personality.length > 0
              ? ` · ${agent.personality.join(" / ")}`
              : ""}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border/40 bg-background/60 px-4 py-2">
          <span className="text-[10px] font-bold tracking-widest text-foreground/60">
            OCTOPUS
          </span>
          <button
            type="button"
            onClick={onHire}
            className="rounded-lg px-3 py-1 text-[10px] font-medium text-white transition-opacity hover:opacity-90"
            style={{ background: accent }}
          >
            做伯乐吧
          </button>
        </div>
      </div>
    </div>
  );
}
