import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/core/agents";
import { renderWithProviders } from "@/test/harness";

import { AgentCard } from "./agent-card";

const deleteAgentMock = vi.hoisted(() => vi.fn());

vi.mock("@/core/agents", () => ({
  useDeleteAgent: () => ({
    mutateAsync: deleteAgentMock,
    isPending: false,
  }),
}));

const agent: Agent = {
  name: "custom-role",
  display_name: "自定义角色",
  description: "负责专项协作。",
  icon: "🤖",
  model: null,
  tool_groups: null,
};

describe("AgentCard", () => {
  beforeEach(() => {
    deleteAgentMock.mockReset();
    deleteAgentMock.mockResolvedValue(undefined);
  });

  it("exposes contextual profile, chat, and delete actions", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(
      <AgentCard agent={agent} onSelect={onSelect} isDefault={false} />,
      { locale: "zh-CN" },
    );

    const profileAction = screen.getByRole("button", {
      name: "自定义角色 角色档案",
    });
    expect(
      screen.getByRole("button", { name: "与 自定义角色 开聊" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "删除角色 自定义角色" }),
    ).toBeInTheDocument();

    await user.click(profileAction);
    expect(onSelect).toHaveBeenCalledWith(agent);
  });

  it("names the destructive confirmation and deletes the selected role", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentCard agent={agent} isDefault={false} />, {
      locale: "zh-CN",
    });

    await user.click(
      screen.getByRole("button", { name: "删除角色 自定义角色" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "删除角色“自定义角色”",
    });
    expect(
      within(dialog).getByText(
        "角色“自定义角色”将被永久删除，此操作无法撤销。",
      ),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "删除" }));
    expect(deleteAgentMock).toHaveBeenCalledWith("custom-role");
  });
});
