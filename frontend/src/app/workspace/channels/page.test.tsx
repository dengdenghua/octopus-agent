import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import type * as AuthApi from "@/core/auth/api";
import ChannelsPage from "./page";
import { SidebarProvider } from "@/components/ui/sidebar";

vi.mock("@/core/auth/api", async (importOriginal) => ({
  ...(await importOriginal<typeof AuthApi>()),
  authHeaders: () => ({ Authorization: "Bearer channel-test" }),
  jsonAuthHeaders: () => ({
    Authorization: "Bearer channel-test",
    "Content-Type": "application/json",
  }),
}));
afterEach(() => vi.unstubAllGlobals());

describe("channel page loading", () => {
  it("authenticates channel, role and team requests", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(
      <SidebarProvider>
        <ChannelsPage />
      </SidebarProvider>,
      { locale: "zh-CN" },
    );
    await waitFor(() => {
      for (const path of ["/api/channels", "/api/agents", "/api/groups"]) {
        expect(fetchMock).toHaveBeenCalledWith(path, {
          headers: { Authorization: "Bearer channel-test" },
        });
      }
    });
  });

  it("keeps a malformed channel response recoverable", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("/api/channels") ? { detail: "invalid registry" } : [],
    }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(
      <SidebarProvider>
        <ChannelsPage />
      </SidebarProvider>,
      { locale: "zh-CN" },
    );
    expect(
      await screen.findByText(/渠道列表：服务返回的数据格式不完整/),
    ).toBeVisible();
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /重试|重新加载/ }));
    await waitFor(() =>
      expect(
        screen.queryByText(/渠道列表：服务返回的数据格式不完整/),
      ).toBeNull(),
    );
  });
});
