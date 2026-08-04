import {
  CheckIcon,
  CoinsIcon,
  LogOutIcon,
  RefreshCwIcon,
  SettingsIcon,
  UsersRoundIcon,
  UserCircleIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { swallow } from "@/core/utils/log";
import { ACTIVE_AGENT_KEY, ROUTE_LOCKS } from "@/core/agents/active";
import { eventBus, emitAgentChanged, emitOpenSettings } from "@/core/events";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useAgents,
  useLocalCliAgents,
  useLocalCliPartnerAgents,
  dedupeAgentsByName,
  dedupePersonaAgentsByDisplayName,
} from "@/core/agents";
import type { Agent, LocalCliPartnerAgent } from "@/core/agents";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import {
  LOCAL_AGENT_IDS,
  LOCAL_AGENT_RANK,
} from "@/components/workspace/agents/agent-world-data";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { taskWorkspaceRoute } from "@/core/router/task-workspace-route";
import { useOctLink } from "@/core/oct/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/utils";

// ─── Helpers ─────────────────────────────────────────────────────

function readActiveAgentName(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_AGENT_KEY);
  } catch (e) {
    swallow(e);
    return null;
  }
}

function isPlaceholderUsername(username?: string | null): boolean {
  const value = username?.trim().toLowerCase();
  return !value || value === "anonymous" || value === "__anonymous__";
}

function getAccountDisplayName(user: {
  mobile?: string;
  email?: string;
  username?: string;
  actor_id?: string;
}): string {
  return (
    user.mobile ||
    user.email ||
    (!isPlaceholderUsername(user.username) ? user.username : "") ||
    user.actor_id ||
    ""
  );
}

function isHubDefaultAgent(agent: Agent): boolean {
  return LOCAL_AGENT_IDS.has(agent.name);
}

function sortHubDefaultAgents(left: Agent, right: Agent): number {
  return (
    (LOCAL_AGENT_RANK.get(left.name) ?? Number.MAX_SAFE_INTEGER) -
    (LOCAL_AGENT_RANK.get(right.name) ?? Number.MAX_SAFE_INTEGER)
  );
}

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
  agent: Agent | undefined;
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
        "flex size-6 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border-default bg-muted text-sm leading-none",
        !emoji && !avatar && "font-semibold text-muted-foreground text-xs",
        className,
      )}
    >
      {showAvatar ? (
        <img
          src={avatar ?? undefined}
          alt=""
          className="size-full object-cover"
          loading="lazy"
          onError={() => setFailedAvatar(avatar)}
        />
      ) : emoji ? (
        emoji
      ) : (
        initial
      )}
    </span>
  );
}

// ─── AgentFooter ─────────────────────────────────────────────────

