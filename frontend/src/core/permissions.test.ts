import { describe, expect, it } from "vitest";

import {
  normalizePermissionMode,
  permissionRuntimeConfig,
} from "./permissions";

describe("permissionRuntimeConfig", () => {
  it("defaults to the product default mode", () => {
    expect(permissionRuntimeConfig(undefined)).toEqual({
      mode: "default",
      approvalPolicy: "on-request",
      sandboxPolicy: {
        type: "workspaceWrite",
        networkAccess: true,
      },
      execution_environment: "sandbox",
      sandbox_mode: "sandbox",
      planningMode: false,
    });
  });

  it("maps bypassPermissions to local execution with auto approval", () => {
    expect(permissionRuntimeConfig("bypassPermissions")).toEqual({
      mode: "bypassPermissions",
      approvalPolicy: "never",
      sandboxPolicy: {
        type: "dangerFullAccess",
        networkAccess: true,
      },
      execution_environment: "local",
      sandbox_mode: "full",
      planningMode: false,
    });
  });

  it("maps plan to planning mode without bypassing approvals", () => {
    expect(permissionRuntimeConfig("plan")).toEqual({
      mode: "plan",
      approvalPolicy: "on-request",
      sandboxPolicy: {
        type: "workspaceWrite",
        networkAccess: true,
      },
      execution_environment: "sandbox",
      sandbox_mode: "sandbox",
      planningMode: true,
    });
  });

  it("keeps legacy sandbox/full settings compatible", () => {
    expect(normalizePermissionMode("sandbox")).toBe("default");
    expect(normalizePermissionMode("full")).toBe("bypassPermissions");
  });
});
