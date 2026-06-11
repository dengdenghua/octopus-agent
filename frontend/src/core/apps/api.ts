import { getBackendBaseURL } from "@/core/config";

export interface OctopusAppAction {
  name: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  requires_confirmation?: boolean;
}

export interface OctopusApp {
  id: string;
  name: string;
  description?: string;
  author?: string | null;
  plugin?: string | null;
  source_plugin?: string | null;
  path?: string;
  route?: string | null;
  entry?: string | null;
  icon?: string | null;
  category?: string | null;
  schema_version?: string | null;
  connector_id?: string | null;
  permissions?: string[];
  actions?: OctopusAppAction[];
  action_count?: number;
}

export async function listApps(): Promise<OctopusApp[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/apps`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to load apps: ${res.statusText}`);
  return res.json() as Promise<OctopusApp[]>;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("octopus:token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}
