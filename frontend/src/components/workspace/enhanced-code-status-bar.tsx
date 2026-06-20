import {
  CheckCircle2Icon,
  Loader2Icon,
  XCircleIcon,
  ZapIcon,
  BotIcon,
  UsersIcon,
  CloudIcon,
  GitBranchIcon,
  WifiIcon,
  WifiOffIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import { memo } from "react";

export type AgentMode = "fast" | "agent" | "swarms";

interface AgentStep {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "error";
}

interface EnhancedCodeStatusBarProps {
  workDir: string;
  codeMode: string;
  modelName: string;
  isLoading: boolean;
  agentMode?: AgentMode;
  agentSteps?: AgentStep[];
  isOnline?: boolean;
  deployStatus?: "idle" | "deploying" | "deployed" | "error";
  collaborators?: number;
  className?: string;
}

const modeConfig: Record<
  AgentMode,
  { icon: React.ReactNode; label: string; color: string }
> = {
  fast: {
    icon: <ZapIcon className="size-3" />,
    label: "Fast",
    color: "text-amber-500 bg-amber-500/10",
  },
  agent: {
    icon: <BotIcon className="size-3" />,
    label: "Agent",
    color: "text-violet-500 bg-violet-500/10",
  },
  swarms: {
    icon: <UsersIcon className="size-3" />,
    label: "Swarms",
    color: "text-emerald-500 bg-emerald-500/10",
  },
};

export const EnhancedCodeStatusBar = memo(function EnhancedCodeStatusBar({
  workDir,
  codeMode,
  modelName,
  isLoading,
  agentMode = "agent",
  agentSteps = [],
  isOnline = true,
  deployStatus = "idle",
  collaborators = 0,
  className,
}: EnhancedCodeStatusBarProps) {
  const { t } = useI18n();
  const mode = modeConfig[agentMode];

  const completedSteps = agentSteps.filter(
    (s) => s.status === "completed",
  ).length;
  const runningStep = agentSteps.find((s) => s.status === "running");
  const hasError = agentSteps.some((s) => s.status === "error");

  return (
    <div
      className={cn(
        "flex items-center justify-between w-full text-xs",
        className,
      )}
    >
      {/* Left section */}
      <div className="flex items-center gap-3">
        {/* Work directory */}
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <GitBranchIcon className="size-3" />
          <span className="font-mono truncate max-w-[200px]">{workDir}</span>
        </div>

        {/* Separator */}
        <div className="w-px h-3 bg-border/50" />

        {/* Agent mode indicator */}
        <div
          className={cn(
            "flex items-center gap-1.5 px-2 py-0.5 rounded-full",
            mode.color,
          )}
        >
          {mode.icon}
          <span className="font-medium">{mode.label}</span>
        </div>

        {/* Model name */}
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <BotIcon className="size-3" />
          <span>{modelName}</span>
        </div>
      </div>

      {/* Center section - Agent progress */}
      {isLoading && agentSteps.length > 0 && (
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            {hasError ? (
              <XCircleIcon className="size-3 text-rose-500" />
            ) : completedSteps === agentSteps.length ? (
              <CheckCircle2Icon className="size-3 text-emerald-500" />
            ) : (
              <Loader2Icon className="size-3 animate-spin text-violet-500" />
            )}
            <span className="text-muted-foreground">
              {runningStep?.name || t.codeStatus.processing}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {agentSteps.map((step, _idx) => (
              <div
                key={step.id}
                className={cn(
                  "size-1.5 rounded-full transition-colors",
                  step.status === "completed" && "bg-emerald-500",
                  step.status === "running" && "bg-violet-500",
                  step.status === "error" && "bg-rose-500",
                  step.status === "pending" && "bg-muted-foreground/20",
                )}
              />
            ))}
          </div>
          <span className="text-muted-foreground/60">
            {completedSteps}/{agentSteps.length}
          </span>
        </div>
      )}

      {/* Right section */}
      <div className="flex items-center gap-3">
        {/* Deploy status */}
        {deployStatus !== "idle" && (
          <div
            className={cn(
              "flex items-center gap-1.5 px-2 py-0.5 rounded-full",
              deployStatus === "deploying" && "text-amber-500 bg-amber-500/10",
              deployStatus === "deployed" &&
                "text-emerald-500 bg-emerald-500/10",
              deployStatus === "error" && "text-rose-500 bg-rose-500/10",
            )}
          >
            {deployStatus === "deploying" ? (
              <Loader2Icon className="size-3 animate-spin" />
            ) : deployStatus === "deployed" ? (
              <CloudIcon className="size-3" />
            ) : (
              <XCircleIcon className="size-3" />
            )}
            <span className="font-medium">
              {deployStatus === "deploying" && t.codeStatus.deploying}
              {deployStatus === "deployed" && t.codeStatus.deployed}
              {deployStatus === "error" && t.codeStatus.deployError}
            </span>
          </div>
        )}

        {/* Collaborators */}
        {collaborators > 0 && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <UsersIcon className="size-3" />
            <span>{collaborators}</span>
          </div>
        )}

        {/* Connection status */}
        <div className="flex items-center gap-1.5">
          {isOnline ? (
            <WifiIcon className="size-3 text-emerald-500" />
          ) : (
            <WifiOffIcon className="size-3 text-rose-500" />
          )}
        </div>

        {/* Code mode */}
        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-muted/50 text-muted-foreground">
          <CodeIcon className="size-3" />
          <span className="capitalize">{codeMode}</span>
        </div>
      </div>
    </div>
  );
});

function CodeIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  );
}
