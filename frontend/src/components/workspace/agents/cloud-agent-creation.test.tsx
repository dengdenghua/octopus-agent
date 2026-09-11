import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/harness";
import { CloudAgentCreation } from "./cloud-agent-creation";
const mocks = vi.hoisted(() => ({ list: vi.fn(), install: vi.fn(), navigate: vi.fn() }));
vi.mock("@/core/agents/agent-world-api", () => ({ listCloudStoreExperts: mocks.list, installCloudExpert: mocks.install }));
vi.mock("react-router-dom", async original => ({ ...await original<object>(), useNavigate: () => mocks.navigate }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe("unified cloud creation", () => {
  it("requires explicit creation and opens the actual imported agent", async () => {
    mocks.list.mockResolvedValue({ agents: [{ id: "wb_source", display_name: "工程师", description: "原始配置" }] });
    mocks.install.mockResolvedValue({ installed: true, agent_id: "actual_agent" });
    renderWithProviders(<CloudAgentCreation sourceId="wb_source" />);
    await screen.findByText("工程师");
    expect(mocks.install).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "创建智能体" }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith("/workspace/agents?surface=chat&hud=1&agent=actual_agent"));
    expect(mocks.install).toHaveBeenCalledWith("wb_source");
  });
  it("rejects an unknown source instead of creating an unrelated agent", async () => {
    mocks.list.mockResolvedValue({ agents: [] });
    renderWithProviders(<CloudAgentCreation sourceId="missing" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("未找到来源模板");
    expect(screen.queryByRole("button", { name: "创建智能体" })).toBeNull();
    expect(mocks.install).not.toHaveBeenCalled();
  });
});
