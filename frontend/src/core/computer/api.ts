import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

const BASE = () => `${getBackendBaseURL()}/api/computer`;

export type ComputerLeaseOwner = {
  owner_id: string;
  owner_label: string;
};

export type ComputerLease = {
  held: boolean;
  owner_id?: string;
  owner_label?: string;
  acquired_at?: number;
  updated_at?: number;
  expires_at?: number;
  ttl_seconds: number;
  lease_ttl_seconds: number;
};

export type ComputerStatus = {
  ok: boolean;
  pyautogui_available: boolean;
  lease?: ComputerLease;
  screen: {
    width?: number;
    height?: number;
    cursor_x?: number;
    cursor_y?: number;
    error?: string;
  };
  skills: string[];
  mode: string;
};

export type ComputerScreenshot = {
  ok: boolean;
  path?: string;
  size_bytes?: number;
  data_url?: string;
  created_at?: number;
  error?: string;
};

export type ComputerMatchedControl = {
  id?: string | number | null;
  name?: string | null;
  control_type?: string | null;
  class_name?: string | null;
  automation_id?: string | null;
  center?: { x?: number | null; y?: number | null } | null;
  rect?: {
    x?: number | null;
    y?: number | null;
    width?: number | null;
    height?: number | null;
    left?: number | null;
    top?: number | null;
    right?: number | null;
    bottom?: number | null;
  } | null;
  query?: string | null;
  score?: number | null;
};

export type ComputerActionMetadata = {
  source?: string;
  matched_control?: ComputerMatchedControl | null;
  [key: string]: unknown;
};

export type ComputerActionPayload = Record<string, unknown> & ComputerActionMetadata;

export type ComputerAction =
  | (ComputerActionMetadata & {
      action: "click" | "move";
      x: number;
      y: number;
      button?: "left" | "right" | "middle";
      clicks?: number;
      duration?: number;
    })
  | (ComputerActionMetadata & { action: "type"; text: string; interval?: number })
  | (ComputerActionMetadata & { action: "key"; keys: string[] | string })
  | (ComputerActionMetadata & { action: "wait"; ms: number });

export type ComputerPreview = {
  ok: boolean;
  token: string;
  action: ComputerActionPayload;
  risk: { level: "low" | "medium" | "high" | string; reason: string };
  expires_in_seconds: number;
  lease?: ComputerLease;
  lease_owner?: ComputerLeaseOwner;
};

export type ComputerExecuteResult = {
  ok: boolean;
  action: ComputerActionPayload;
  risk: { level: string; reason: string };
  result: Record<string, unknown>;
  lease?: ComputerLease;
  executed_at: number;
};

export type ComputerPlanSuggestion = {
  id: string;
  title: string;
  rationale: string;
  token: string;
  action: ComputerActionPayload;
  risk: { level: "low" | "medium" | "high" | string; reason: string };
  expires_in_seconds: number;
  lease_owner?: ComputerLeaseOwner;
};

export type ComputerActionPlan = {
  ok: boolean;
  goal: string;
  screenshot?: ComputerScreenshot | null;
  suggestions: ComputerPlanSuggestion[];
  mode: string;
  limitations: string[];
  lease?: ComputerLease;
};

export type ComputerLeaseReleaseResult = {
  ok: boolean;
  lease: ComputerLease;
};

function leaseOwnerBody(leaseOwner?: ComputerLeaseOwner | null) {
  return leaseOwner
    ? {
        lease_owner_id: leaseOwner.owner_id,
        lease_owner_label: leaseOwner.owner_label,
      }
    : {};
}

export async function getComputerStatus(): Promise<ComputerStatus> {
  const res = await fetch(`${BASE()}/status`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to load computer status: ${res.statusText}`);
  return (await res.json()) as ComputerStatus;
}

export async function captureComputerScreen(): Promise<ComputerScreenshot> {
  const res = await fetch(`${BASE()}/screenshot`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(`Failed to capture screen: ${res.statusText}`);
  return (await res.json()) as ComputerScreenshot;
}

export async function previewComputerAction(
  action: ComputerAction,
  options: { leaseOwner?: ComputerLeaseOwner | null } = {},
): Promise<ComputerPreview> {
  const res = await fetch(`${BASE()}/actions/preview`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ ...action, ...leaseOwnerBody(options.leaseOwner) }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to preview action: ${res.status}${text ? ` ${text}` : ""}`);
  }
  return (await res.json()) as ComputerPreview;
}

export async function planComputerActions(
  goal: string,
  options: { capture?: boolean; leaseOwner?: ComputerLeaseOwner | null } = {},
): Promise<ComputerActionPlan> {
  const res = await fetch(`${BASE()}/actions/plan`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({
      goal,
      capture: options.capture ?? true,
      ...leaseOwnerBody(options.leaseOwner),
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to plan actions: ${res.status}${text ? ` ${text}` : ""}`);
  }
  return (await res.json()) as ComputerActionPlan;
}

export async function groundComputerActions(
  goal: string,
  output: string,
  options: { capture?: boolean; leaseOwner?: ComputerLeaseOwner | null } = {},
): Promise<ComputerActionPlan> {
  const res = await fetch(`${BASE()}/actions/ground`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({
      goal,
      output,
      capture: options.capture ?? true,
      ...leaseOwnerBody(options.leaseOwner),
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to ground vision output: ${res.status}${text ? ` ${text}` : ""}`);
  }
  return (await res.json()) as ComputerActionPlan;
}

export async function askVisionModelForComputerActions(
  goal: string,
  modelId: string,
  options: { leaseOwner?: ComputerLeaseOwner | null } = {},
): Promise<ComputerActionPlan> {
  const res = await fetch(`${BASE()}/actions/vision`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ goal, model_id: modelId, ...leaseOwnerBody(options.leaseOwner) }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to ask vision model: ${res.status}${text ? ` ${text}` : ""}`);
  }
  return (await res.json()) as ComputerActionPlan;
}

export async function executeComputerAction(
  token: string,
  options: { leaseOwner?: ComputerLeaseOwner | null } = {},
): Promise<ComputerExecuteResult> {
  const res = await fetch(`${BASE()}/actions/execute`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ token, ...leaseOwnerBody(options.leaseOwner) }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to execute action: ${res.status}${text ? ` ${text}` : ""}`);
  }
  return (await res.json()) as ComputerExecuteResult;
}

export async function releaseComputerLease(
  leaseOwner: ComputerLeaseOwner,
): Promise<ComputerLeaseReleaseResult> {
  const res = await fetch(`${BASE()}/lease/release`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(leaseOwnerBody(leaseOwner)),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to release computer lease: ${res.status}${text ? ` ${text}` : ""}`);
  }
  return (await res.json()) as ComputerLeaseReleaseResult;
}
