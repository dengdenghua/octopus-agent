export type PermissionMode =
  | "default"
  | "acceptEdits"
  | "bypassPermissions"
  | "plan";
export type LegacyPermissionMode = "sandbox" | "full";
export type ApprovalPolicy = "never" | "on-request" | "untrusted";

export type SandboxPolicy =
  | {
      type: "workspaceWrite";
      networkAccess: boolean;
    }
  | {
      type: "dangerFullAccess";
      networkAccess: boolean;
    };

export interface PermissionRuntimeConfig {
  mode: PermissionMode;
  approvalPolicy: ApprovalPolicy;
  sandboxPolicy: SandboxPolicy;
  execution_environment: "sandbox" | "local";
  sandbox_mode: LegacyPermissionMode;
  planningMode: boolean;
}

export function normalizePermissionMode(value: unknown): PermissionMode {
  const raw = typeof value === "string" ? value.trim() : "";
  const normalized = raw.toLowerCase();
  if (normalized === "acceptedits" || normalized === "accept-edits") {
    return "acceptEdits";
  }
  if (
    normalized === "bypasspermissions" ||
    normalized === "bypass-permissions" ||
    normalized === "bypass" ||
    normalized === "yolo" ||
    normalized === "full"
  ) {
    return "bypassPermissions";
  }
  if (normalized === "plan") return "plan";
  return "default";
}

export function permissionRuntimeConfig(
  value: unknown,
): PermissionRuntimeConfig {
  const mode = normalizePermissionMode(value);
  if (mode === "bypassPermissions") {
    return {
      mode,
      approvalPolicy: "never",
      sandboxPolicy: {
        type: "dangerFullAccess",
        networkAccess: true,
      },
      execution_environment: "local",
      sandbox_mode: "full",
      planningMode: false,
    };
  }
  const planningMode = mode === "plan";
  return {
    mode,
    approvalPolicy: "on-request",
    sandboxPolicy: {
      type: "workspaceWrite",
      networkAccess: true,
    },
    execution_environment: "sandbox",
    sandbox_mode: "sandbox",
    planningMode,
  };
}
