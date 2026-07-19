import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentWorldAgent } from "@/core/agents/types";
import { renderWithProviders } from "@/test/harness";

import { AgentWorldCard } from "./agent-world-card";

const installAgentMock = vi.hoisted(() => vi.fn());

vi.mock("@/core/agents/agent-world-api", () => ({
  installAgent: installAgentMock,
  uninstallAgent: vi.fn(),
}));

const agent: AgentWorldAgent = {
  id: "research-role",
  name: "research-role",
  display_name: "研究角色",
  description: "整理资料并核对来源。",
  author: "Octopus",
  category: "researcher",
  tags: ["research"],
  icon: "🔬",
  version: "1.0.0",
  downloads: 1250,
  rating: 4.6,
  rating_count: 18,
  is_featured: false,
  is_official: true,
  is_installed: false,
  created_at: "2026-07-20",
};

describe("AgentWorldCard", () => {
  beforeEach(() => {
    installAgentMock.mockReset();
    installAgentMock.mockResolvedValue({ registered_skills: 0 });
  });

  it("keeps profile and install actions independently accessible", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(<AgentWorldCard agent={agent} onSelect={onSelect} />, {
      locale: "zh-CN",
    });

    expect(
      screen.getByRole("img", { name: "评分 4.6，18 条评价" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("下载量 1.3K")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "研究角色 角色档案" }));
    expect(onSelect).toHaveBeenCalledWith(agent);

    await user.click(screen.getByRole("button", { name: "添加角色 研究角色" }));
    expect(installAgentMock).toHaveBeenCalledWith("research-role");
  });
});
