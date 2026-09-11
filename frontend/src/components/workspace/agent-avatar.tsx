import { useState } from "react";
import type { Agent } from "@/core/agents/types";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { getBackendBaseURL } from "@/core/config";
import { cn } from "@/lib/utils";

/** Resolve ``Agent.avatar_url`` to an absolute URL the browser can load. */
function resolveAvatarUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("data:") ||
    url.startsWith("blob:")
  ) {
    return withAgentAvatarVersion(url);
  }
  // API avatars belong to the Python gateway. Imported Vite assets must stay
  // on the frontend origin (and may be relative in the packaged Electron app).
  if (url.startsWith("/api/") || url.startsWith("api/")) {
    const path = url.startsWith("/") ? url : `/${url}`;
    return withAgentAvatarVersion(`${getBackendBaseURL()}${path}`);
  }
  return withAgentAvatarVersion(url);
}

// ─── Avatar components ───────────────────────────────────────────

export function AgentAvatar({
  agent,
  className,
}: {
  agent:
    | Pick<Agent, "name" | "display_name" | "avatar_url" | "icon">
    | undefined;
  className?: string;
}) {
  const avatar = resolveAvatarUrl(agent?.avatar_url);
  const [failedAvatar, setFailedAvatar] = useState<string | null>(null);
  const showAvatar = Boolean(avatar && failedAvatar !== avatar);
  const emoji = agent?.icon?.trim() || "";
  const initial = (agent?.display_name || agent?.name || "?")
    .trim()
    .charAt(0)
    .toUpperCase();
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative flex size-6 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border-default bg-muted text-sm leading-none",
        !emoji && !avatar && "font-semibold text-muted-foreground text-xs",
        className,
      )}
    >
      {emoji || initial}
      {showAvatar && (
        <img
          src={avatar ?? undefined}
          alt=""
          className="absolute inset-0 size-full object-cover"
          loading="lazy"
          onError={() => setFailedAvatar(avatar)}
        />
      )}
    </span>
  );
}
