import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { PublishedRolesPanel } from "./published-roles-panel";

vi.mock("@/core/auth/api", () => ({ jsonAuthHeaders: () => ({}) }));
afterEach(() => vi.unstubAllGlobals());

it("publishes the selected role without selecting or transmitting an engine", async () => {
  const role = { role_id: "echo_zero", name: "Zero", url: "http://localhost:8310/api/a2a/roles/echo_zero" };
  let published = false;
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({ role_id: "echo_zero" });
      published = true;
      return { ok: true, json: async () => role };
    }
    return { ok: true, json: async () => ({ roles: [role], published: published ? [role] : [] }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<PublishedRolesPanel />);
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "邀请我的角色参与协作" }));
  await screen.findByRole("option", { name: "Zero" });
  fireEvent.change(screen.getByLabelText("对外协作角色"), { target: { value: "echo_zero" } });
  fireEvent.click(screen.getByRole("button", { name: "生成角色连接地址" }));
  await waitFor(() => expect(screen.getByText(role.url)).toBeInTheDocument());
  expect(screen.queryByLabelText("远程角色引擎")).not.toBeInTheDocument();
});
