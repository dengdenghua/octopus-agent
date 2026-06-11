/**
 * `useActiveAgentId` — subscribes to the footer-picked agent.
 *
 * Single source of truth: ``localStorage["octopus.active-agent"]`` +
 * a ``window.octopus:active-agent`` CustomEvent that the footer
 * dropdown dispatches on change.
 *
 * Reused by:
 *   • `WorkspaceSidebar` — scope thread list to the active agent
 *   • `ChatsPage` (`app/workspace/chats/[id]/page.tsx`) — route the
 *     turn to the active agent, and invalidate thread cache on change
 *   • anywhere else that needs to know "who am I talking to"
 *
 * Without this hook, each component had its own localStorage read +
 * listener, easy to drift out of sync (and historically did: the
 * sidebar kept showing one agent's threads while chat page sent
 * another's).
 */
import { swallow } from "@/core/utils/log";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useEvent } from "../events";

export const ACTIVE_AGENT_KEY = "octopus.active-agent";
// Kept for backward compatibility with external listeners
export const ACTIVE_AGENT_EVENT = "octopus:active-agent";

export const ROUTE_LOCKS: { prefix: string; agent: string }[] = [
  // Team mode does NOT lock to a specific agent — the leader is
  // chosen by the user from the agent roster (same as chat mode).
  // This means "coder" in team mode is the SAME person as "coder"
  // in chat mode — they're just "pulled into the group".
];

function routeLock(pathname: string): string | null {
  const agentChatMatch = /^\/workspace\/agents\/([^/]+)\/chats(?:\/|$)/.exec(
    pathname,
  );
  if (agentChatMatch?.[1]) {
    try {
      return decodeURIComponent(agentChatMatch[1]);
    } catch (e) {
      swallow(e);
      return agentChatMatch[1];
    }
  }
  for (const r of ROUTE_LOCKS) {
    if (pathname.startsWith(r.prefix)) return r.agent;
  }
  return null;
}

// Agent ids the backend understands. Anything else (empty string, old
// stub DIDs, etc.) falls back to null → "no agent filter applied",
// which effectively shows all threads — right for guest/first-run,
// wrong if the user actually picked one. The sidebar filters apply
// only when this returns a known id.
const KNOWN_AGENT_IDS = new Set([
  "general",
  "coder",
  "admin",
  "vibe_selling",
  "ecommerce_mind",
  "desktop_operator",
]);


function readActive(): string | null {
  try {
    const raw = window.localStorage.getItem(ACTIVE_AGENT_KEY);
    if (raw && KNOWN_AGENT_IDS.has(raw)) return raw;
    if (raw) {
      // Stale legacy id (e.g. DID-xxx) — clean it so the UI doesn't
      // keep trying to route to a backend-unknown agent.
      window.localStorage.removeItem(ACTIVE_AGENT_KEY);
    }
  } catch (e) { swallow(e, "storage"); }
  return null;
}


/** React hook · returns the currently-active agent id (or null).
 *
 *  Routes listed in ``ROUTE_LOCK`` override the stored preference —
 *  the Code workspace ALWAYS reports ``coder``, never whatever the
 *  footer was last set to — so thread lists / stream requests / other
 *  consumers can't drift off the owning persona.
 */
export function useActiveAgentId(): string | null {
  const { pathname } = useLocation();
  const locked = routeLock(pathname);
  const [id, setId] = useState<string | null>(() => readActive());

  // Subscribe to EventBus agent changes
  useEvent("agent:changed", (payload) => {
    setId(KNOWN_AGENT_IDS.has(payload.name) ? payload.name : null);
  });

  // Handle tab-to-tab sync too — user opens Privacy in one tab,
  // switches agent in another → sidebar auto-updates.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === ACTIVE_AGENT_KEY) setId(readActive());
    }
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return locked ?? id;
}
