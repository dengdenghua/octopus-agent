import { MonitorIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { AgentRunState } from "../agent-run-status";
import {
  agentRunStatusLightPulseClass,
  agentRunStatusLightClass,
} from "../agent-run-status";

export function MainComputerStatusButton({
  active,
  label,
  onClick,
  runState,
  title,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  runState: AgentRunState;
  title: string;
}) {
  const { t } = useI18n();
  const buttonClassName = cn(
    "relative flex size-9 shrink-0 items-center justify-center rounded-md font-mono transition-colors",
    active
      ? "bg-muted/60 text-foreground"
      : "bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
  );
  const iconClassName = "size-4 transition-colors";
  const pulseClassName = agentRunStatusLightPulseClass(runState);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          className={buttonClassName}
          aria-pressed={active}
          aria-label={`${t.agentWorkbenchPanel.currentConversation} · ${label}`}
          title={`${t.agentWorkbenchPanel.currentConversation} · ${label}`}
        >
          <MonitorIcon className={iconClassName} />
          {runState !== "done" && (
            <span
              className={cn(
                "absolute top-0.5 right-0.5 size-1.5 rounded-full ring-2 ring-background",
                agentRunStatusLightClass(runState),
                pulseClassName,
              )}
            />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent align="start" side="bottom" className="max-w-52">
        <div className="font-medium">
          {t.agentWorkbenchPanel.currentConversation}
        </div>
        <div className="mt-0.5 text-xs opacity-80">
          {t.agentWorkbenchPanel.currentConversation}
          {" · "}
          {label}
        </div>
        <div className="mt-1 text-xs opacity-75">{title}</div>
      </TooltipContent>
    </Tooltip>
  );
}
