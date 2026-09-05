import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";
import type { Team } from "@/core/teams";

import { TeamWorkbenchPanel } from "./team-workbench-panel";

function teamFixture(): Team {
  return {
    id: "team-1",
    name: "Octopus Lab",
    leaderId: "general",
    members: [
      {
        name: "general",
        display_name: "Eve",
        description: "Team lead",
        icon: null,
        avatar_url: "/api/agents/general/avatar",
        model: null,
        tool_groups: null,
      },
      {
        name: "codex-cli",
        display_name: "Codex CLI",
        description: "Local coding agent",
        icon: null,
        avatar_url: null,
        model: null,
        tool_groups: null,
      },
    ],
    participants: [
      {
        id: "me",
        display_name: "You",
        role: "owner",
        status: "active",
        joined_at: "2026-06-29T00:00:00Z",
      },
    ],
  };
}

describe("<TeamWorkbenchPanel />", () => {
  test("opens a member card in the header machine rail before mentioning an AI member", () => {
    const onMention = vi.fn();
    const onSelectTab = vi.fn();

    renderWithProviders(
      <TeamWorkbenchPanel
        activeTab="tasks"
        onSelectTab={onSelectTab}
        roomId="room-1"
        team={teamFixture()}
        workDir="/tmp/project"
        onWorkDirChange={vi.fn()}
        currentParticipantId="me"
        onMention={onMention}
      />,
      { locale: "zh-CN" },
    );

    const header = screen.getByRole("banner");
    const codexSeat = within(header).getByRole("button", {
      name: "@Codex CLI · 查看成员信息",
    });
    expect(codexSeat).toHaveAttribute("title", "Local coding agent");
    expect(
      within(header).getByRole("button", { name: "You · 在线 · 查看成员信息" }),
    ).toBeInTheDocument();

    fireEvent.pointerDown(codexSeat, { button: 0, ctrlKey: false });
    expect(screen.getByLabelText("Codex CLI 的成员信息")).toBeInTheDocument();
    expect(screen.getByText("Local coding agent")).toBeInTheDocument();
    expect(onMention).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "提及成员" }));
    expect(onSelectTab).toHaveBeenCalledWith("members");
    expect(onMention).toHaveBeenCalledWith("codex-cli");
  });
});
