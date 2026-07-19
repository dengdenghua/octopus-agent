import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { AgentsTab } from "./agent-world-unified";

const emptyCounts = new Map([
  ["all" as const, 0],
  ["assistant" as const, 0],
  ["coder" as const, 0],
  ["researcher" as const, 0],
  ["creative" as const, 0],
  ["automation" as const, 0],
  ["specialist" as const, 0],
  ["financial" as const, 0],
]);

function renderAgentsTab({
  loading = false,
  loadError = false,
  onRetry = vi.fn(),
}: {
  loading?: boolean;
  loadError?: boolean;
  onRetry?: () => void;
} = {}) {
  renderWithProviders(
    <AgentsTab
      agents={[]}
      filteredAgents={[]}
      loading={loading}
      loadError={loadError}
      activeCategory="all"
      categoryCounts={emptyCounts}
      onCategoryChange={vi.fn()}
      onSelectAgent={vi.fn()}
      onInstallChange={vi.fn()}
      onRetry={onRetry}
    />,
    { locale: "zh-CN" },
  );
}

describe("Agent Hub role list states", () => {
  it("announces loading without exposing empty controls", () => {
    renderAgentsTab({ loading: true });
    expect(screen.getByRole("status")).toHaveTextContent("正在加载角色");
    expect(screen.queryByRole("button", { name: "全部" })).toBeNull();
  });

  it("keeps a failed load recoverable", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    renderAgentsTab({ loadError: true, onRetry });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "角色列表加载失败，请稍后重试。",
    );
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("exposes category selection state without counts polluting names", () => {
    renderAgentsTab();
    expect(screen.getByRole("group", { name: "按角色类型筛选" })).toBeVisible();
    expect(screen.getByRole("button", { name: "全部" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "编程" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
