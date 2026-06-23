import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

import type { Agent } from "./types";

/** A coding-agent CLI detected on this machine (from `/api/cli-team/status`). */
interface DetectedPartner {
  agent_id: string;
  partner_id: string;
  command: string;
}

interface CliTeamStatus {
  detected: DetectedPartner[];
  repo_root: string;
  is_git_repo: boolean;
}

const PARTNER_LABEL: Record<string, string> = {
  "claude-code": "Claude Code",
  "codex-cli": "Codex CLI",
  openclaw: "OpenClaw",
  hermes: "Hermes Agent",
};

const PARTNER_ICON: Record<string, string> = {
  "claude-code": "🟣",
  "codex-cli": "⬛",
  openclaw: "🦞",
  hermes: "🪽",
};

/** Turn a detected CLI into an `Agent` so it shows up in the team pickers
 * exactly like a built-in agent — addable, leadable, removable. The synthetic
 * `name` (`local_*`) is what the team runner routes through the CLI bridge. */
function partnerToAgent(p: DetectedPartner): Agent {
  const label = PARTNER_LABEL[p.partner_id] ?? p.partner_id;
  return {
    name: p.agent_id,
    display_name: label,
    description: `本机 ${label} · 用你的订阅，在隔离 worktree 里跑、共享团队黑板`,
    icon: PARTNER_ICON[p.partner_id] ?? "🖥️",
    // Prefer the partner's brand avatar (served once it's registered on disk);
    // the emoji icon stays as the fallback when the SVG isn't available.
    avatar_url: `/api/agents/${p.agent_id}/avatar`,
    model: null,
    tool_groups: null,
  };
}

/**
 * Detected local coding-agent CLIs (Claude Code / Codex / …) as addable team
 * members. Empty when none are installed or the backend is offline — the
 * pickers just fall back to the built-in agents.
 */
export function useLocalCliAgents(): { cliAgents: Agent[]; isLoading: boolean } {
  const { data, isLoading } = useQuery({
    queryKey: ["cli-team-status"],
    queryFn: async ({ signal }): Promise<CliTeamStatus | null> => {
      try {
        const res = await fetch(`${getBackendBaseURL()}/api/cli-team/status`, {
          signal,
        });
        if (!res.ok) return null;
        return (await res.json()) as CliTeamStatus;
      } catch {
        return null;
      }
    },
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  const cliAgents = (data?.detected ?? []).map(partnerToAgent);
  return { cliAgents, isLoading };
}