export function AgentFooter() {
  const { agents } = useAgents();
  const {
    cliAgents,
    isFetching: isFetchingCliAgents,
    isError: cliAgentsFailed,
    refresh: refreshCliAgents,
  } = useLocalCliAgents();
  const {
    partners: allCliPartners,
    isFetching: isFetchingAllCliPartners,
    isError: cliPartnersFailed,
    refresh: refreshAllCliPartners,
  } = useLocalCliPartnerAgents();
  const { user, logout } = useAuth();
  const _navigate = useNavigate();
  const { pathname, search } = useLocation();
  const octLink = useOctLink();
  const { t } = useI18n();
  const credits = octLink.data?.credits?.surplusCredits;
  const [activeName, setActiveName] = useState<string | null>(() =>
    readActiveAgentName(),
  );
  useEffect(() => {
    return eventBus.on("agent:changed", ({ name }) => {
      setActiveName(name);
    });
  }, []);

  const lock = ROUTE_LOCKS.find((r) => pathname.startsWith(r.prefix));
  const surfaceParam = new URLSearchParams(search).get("surface");
  const agentLibrarySurface = surfaceParam === "company" ? "company" : "chat";
  const agentLibraryHref = (tab?: string) => {
    const params = new URLSearchParams({
      hud: "1",
      surface: agentLibrarySurface,
    });
    if (tab) params.set("tab", tab);
    return `/workspace/agents?${params.toString()}`;
  };
  // Prefer the live detector for local CLIs so stale on-disk profiles cannot
  // leak an old alias, avatar, model, or capability identity into the picker.
  // Non-CLI profiles still come from the regular agent registry.
  const footerAgents = useMemo(
    () => dedupeAgentsByName([...cliAgents, ...agents]),
    [agents, cliAgents],
  );
  // A local-partner CLI is either a synthetic `local_*` entry or an on-disk
  // agent carrying the `local_partner` capability flag.
  const isLocalCliAgent = (a: Agent) =>
    a.name.startsWith("local_") || Boolean(a.capabilities?.local_partner);
  const personaAgents = useMemo(() => {
    // Show ALL persona agents (restored — the "minimal" snapshot had narrowed
    // this to hub-defaults + the active one, hiding the user's custom agents):
    // hub-default agents first in their canonical order, then custom agents.
    const nonCli = footerAgents.filter((a) => !isLocalCliAgent(a));
    const hubAgents = nonCli
      .filter(isHubDefaultAgent)
      .sort(sortHubDefaultAgents);
    const customAgents = nonCli.filter((a) => !isHubDefaultAgent(a));
    // Dedupe by base display name: "Eve / Siren" and "Eve" share the base
    // "Eve". Hub-defaults win, so the echo_* variants of the same character
    // don't show up as duplicates next to the general agent.
    return dedupePersonaAgentsByDisplayName([...hubAgents, ...customAgents]);
  }, [footerAgents]);
  const cliPartnerAgents = useMemo(
    () => footerAgents.filter(isLocalCliAgent),
    [footerAgents],
  );
  const cliPartnerAgentNames = useMemo(
    () => new Set(cliPartnerAgents.map((agent) => agent.name)),
    [cliPartnerAgents],
  );
  const cliPartnerRows = useMemo<LocalCliPartnerAgent[]>(() => {
    if (allCliPartners.length > 0) {
      return allCliPartners;
    }
    return cliPartnerAgents.map((agent) => ({
      agent,
      partnerId:
        String(agent.capabilities?.local_partner_id || "") ||
        agent.name.replace(/^local_/, "").replaceAll("_", "-"),
      detected: true,
      ready: true,
      registered: false,
      status: "detected",
      fixHint: null,
    }));
  }, [allCliPartners, cliPartnerAgents]);
  const effectiveName = lock?.agent ?? activeName ?? "general";

  const active: Agent | undefined =
    (effectiveName && footerAgents.find((a) => a.name === effectiveName)) ||
    footerAgents[0];

  const lockedAgent: Agent | undefined =
    lock && !agents.find((a) => a.name === lock.agent)
      ? {
          name: lock.agent,
          display_name:
            lock.agent === "admin" ? t.sidebar.adminAgentName : lock.agent,
          description: "",
          icon: lock.agent === "admin" ? "🛡️" : undefined,
          avatar_url: `/api/agents/${lock.agent}/avatar`,
          model: null,
          tool_groups: [],
        }
      : undefined;

  const selectAgent = (name: string) => {
    setActiveName(name);
    emitAgentChanged(name);
    _navigate(taskWorkspaceRoute({ agentId: name }));
  };

  const renderAgentItem = (a: Agent) => {
    const isActive = a.name === active?.name;
    return (
      <DropdownMenuItem
        key={a.name}
        onSelect={() => selectAgent(a.name)}
        className={cn(
          "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs",
          "opacity-85 transition-colors focus:bg-muted/60 focus:text-foreground focus:opacity-100",
          isActive && "bg-muted/35 opacity-100",
        )}
      >
        <AgentAvatar agent={a} className="size-8 rounded-lg text-xs" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate font-medium leading-none">
            {a.display_name || a.name}
          </span>
          <span className="truncate text-xs font-normal leading-tight text-muted-foreground">
            {isActive
              ? t.sidebar.currentAgent
              : a.description || t.sidebar.soloChat}
          </span>
        </span>
        {isActive && (
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <CheckIcon className="size-3" />
          </span>
        )}
      </DropdownMenuItem>
    );
  };

  const renderCliPartnerItem = (row: LocalCliPartnerAgent) => {
    const a = row.agent;
    const isSelectable = row.detected && row.ready;
    const isActive = a.name === active?.name;
    const command =
      typeof a.capabilities?.local_partner_command === "string"
        ? a.capabilities.local_partner_command
        : "";
    const statusText = row.detected
      ? row.registered || cliPartnerAgentNames.has(a.name)
        ? t.localAgentConnect.statusConnected
        : t.localAgentConnect.statusDetected
      : t.localAgentConnect.statusNotDetected;
    return (
      <DropdownMenuItem
        key={a.name}
        disabled={!isSelectable}
        onSelect={() => {
          if (isSelectable) selectAgent(a.name);
        }}
        className={cn(
          "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs",
          "opacity-85 transition-colors focus:bg-muted/60 focus:text-foreground focus:opacity-100",
          isActive && "bg-muted/35 opacity-100",
          !isSelectable && "opacity-45 focus:bg-transparent",
        )}
      >
        <AgentAvatar agent={a} className="size-8 rounded-lg text-xs" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate font-medium leading-none">
            {a.display_name || a.name}
          </span>
          <span className="truncate text-xs font-normal leading-tight text-muted-foreground">
            {row.detected
              ? command || a.description || statusText
              : row.fixHint || t.localAgentConnect.noPartnersAvailable}
          </span>
        </span>
        <span
          className={cn(
            "shrink-0 rounded-md px-1.5 py-0.5 text-2xs font-medium",
            row.detected
              ? "bg-success/10 text-success"
              : "bg-muted text-muted-foreground",
          )}
        >
          {statusText}
        </span>
        {isActive && (
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <CheckIcon className="size-3" />
          </span>
        )}
      </DropdownMenuItem>
    );
  };

  const displayAgent = lockedAgent ?? active;
  const accountName = user ? getAccountDisplayName(user) : "";

  return (
    <div className="flex items-center gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={Boolean(lock)}>
          <button
            type="button"
            disabled={Boolean(lock)}
            title={
              lock
                ? t.sidebar.lockedAgentTooltip(
                    displayAgent?.display_name || displayAgent?.name || "",
                  )
                : displayAgent?.description || t.sidebar.switchAgentLabel
            }
            aria-label={
              displayAgent?.display_name ||
              displayAgent?.name ||
              t.sidebar.switchAgentLabel
            }
            className={cn(
              "group/agent flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left",
              "opacity-85 transition-[opacity,background-color] duration-150",
              "hover:opacity-100 hover:bg-muted/50 outline-none",
              "group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0",
            )}
          >
            <AgentAvatar agent={displayAgent} />
            <span className="min-w-0 flex-1 truncate text-xs font-medium leading-tight group-data-[collapsible=icon]:hidden">
              {displayAgent?.display_name || displayAgent?.name || "Octopus"}
            </span>
            {lock ? (
              <span
                className="shrink-0 text-2xs uppercase tracking-wider text-muted-foreground/60 group-data-[collapsible=icon]:hidden"
                aria-hidden
              >
                🔒
              </span>
            ) : (
              <span className="shrink-0 text-muted-foreground/60 group-hover/agent:text-muted-foreground group-data-[collapsible=icon]:hidden">
                <svg
                  viewBox="0 0 24 24"
                  className="size-3"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <polyline points="6 15 12 9 18 15" />
                </svg>
              </span>
            )}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="top"
          align="start"
          sideOffset={6}
          className="max-h-[calc(100vh-1rem)] w-72 overflow-y-auto overscroll-contain rounded-lg border-border-default p-1.5 shadow-xl shadow-black/10"
        >
          <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            {t.sidebar.switchAgentMenuTitle}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {personaAgents.length > 0 ? (
            personaAgents.map(renderAgentItem)
          ) : (
            <div className="px-2 py-2 text-xs text-muted-foreground">
              {t.sidebar.noAgents}
            </div>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="flex items-center gap-2 px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            <span className="min-w-0 flex-1 truncate">
              {t.sidebar.localCliPartners}
            </span>
            <button
              type="button"
              disabled={isFetchingCliAgents || isFetchingAllCliPartners}
              title={t.localAgentConnect.retryDetect}
              aria-label={t.localAgentConnect.retryDetect}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void Promise.all([refreshCliAgents(), refreshAllCliPartners()]);
              }}
              className="-mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-wait disabled:opacity-50"
            >
              <RefreshCwIcon
                className={cn(
                  "size-3.5",
                  (isFetchingCliAgents || isFetchingAllCliPartners) &&
                    "animate-spin",
                )}
              />
            </button>
          </DropdownMenuLabel>
          <div aria-live="polite">
            {cliAgentsFailed && cliPartnersFailed ? (
              <div className="px-2.5 py-2 text-xs text-destructive">
                {t.localAgentConnect.detectFailed}
              </div>
            ) : (isFetchingCliAgents || isFetchingAllCliPartners) &&
              cliPartnerRows.length === 0 ? (
              <div className="px-2.5 py-2 text-xs text-muted-foreground">
                {t.localAgentConnect.detecting}
              </div>
            ) : cliPartnerRows.length === 0 ? (
              <div className="px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
                {t.localAgentConnect.noPartnersAvailable}
              </div>
            ) : null}
          </div>
          {cliPartnerRows.map(renderCliPartnerItem)}
          <DropdownMenuSeparator />
          {displayAgent ? (
            <>
              <DropdownMenuItem
                onSelect={() => _navigate(agentLibraryHref())}
                className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-muted-foreground focus:bg-muted/60 focus:text-foreground"
              >
                <UsersRoundIcon className="size-4 shrink-0" />
                <span>{t.sidebar.openAgentHud}</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          ) : null}
          <div className="flex items-center gap-2 px-2.5 py-2 text-xs text-muted-foreground">
            <UserCircleIcon className="size-4 shrink-0 opacity-70" />
            <span className="min-w-0 flex-1 truncate">{accountName}</span>
          </div>
          <DropdownMenuItem
            onSelect={() => emitOpenSettings("account")}
            className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs focus:bg-muted/60"
          >
            <CoinsIcon className="size-4 shrink-0 opacity-70" />
            <span className="min-w-0 flex-1 truncate">
              {t.sidebar.remainingCredits}
            </span>
            <span className="shrink-0 text-xs font-mono text-foreground/80">
              {typeof credits === "number" ? credits.toLocaleString() : "—"}
            </span>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => void logout()}
            className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs focus:bg-muted/60"
          >
            <LogOutIcon className="size-4 shrink-0 opacity-70" />
            <span>{t.sidebar.logout}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <button
        type="button"
        title={t.sidebar.settingsTooltip}
        aria-label={t.sidebar.settingsTooltip}
        onClick={() => emitOpenSettings()}
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground",
          "opacity-70 transition-[opacity,background-color,color] duration-150",
          "hover:bg-muted hover:text-foreground hover:opacity-100",
          "group-data-[collapsible=icon]:hidden",
        )}
      >
        <SettingsIcon className="size-4" />
      </button>
    </div>
  );
}
