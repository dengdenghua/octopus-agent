export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  capabilities: Array<Record<string, unknown>>;
  dependencies: string[];
  enabled: boolean;
  state: string;
  error?: string;
  logo_url?: string | null;
  icon_url?: string | null;
  brand_color?: string | null;
  start_time?: string;
}

export interface CapabilityInfo {
  name: string;
  type: string;
  description: string;
  version: string;
  requires: string[];
  provider?: string;
}

// ── PluginHub (new pluggable module architecture) ──────────

/** Capability as returned by the PluginHub API. */
export interface HubCapability {
  type: "skill" | "channel" | "api" | "config_ui";
  name: string;
  description: string;
}

/** Full plugin info as returned by the PluginHub API. */
export interface HubPluginInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  capabilities: HubCapability[];
  config_schema?: Record<string, unknown>;
  config_ui?: string | null;
  loaded: boolean;
  enabled: boolean;
  error?: string | null;
  dir: string;
  dependencies: string[];
  state: string;
}

/** A discovered (not yet loaded) plugin candidate. */
export interface DiscoveredPlugin {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  tags: string[];
  dir: string;
  loaded: boolean;
}
