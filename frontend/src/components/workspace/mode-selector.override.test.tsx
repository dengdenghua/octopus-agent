import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      modes: {
        develop: "编程",
        developDesc: "",
        developEffect: "",
        developTooltip: "",
        audit: "审查",
        auditDesc: "",
        auditEffect: "",
        auditTooltip: "",
        uxui: "界面",
        uxuiDesc: "",
        uxuiEffect: "",
        uxuiTooltip: "",
        manualOverrideShort: "手动",
        standard: "标准",
        ultra: "深度",
      },
    },
    locale: "zh",
    setLocale: () => Promise.resolve(),
  }),
}));

import { ModeSelector, persistModeSelection } from "./mode-selector";

function mockFetch() {
  return vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/agent-modes/detect")) {
        return new Response(
          JSON.stringify({
            recommended_mode: "coder",
            confidence: 0.9,
            reason: "test",
            signals: {},
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/agent-modes")) {
        return new Response(
          JSON.stringify({
            modes: [{ name: "develop", display_name: "编程" }],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response("not found", { status: 404 });
    }),
  );
}

describe("ModeSelector.onManualOverrideChange", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockFetch();
  });

  it("reports true when the user manually switches modes", async () => {
    const onManualOverrideChange = vi.fn();
    const onUserModeChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ModeSelector
        workDir="/workspace/a"
        sessionId="s1"
        mode="develop"
        onModeChange={() => {}}
        onUserModeChange={onUserModeChange}
        onManualOverrideChange={onManualOverrideChange}
      />,
    );

    // Open the popup and pick the only specialized option: Design.
    await user.click(screen.getByRole("button", { haspopup: "listbox" }));
    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(2);
    expect(
      options.every((option) => !option.textContent?.includes("审查")),
    ).toBe(true);
    const design = options.find((o) => o.textContent?.includes("界面"));
    expect(design).toBeTruthy();
    await user.click(design!);

    expect(onManualOverrideChange).toHaveBeenCalledWith(true);
    expect(onUserModeChange).toHaveBeenCalledOnce();
    expect(onUserModeChange).toHaveBeenCalledWith("uxui");
  });

  it("migrates a persisted audit mode to general on mount", () => {
    window.localStorage.setItem(
      "octopus:modeOverride",
      JSON.stringify({
        "/workspace/a": { mode: "audit", auditIntensity: "max" },
      }),
    );
    const onModeChange = vi.fn();
    const onUserModeChange = vi.fn();
    render(
      <ModeSelector
        workDir="/workspace/a"
        sessionId="s1"
        mode="develop"
        onModeChange={onModeChange}
        onUserModeChange={onUserModeChange}
      />,
    );

    expect(onModeChange).toHaveBeenCalledWith("develop");
    expect(onUserModeChange).not.toHaveBeenCalled();
  });

  it("renders a legacy audit prop as General without exposing a third option", async () => {
    const user = userEvent.setup();
    render(
      <ModeSelector
        workDir="/workspace/a"
        sessionId="s1"
        mode="audit"
        onModeChange={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /编程/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { haspopup: "listbox" }));
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    expect(screen.queryByText("审查")).not.toBeInTheDocument();
  });

  it("persists a mode only after the server accepts it", async () => {
    await persistModeSelection("audit", "s1", "/workspace/a");

    expect(
      JSON.parse(window.localStorage.getItem("octopus:modeOverride")!),
    ).toEqual({
      "/workspace/a": { mode: "develop" },
    });
  });

  it("rejects a failed server update without overwriting the saved mode", async () => {
    window.localStorage.setItem(
      "octopus:modeOverride",
      JSON.stringify({ "/workspace/a": { mode: "develop" } }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("failed", { status: 500 })),
    );

    await expect(
      persistModeSelection("audit", "s1", "/workspace/a"),
    ).rejects.toThrow("Mode update failed: 500");
    expect(
      JSON.parse(window.localStorage.getItem("octopus:modeOverride")!),
    ).toEqual({
      "/workspace/a": { mode: "develop" },
    });
  });
});
