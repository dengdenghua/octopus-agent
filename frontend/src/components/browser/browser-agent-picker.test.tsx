import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { primaryPersonaRoster } from "@/core/agents/agent-list";
import { ACTIVE_AGENT_KEY, useActiveAgentId } from "@/core/agents/active";
import type { Agent } from "@/core/agents/types";
import { emitAgentChanged } from "@/core/events";
import { BrowserAgentPicker } from "./browser-agent-picker";

const agent = (name: string, display_name: string): Agent => ({
  name,
  display_name,
  avatar_url: `/api/agents/${name}/avatar`,
  description: "",
  model: null,
  tool_groups: null,
});
const roster = primaryPersonaRoster([
  agent("aoi", "Zero"),
  agent("desktop_operator", "Raven"),
  agent("coder", "Kane"),
  agent("general", "Eve"),
  agent("expert", "Expert"),
]);
function Picker() {
  const id = useActiveAgentId() ?? "general";
  return (
    <>
      <BrowserAgentPicker
        activeAgent={roster.find((item) => item.name === id) ?? null}
        activeAgentId={id}
        agents={roster}
      />
      <output data-testid="active-id">{id}</output>
    </>
  );
}
beforeEach(() => localStorage.setItem(ACTIVE_AGENT_KEY, "desktop_operator"));

it("uses the shared roster order and real avatar for browser roles", async () => {
  renderWithProviders(<Picker />, { locale: "zh-CN" });
  const trigger = screen.getByRole("button", { name: "切换智能体 · Raven" });
  expect(trigger.querySelector("img")?.getAttribute("src")).toContain(
    "/api/agents/desktop_operator/avatar",
  );
  await userEvent.click(trigger);
  const menu = screen.getByRole("menu");
  const items = within(menu).getAllByRole("menuitem");
  expect(items).toHaveLength(4);
  ["Eve", "Kane", "Raven", "Zero"].forEach((name, index) => {
    expect(items[index]).toHaveAccessibleName(new RegExp(name));
  });
  expect(within(menu).getByRole("menuitem", { name: /Raven/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

it("synchronizes browser selections and external role changes via the shared state", async () => {
  renderWithProviders(<Picker />, { locale: "zh-CN" });
  await userEvent.click(
    screen.getByRole("button", { name: "切换智能体 · Raven" }),
  );
  await userEvent.click(screen.getByRole("menuitem", { name: /Kane/ }));
  expect(localStorage.getItem(ACTIVE_AGENT_KEY)).toBe("coder");
  expect(screen.getByTestId("active-id")).toHaveTextContent("coder");
  expect(
    screen.getByRole("button", { name: "切换智能体 · Kane" }),
  ).toBeVisible();
  act(() => emitAgentChanged("general"));
  expect(
    screen.getByRole("button", { name: "切换智能体 · Eve" }),
  ).toBeVisible();
});

it("supports keyboard selection without a separate mouse-only menu", async () => {
  renderWithProviders(<Picker />, { locale: "zh-CN" });
  screen.getByRole("button", { name: "切换智能体 · Raven" }).focus();
  await userEvent.keyboard("{Enter}{ArrowDown}{Enter}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(localStorage.getItem(ACTIVE_AGENT_KEY)).not.toBe("desktop_operator");
});
