import { useState } from "react";
import {
  BadgeCheckIcon,
  DownloadIcon,
  Loader2Icon,
  SparklesIcon,
  StarIcon,
} from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AuthenticatedImage } from "@/components/ui/authenticated-image";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { installAgent, uninstallAgent } from "@/core/agents/agent-world-api";
import type { AgentWorldAgent, AgentWorldCategory } from "@/core/agents/types";

// ---------------------------------------------------------------------------
// Category colours
// ---------------------------------------------------------------------------

export const CATEGORY_STYLES: Record<
  AgentWorldCategory,
  { bg: string; text: string; icon: string }
> = {
  assistant: {
    bg: "bg-blue-500/10",
    text: "text-blue-600 dark:text-blue-400",
    icon: "🤖",
  },
  coder: {
    bg: "bg-emerald-500/10",
    text: "text-emerald-600 dark:text-emerald-400",
    icon: "💻",
  },
  researcher: {
    bg: "bg-violet-500/10",
    text: "text-violet-600 dark:text-violet-400",
    icon: "🔬",
  },
  creative: {
    bg: "bg-amber-500/10",
    text: "text-amber-600 dark:text-amber-400",
    icon: "🎨",
  },
  automation: {
    bg: "bg-rose-500/10",
    text: "text-rose-600 dark:text-rose-400",
    icon: "⚡",
  },
  specialist: {
    bg: "bg-cyan-500/10",
    text: "text-cyan-600 dark:text-cyan-400",
    icon: "🎯",
  },
  financial: {
    bg: "bg-teal-500/10",
    text: "text-teal-600 dark:text-teal-400",
    icon: "💼",
  },
};

// ---------------------------------------------------------------------------
// Star rating helper
// ---------------------------------------------------------------------------

