import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";

export type RuleEffect = "allow" | "deny";

export interface ApprovalRule {
  effect: RuleEffect;
  tool: string;
  args_contains: string;
  reason: string;
}

export interface PolicyResponse {
  rules: ApprovalRule[];
}

export interface NewRuleInput {
  effect: RuleEffect;
  tool: string;
  args_contains?: string;
  reason?: string;
}

export async function listPermissionRules(): Promise<ApprovalRule[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/permissions`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to load permission rules: ${res.statusText}`);
  }
  const data = (await res.json()) as PolicyResponse;
  return data.rules ?? [];
}

export async function addPermissionRule(
  rule: NewRuleInput,
): Promise<ApprovalRule[]> {
  const body = {
    effect: rule.effect,
    tool: rule.tool,
    args_contains: rule.args_contains ?? "",
    reason: rule.reason ?? "",
  };
  const res = await fetch(`${getBackendBaseURL()}/api/permissions/rules`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `Failed to add rule: ${res.status}${detail ? ` ${detail}` : ""}`,
    );
  }
  const data = (await res.json()) as PolicyResponse;
  return data.rules ?? [];
}

export async function deletePermissionRule(
  index: number,
): Promise<ApprovalRule[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/permissions/rules/${index}`,
    {
      method: "DELETE",
      headers: authHeaders(),
    },
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `Failed to delete rule: ${res.status}${detail ? ` ${detail}` : ""}`,
    );
  }
  const data = (await res.json()) as PolicyResponse;
  return data.rules ?? [];
}

export async function movePermissionRule(
  fromIndex: number,
  toIndex: number,
): Promise<ApprovalRule[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/permissions/rules/${fromIndex}/move`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ to: toIndex }),
    },
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `Failed to move rule: ${res.status}${detail ? ` ${detail}` : ""}`,
    );
  }
  const data = (await res.json()) as PolicyResponse;
  return data.rules ?? [];
}
