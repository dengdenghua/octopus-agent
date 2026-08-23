import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  RealtimeChatHeaderActions,
  RealtimeChatHeaderMemberSurface,
  RealtimeChatHeaderOverflowMenu,
} from "./realtime-chat-header-controls";

describe("realtime chat header controls", () => {
  it("presents AI roster and human invite as one segmented member surface", () => {
    renderWithProviders(
      <RealtimeChatHeaderMemberSurface
        aiMembers={<button type="button">AI members 1</button>}
        humanInvite={<button type="button">Invite person</button>}
      />,
      { locale: "en-US" },
    );

    const memberSurface = screen.getByRole("group", {
      name: "Collaboration",
    });
    expect(
      within(memberSurface).getByRole("button", { name: "AI members 1" }),
    ).toBeInTheDocument();
    expect(
      within(memberSurface).getByRole("button", { name: "Invite person" }),
    ).toBeInTheDocument();
    expect(memberSurface).toHaveAttribute(
      "data-slot",
      "realtime-header-members",
    );
  });

  it("keeps idle recording and share actions inside More", async () => {
    const user = userEvent.setup();
    const onOpenRecorder = vi.fn();
    const onExportReplay = vi.fn();

    renderWithProviders(
      <RealtimeChatHeaderOverflowMenu
        onOpenRecorder={onOpenRecorder}
        share={{ title: "Launch notes", onExportReplay }}
      />,
      { locale: "en-US" },
    );

    expect(
      screen.queryByRole("button", { name: /record/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("menuitem", { name: /record/i }));
    expect(onOpenRecorder).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "More" }));
    expect(
      screen.getByRole("menuitem", { name: "Save as image" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("menuitem", { name: "Export replayable HTML" }),
    );
    expect(onExportReplay).toHaveBeenCalledOnce();
  });

  it("keeps active recording, workbench, and overflow in a stable order", () => {
    renderWithProviders(
      <RealtimeChatHeaderActions
        recording={<button type="button">REC active</button>}
        workbench={<button type="button">Workbench</button>}
        overflow={<button type="button">More</button>}
      />,
    );

    const actions = screen
      .getByText("REC active")
      .closest('[data-slot="realtime-header-actions"]');
    expect(actions).not.toBeNull();
    expect(
      within(actions as HTMLElement)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["REC active", "Workbench", "More"]);
  });
});