function StarRating({ rating, count }: { rating: number; count: number }) {
  return (
    <div className="flex items-center gap-1">
      <div className="flex items-center">
        {Array.from({ length: 5 }).map((_, i) => {
          const filled = i < Math.round(rating);
          return (
            <StarIcon
              key={i}
              className={cn(
                "h-3 w-3",
                filled
                  ? "fill-amber-400 text-amber-400"
                  : "fill-muted text-muted",
              )}
            />
          );
        })}
      </div>
      <span className="text-muted-foreground text-xs">
        {rating.toFixed(1)} ({count})
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Download count formatter
// ---------------------------------------------------------------------------

function formatDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// ---------------------------------------------------------------------------
// AgentWorldCard
// ---------------------------------------------------------------------------

interface AgentWorldCardProps {
  agent: AgentWorldAgent;
  onSelect?: (agent: AgentWorldAgent) => void;
  onInstallChange?: () => void;
  featured?: boolean;
}

export function AgentWorldCard({
  agent,
  onSelect,
  onInstallChange,
  featured: _featured,
}: AgentWorldCardProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [installing, setInstalling] = useState(false);
  const [installed, setInstalled] = useState(agent.is_installed);
  const catStyle = CATEGORY_STYLES[agent.category] ?? CATEGORY_STYLES.assistant;
  const categoryLabel =
    t.agentWorld.categories[agent.category] ?? agent.category;
  const keySkillCount = agent.key_skills?.length ?? 0;
  const hasCapabilityPack = keySkillCount > 0;
  const iconFallback = (
    <span className="bg-gradient-to-br from-primary/12 to-muted/35 text-primary flex h-full w-full items-center justify-center rounded-sm">
      {agent.icon || catStyle.icon}
    </span>
  );

  async function handleInstallToggle(e: React.MouseEvent) {
    e.stopPropagation();
    setInstalling(true);
    try {
      if (installed) {
        await uninstallAgent(agent.id);
        setInstalled(false);
        toast.success(t.agentWorld.toastUninstalled(agent.display_name));
      } else {
        const result = await installAgent(agent.id);
        setInstalled(true);
        const assembledSkillCount =
          result.key_skills?.length ??
          result.registered_skills ??
          keySkillCount;
        toast.success(
          assembledSkillCount > 0
            ? t.agentWorld.toastCapabilityPackInstalled(
                agent.display_name,
                assembledSkillCount,
              )
            : t.agentWorld.toastInstalled(agent.display_name),
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      onInstallChange?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling(false);
    }
  }

  return (
    <Card
      className={cn(
        "group relative flex cursor-pointer flex-col overflow-hidden rounded-lg border-border-default bg-card/86 py-0 transition-all ease-out",
        "hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-[0_0_24px_hsl(var(--primary)/0.10)]",
        "before:pointer-events-none before:absolute before:left-0 before:top-0 before:h-3 before:w-3 before:border-l before:border-t before:border-primary/45",
        "after:pointer-events-none after:absolute after:bottom-0 after:right-0 after:h-3 after:w-3 after:border-b after:border-r after:border-primary/30",
      )}
      onClick={() => onSelect?.(agent)}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-primary/35" />
      <div className="pointer-events-none absolute inset-0 opacity-0 transition-opacity [background-image:linear-gradient(180deg,transparent_0,transparent_94%,hsl(var(--primary)/0.16)_95%,transparent_100%)] [background-size:100%_18px] group-hover:opacity-100" />
      {/* Featured shimmer accent */}
      {agent.is_featured && (
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-500/60 via-primary/40 to-violet-500/60" />
      )}

      <CardHeader className="flex flex-1 flex-col px-3 pb-2 pt-3">
        {/* Icon + Title row */}
        <div className="flex items-start gap-2">
          <div className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-primary/25 bg-background text-lg shadow-[0_0_14px_hsl(var(--primary)/0.08)]">
            {agent.avatar_url ? (
              <AuthenticatedImage
                src={withAgentAvatarVersion(agent.avatar_url)}
                alt={agent.display_name}
                className="h-full w-full bg-white object-cover [image-rendering:pixelated]"
                fallback={iconFallback}
              />
            ) : (
              iconFallback
            )}
            {agent.is_official && (
              <div className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-blue-500 shadow-[var(--shadow-xs)]">
                <BadgeCheckIcon className="h-2.5 w-2.5 text-white" />
              </div>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <CardTitle className="truncate text-sm font-semibold leading-5">
                {agent.display_name}
              </CardTitle>
              {agent.is_featured && (
                <SparklesIcon className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              )}
            </div>
            <p className="text-muted-foreground mt-0.5 truncate text-xs">
              {t.agentWorld.authorPrefix} {agent.author}
            </p>
          </div>
        </div>

        {/* Description */}
        <CardDescription className="mt-2 line-clamp-2 min-h-8 text-xs leading-4 text-muted-foreground/90">
          {agent.description}
        </CardDescription>

        {/* Category + Rating */}
        <div className="mt-2 flex items-center justify-between gap-2">
          <Badge
            variant="secondary"
            className={cn(
              "text-[10px] font-medium",
              catStyle.bg,
              catStyle.text,
            )}
          >
            {categoryLabel}
          </Badge>
          <StarRating rating={agent.rating} count={agent.rating_count} />
        </div>

        {keySkillCount > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            <Badge
              variant="outline"
              className="border-primary/25 bg-primary/5 text-[10px] font-medium text-primary"
            >
              {t.agentWorld.keySkillCount(keySkillCount)}
            </Badge>
          </div>
        )}
      </CardHeader>

      <CardFooter className="relative mt-auto flex items-center justify-between gap-2 border-t border-border-default bg-background/54 px-3 py-2">
        {/* Download count */}
        <div className="text-muted-foreground flex items-center gap-1 text-xs">
          <DownloadIcon className="h-3 w-3" />
          <span>{formatDownloads(agent.downloads)}</span>
        </div>

        {/* Install / Uninstall */}
        <Button
          size="sm"
          variant={installed ? "outline" : "default"}
          className={cn(
            "h-7 rounded-sm px-3 text-xs transition-all",
            !installed && "shadow-[var(--shadow-xs)] hover:shadow-[var(--shadow-sm)]",
          )}
          disabled={installing}
          onClick={handleInstallToggle}
        >
          {installing ? (
            <Loader2Icon className="mr-1 h-3 w-3 animate-spin" />
          ) : !installed && hasCapabilityPack ? (
            <SparklesIcon className="mr-1 h-3 w-3" />
          ) : null}
          {installed
            ? t.agentWorld.agentInstalled
            : hasCapabilityPack
              ? t.agentWorld.assembleCapabilityPack
              : t.agentWorld.installThisAgent}
        </Button>
      </CardFooter>
    </Card>
  );
}

export { StarRating, formatDownloads };
