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
  "trae-cli": "Trae CLI",
  "qoder-cli": "Qoder CLI",
  "kimi-cli": "Kimi CLI",
  "codebuddy-cli": "CodeBuddy CLI",
  openclaw: "OpenClaw",
  hermes: "Hermes Agent",
};

const PARTNER_ICON: Record<string, string> = {
  "claude-code": "🟣",
  "codex-cli": "⬛",
  "trae-cli": "🟦",
  "qoder-cli": "🟧",
  "kimi-cli": "🌙",
  "codebuddy-cli": "🟢",
  openclaw: "🦞",
  hermes: "🪽",
};

const PARTNER_LOGO_URL: Record<string, string> = {
  "claude-code": "https://claude.ai/favicon.ico",
  "codex-cli": "https://chatgpt.com/favicon.ico",
  "trae-cli":
    "https://lf-static.traecdn.us/obj/trae-ai-tx/trae_website/favicon.png",
  "qoder-cli":
    "https://img.alicdn.com/imgextra/i3/O1CN01KliT1u1jEq947NlKH_!!6000000004517-55-tps-180-180.svg",
  "kimi-cli": "https://www.kimi.com/favicon.ico",
  "codebuddy-cli":
    "https://codebuddy-1328495429.cos.accelerate.myqcloud.com/web/ide/logo.svg",
};

const DRIVABLE_PARTNERS = new Set([
  "claude-code",
  "codex-cli",
  "trae-cli",
  "qoder-cli",
  "codebuddy-cli",
]);

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
    // Prefer the partner's brand logo; the emoji icon stays as the fallback.
    avatar_url:
      PARTNER_LOGO_URL[p.partner_id] ?? `/api/agents/${p.agent_id}/avatar`,
    model: null,
    tool_groups: null,
    capabilities: {
      local_partner: DRIVABLE_PARTNERS.has(p.partner_id),
      local_partner_id: p.partner_id,
      local_partner_command: p.command,
    },
  };
}

/**
 * Detected local coding-agent CLIs (Claude Code / Codex / Trae / Qoder / …) as addable team
 * members. Empty when none are installed or the backend is offline — the
 * pickers just fall back to the built-in agents.
 */
export function useLocalCliAgents(): {
  cliAgents: Agent[];
  isLoading: boolean;
} {
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

/**
 * Dedupe the picker's agent list by `name`, keeping the first occurrence.
 *
 * A detected local CLI (e.g. `local_codex_cli`) is synthesized by
 * {@link useLocalCliAgents} AND — once it has an on-disk profile — also comes
 * back from the backend via `useAgents()`. Merging both sources lands two
 * agents with the same `name`, which the pickers use as the React `key`,
 * producing the "Encountered two children with the same key" error and risking
 * dropped/duplicated rows. Callers merge as `[...mobile, ...cli, ...builtin]`,
 * so first-wins keeps the synthetic CLI entry (purpose-built for the picker,
 * shown only when the CLI is actually detected) when present, and otherwise
 * falls back to the registered backend agent. Both share the same `name`, so
 * routing is identical either way.
 */
export function dedupeAgentsByName(agents: Agent[]): Agent[] {
  const seen = new Set<string>();
  return agents.filter((a) => {
    if (seen.has(a.name)) return false;
    seen.add(a.name);
    return true;
  });
}
