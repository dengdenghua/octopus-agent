import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { AutomationPictureInPicture } from "./automation-picture-in-picture";

const captureAutomationPreview = vi.fn();

vi.mock("@/core/browser/api", () => ({
  captureBrowserRelayPreview: vi.fn(),
}));

vi.mock("@/core/computer/api", () => ({
  captureComputerScreen: vi.fn(),
}));

describe("<AutomationPictureInPicture />", () => {
  const originalOctopus = window.octopus;

  beforeEach(() => {
    captureAutomationPreview.mockReset().mockResolvedValue({
      ok: true,
      dataUrl: "data:image/png;base64,cGlw",
      width: 960,
      height: 540,
      sourceId: "window:42:0",
      sourceName: "Release dashboard - Google Chrome",
      matched: true,
    });
    window.localStorage.clear();
    window.octopus = {
      isElectron: true,
      desktop: { captureAutomationPreview },
    } as unknown as NonNullable<typeof window.octopus>;
  });

  afterEach(() => {
    window.octopus = originalOctopus;
    vi.clearAllMocks();
  });

  it("renders a native read-only frame and closes without changing the target", async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <AutomationPictureInPicture
        threadId="thread-1"
        target={{
          kind: "browser_tab",
          source: "browser_relay",
          id: "42",
          title: "Release dashboard",
          url: "https://example.com/releases",
        }}
        open
        active
        paused={false}
        relayConnected
        stateLabel="Agent controlling"
        onOpenChange={onOpenChange}
      />,
    );

    expect(
      await screen.findByTestId("automation-picture-in-picture"),
    ).toBeInTheDocument();
    expect(await screen.findByAltText("Release dashboard")).toHaveAttribute(
      "src",
      "data:image/png;base64,cGlw",
    );
    await waitFor(() =>
      expect(captureAutomationPreview).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "browser_tab",
          id: "42",
          title: "Release dashboard",
        }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
