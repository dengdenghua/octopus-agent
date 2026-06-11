import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";

import type { MCPConfig } from "./types";

async function assertOk(response: Response, label: string): Promise<void> {
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(
      (err as { detail?: string }).detail ?? `${label}: ${response.statusText}`,
    );
  }
}

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    headers: authHeaders(),
  });
  await assertOk(response, "Failed to load MCP config");
  return response.json() as Promise<MCPConfig>;
}

export async function updateMCPConfig(config: MCPConfig) {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    method: "PUT",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(config),
  });
  await assertOk(response, "Failed to update MCP config");
  return response.json();
}

// ───────────────────────────── Trust store ─────────────────────────────
//
// MCP servers run arbitrary code on the user's machine. Per ADR-007, the
// runtime refuses to register a server's tools as skills until the user
// explicitly approves it. These wrappers talk to /api/mcp/trust so the
// settings page can show approval state and surface an Approve button.

export interface MCPTrustEntry {
  server_name: string;
  approved: boolean;
  added_ts: number;
  tool_digest: string;
  note: string;
}

export async function listMCPTrust(): Promise<{ entries: MCPTrustEntry[] }> {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/trust`, {
    headers: authHeaders(),
  });
  await assertOk(response, "Failed to list MCP trust entries");
  return response.json();
}

export async function approveMCPTrust(
  server_name: string,
  tool_names: string[] = [],
  note = "",
): Promise<{ ok: boolean; entry: MCPTrustEntry }> {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/trust`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ server_name, tool_names, note }),
  });
  await assertOk(response, "Failed to approve MCP trust");
  return response.json();
}

export async function revokeMCPTrust(
  server_name: string,
): Promise<{ ok: boolean; server_name: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/mcp/trust/${encodeURIComponent(server_name)}`,
    { method: "DELETE", headers: authHeaders() },
  );
  await assertOk(response, "Failed to revoke MCP trust");
  return response.json();
}
