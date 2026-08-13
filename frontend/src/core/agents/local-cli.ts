import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

import { listLocalAgentPartners, type LocalAgentPartner } from "./api";
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

export interface LocalCliPartnerAgent {
  agent: Agent;
  partnerId: string;
  detected: boolean;
  ready: boolean;
  registered: boolean;
  status: string;
  fixHint?: string | null;
}

const PARTNER_LABEL: Record<string, string> = {
  "claude-code": "Claude Code",
  "codex-cli": "Codex CLI",
  "trae-cli": "Trae CLI",
  "qoder-cli": "Qoder CLI",
  "kimi-cli": "Kimi CLI",
  "codebuddy-cli": "CodeBuddy CLI",
  "opencode-cli": "OpenCode CLI",
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
  "opencode-cli": "🟩",
  openclaw: "🦞",
  hermes: "🪽",
};

const DRIVABLE_PARTNERS = new Set([
  "claude-code",
  "codex-cli",
  "trae-cli",
  "qoder-cli",
  "codebuddy-cli",
  "opencode-cli",
  "hermes",
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
    avatar_url: `/api/agents/${p.agent_id}/avatar`,
    model: null,
    tool_groups: null,
    capabilities: {
      local_partner: DRIVABLE_PARTNERS.has(p.partner_id),
      local_partner_id: p.partner_id,
      local_partner_command: p.command,
    },
  };
}

function localPartnerToAgent(
  partner: LocalAgentPartner,
  detected?: DetectedPartner,
): Agent {
  const partnerId = partner.id;
  const label = partner.name || PARTNER_LABEL[partnerId] || partnerId;
  const command =
    detected?.command || partner.command || partner.executable || "";
  return {
    name: partner.agent_id,
    display_name: label,
    description:
      partner.setup_hint ||
      partner.description ||
      `本机 ${label} · 用你的订阅，在隔离 worktree 里跑、共享团队黑板`,
    icon:
      partner.id === "claude-code"
        ? "CC"
        : (partner.icon ?? PARTNER_ICON[partnerId] ?? "CLI"),
    avatar_url: `/api/agents/${partner.agent_id}/avatar`,
    model: null,
    tool_groups: null,
    capabilities: {
      local_partner: DRIVABLE_PARTNERS.has(partnerId),
      local_partner_id: partnerId,
      local_partner_command: command,
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
  isFetching: boolean;
  isError: boolean;
  refresh: () => Promise<unknown>;
} {
  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ["cli-team-status"],
    queryFn: async ({ signal }): Promise<CliTeamStatus> => {
      const res = await fetch(`${getBackendBaseURL()}/api/cli-team/status`, {
        cache: "no-store",
        headers: authHeaders(),
        signal,
      });
      if (!res.ok) {
        throw new Error(`Failed to detect local CLI partners: ${res.status}`);
      }
      return (await res.json()) as CliTeamStatus;
    },
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  const cliAgents = (data?.detected ?? []).map(partnerToAgent);
  return {
    cliAgents,
    isLoading,
    isFetching,
    isError,
    refresh: refetch,
  };
}

export function useLocalCliPartnerAgents(): {
  partners: LocalCliPartnerAgent[];
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  refresh: () => Promise<unknown>;
} {
  const statusQuery = useQuery({
    queryKey: ["cli-team-status"],
    queryFn: async ({ signal }): Promise<CliTeamStatus> => {
      const res = await fetch(`${getBackendBaseURL()}/api/cli-team/status`, {
        cache: "no-store",
        headers: authHeaders(),
        signal,
      });
      if (!res.ok) {
        throw new Error(`Failed to detect local CLI partners: ${res.status}`);
      }
      return (await res.json()) as CliTeamStatus;
    },
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  const partnersQuery = useQuery({
    queryKey: ["agents", "local-partners"],
    queryFn: ({ signal }) => listLocalAgentPartners({ signal }),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  const detectedByPartnerId = useMemo(
    () =>
      new Map(
        (statusQuery.data?.detected ?? []).map((partner) => [
          partner.partner_id,
          partner,
        ]),
      ),
    [statusQuery.data?.detected],
  );
  const partners = useMemo<LocalCliPartnerAgent[]>(() => {
    const full = partnersQuery.data ?? [];
    if (full.length > 0) {
      return full.map((partner) => {
        const detected = detectedByPartnerId.get(partner.id);
        return {
          agent: localPartnerToAgent(partner, detected),
          partnerId: partner.id,
          detected: Boolean(detected || partner.detected),
          ready: Boolean(partner.ready ?? detected),
          registered: Boolean(partner.registered),
          status: partner.effective_status || partner.status || "missing",
          fixHint: partner.fix_hint,
        };
      });
    }
    return (statusQuery.data?.detected ?? []).map((partner) => ({
      agent: partnerToAgent(partner),
      partnerId: partner.partner_id,
      detected: true,
      ready: true,
      registered: false,
      status: "detected",
      fixHint: null,
    }));
  }, [detectedByPartnerId, partnersQuery.data, statusQuery.data?.detected]);

  const refresh = async () => {
    await Promise.all([statusQuery.refetch(), partnersQuery.refetch()]);
  };
  return {
    partners,
    isLoading: statusQuery.isLoading || partnersQuery.isLoading,
    isFetching: statusQuery.isFetching || partnersQuery.isFetching,
    isError: statusQuery.isError && partnersQuery.isError,
    refresh,
  };
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

/**
 * Collapse duplicate persona profiles that differ only by a slash suffix such
 * as `Eve` and `Eve / Siren`. Local CLIs and connected devices deliberately
 * keep their stable ids because two external runtimes may share a friendly
 * label while still being different execution targets.
 */
export function dedupePersonaAgentsByDisplayName(agents: Agent[]): Agent[] {
  const result: Agent[] = [];
  const personaIndexByLabel = new Map<string, number>();
  for (const agent of agents) {
    const isExternalRuntime =
      /^(?:local_|registry_local_|mobile_)/.test(agent.name) ||
      Boolean(agent.capabilities?.local_partner);
    if (isExternalRuntime) {
      result.push(agent);
      continue;
    }

    const displayName = agent.display_name || agent.name;
    const label = displayName
      .split(/\s*\/\s*/)[0]
      ?.trim()
      .toLowerCase();
    if (!label) continue;

    const existingIndex = personaIndexByLabel.get(label);
    if (existingIndex === undefined) {
      personaIndexByLabel.set(label, result.length);
      result.push(agent);
      continue;
    }

    const existing = result[existingIndex];
    const existingHasAlias = (existing?.display_name || existing?.name || "")
      .trim()
      .includes("/");
    const nextHasAlias = displayName.includes("/");
    if (existingHasAlias && !nextHasAlias) {
      result[existingIndex] = agent;
    }
  }
  return result;
}
