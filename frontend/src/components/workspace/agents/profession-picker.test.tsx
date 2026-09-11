import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { ProfessionPicker } from "./profession-picker";
vi.mock("@/core/agents/api", () => ({ listAgents: vi.fn().mockResolvedValue([
  { name: "twin_structural_engineer", display_name: "结构工程师分身", description: "结构方案与图纸审核" },
  { name: "twin_embedded", display_name: "嵌入式工程师分身", description: "固件与RTOS" },
  { name: "general", display_name: "Eve", description: "助理" },
]) }));
it("filters local professions and passes the original duties without changing templates", async () => {
 const onSelect = vi.fn(); const user = userEvent.setup();
 renderWithProviders(<ProfessionPicker onSelect={onSelect} />, { locale: "zh-CN" });
 await user.click(screen.getByRole("button", { name: "选择职业模板" }));
 await screen.findByRole("button", { name: /结构工程师/ });
 await user.type(screen.getByRole("textbox", { name: "搜索职业" }), "嵌入式");
 expect(screen.queryByRole("button", { name: /结构工程师/ })).not.toBeInTheDocument();
 await user.click(screen.getByRole("button", { name: "嵌入式工程师" }));
 await waitFor(() => expect(onSelect).toHaveBeenCalledWith({ name: "嵌入式工程师", id: "embedded", description: "固件与RTOS" }));
});
