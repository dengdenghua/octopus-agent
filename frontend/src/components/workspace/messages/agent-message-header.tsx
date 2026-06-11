
import { Badge } from "@/components/ui/badge";
import { getBackendBaseURL } from "@/core/config";
import { cn } from "@/lib/utils";

interface AgentMessageHeaderProps {
  agentDisplayName: string;
  avatarUrl?: string;
  icon?: string | null;
  role?: "tl" | "member";
}

export function AgentAvatar({
  agentDisplayName,
  avatarUrl,
  icon,
  className = "h-6 w-6 rounded-lg",
}: {
  agentDisplayName: string;
  avatarUrl?: string;
  icon?: string | null;
  className?: string;
}) {
  const backendBase = getBackendBaseURL();
  const fullAvatarUrl = avatarUrl
    ? avatarUrl.startsWith("http")
      ? avatarUrl
      : `${backendBase}${avatarUrl}`
    : null;
  const emoji = icon?.trim() || "";
  const initial = (agentDisplayName || "?").trim().charAt(0).toUpperCase();

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden border border-border/60 bg-muted text-[13px] leading-none",
        !fullAvatarUrl && !emoji && "text-[11px] font-semibold text-muted-foreground",
        className,
      )}
    >
      {fullAvatarUrl ? (
        <img
          src={fullAvatarUrl}
          alt={agentDisplayName}
          className="h-full w-full object-cover"
        />
      ) : emoji ? (
        emoji
      ) : (
        initial
      )}
    </div>
  );
}

export function AgentMessageHeader({
  agentDisplayName,
  avatarUrl,
  icon,
  role,
}: AgentMessageHeaderProps) {
  return (
    <div className="mt-3 mb-1 flex items-center gap-2 first:mt-0">
      <AgentAvatar
        agentDisplayName={agentDisplayName}
        avatarUrl={avatarUrl}
        icon={icon}
      />
      <span className="text-sm font-semibold">{agentDisplayName}</span>
      {role === "tl" && (
        <Badge
          variant="outline"
          className="border-emerald-500/50 bg-emerald-500/10 text-emerald-600 px-1.5 py-0 text-[10px] leading-4 dark:text-emerald-400"
        >
          TL
        </Badge>
      )}
    </div>
  );
}
