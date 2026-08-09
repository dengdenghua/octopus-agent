import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

import { getLocalSettings } from "@/core/settings";
import { renderWithProviders } from "@/test/harness";

import SandboxSettingsPage from "./sandbox-settings-page";

describe("SandboxSettingsPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders three independent axes with defaults highlighted", () => {
    renderWithProviders(<SandboxSettingsPage />);

    // Execution environment axis.
    expect(
      screen.getByRole("button", { name: /^Sandbox/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^Local/ })).toBeInTheDocument();

    // Permission level axis.
    expect(
      screen.getByRole("button", { name: /^Default/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /^Accept edits/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Full access/ }),
    ).toBeInTheDocument();

    // Network access axis — three tiers, deny highlighted by default.
    expect(
      screen.getByRole("button", { name: /^Blocked/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /^Common domains/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Allowed/ }),
    ).toBeInTheDocument();
  });

  it("switches the execution environment without touching the other axes", () => {
    renderWithProviders(<SandboxSettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Local/ }));

    const persisted = getLocalSettings();
    expect(persisted.context.execution_environment).toBe("local");
    expect(persisted.context.sandbox_mode).toBe("full");
    // The permission axis is untouched.
    expect(persisted.context.permission_mode).toBe("default");
    expect(persisted.context.approval_policy).toBeUndefined();
    // The network axis is untouched.
    expect(persisted.context.network_access).toBe("deny");

    expect(screen.getByRole("button", { name: /^Local/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switches the permission level without touching the other axes", () => {
    renderWithProviders(<SandboxSettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Full access/ }));

    const persisted = getLocalSettings();
    expect(persisted.context.permission_mode).toBe("bypassPermissions");
    expect(persisted.context.approval_policy).toBe("never");
    // The environment axis is untouched (still sandbox by default).
    expect(persisted.context.execution_environment).toBe("sandbox");
    // The network axis is untouched.
    expect(persisted.context.network_access).toBe("deny");

    expect(
      screen.getByRole("button", { name: /^Full access/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("switches network access to the common-domains tier without touching the other axes", () => {
    renderWithProviders(<SandboxSettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Common domains/ }));

    const persisted = getLocalSettings();
    expect(persisted.context.network_access).toBe("common");
    // The other axes are untouched.
    expect(persisted.context.permission_mode).toBe("default");
    expect(persisted.context.execution_environment).toBe("sandbox");

    expect(
      screen.getByRole("button", { name: /^Common domains/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("switches network access to the full tier", () => {
    renderWithProviders(<SandboxSettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Allowed/ }));

    const persisted = getLocalSettings();
    expect(persisted.context.network_access).toBe("full");
    expect(screen.getByRole("button", { name: /^Allowed/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switches reply style without touching the other axes", () => {
    renderWithProviders(<SandboxSettingsPage />);

    // Default style is highlighted by default.
    expect(
      screen.getByRole("button", { name: "reply-style-default" }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(
      screen.getByRole("button", { name: "reply-style-professional" }),
    );

    const persisted = getLocalSettings();
    expect(persisted.context.reply_style).toBe("professional");
    // Other axes untouched.
    expect(persisted.context.network_access).toBe("deny");
    expect(persisted.context.permission_mode).toBe("default");
    expect(persisted.context.execution_environment).toBe("sandbox");
    expect(
      screen.getByRole("button", { name: "reply-style-professional" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps all three axes independent when re-rendering an existing combination", () => {
    window.localStorage.setItem(
      "octopus.local-settings",
      JSON.stringify({
        context: {
          permission_mode: "acceptEdits",
          execution_environment: "local",
          sandbox_mode: "full",
          approval_policy: "on-request",
          // Legacy boolean storage normalizes to the "full" tier.
          network_access: true,
        },
      }),
    );

    renderWithProviders(<SandboxSettingsPage />);
    expect(screen.getByRole("button", { name: /^Local/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByRole("button", { name: /^Accept edits/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^Allowed/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Change only the permission axis; environment and network stay.
    fireEvent.click(screen.getByRole("button", { name: /^Default/ }));

    const persisted = getLocalSettings();
    expect(persisted.context.permission_mode).toBe("default");
    expect(persisted.context.execution_environment).toBe("local");
    // Unchanged axes keep their raw stored value (legacy true).
    expect(persisted.context.network_access).toBe(true);
  });
});
