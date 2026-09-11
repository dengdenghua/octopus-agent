import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { GeneLockControlCard } from "./gene-lock-badge";

const fetchMock = vi.fn();
vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({ Authorization: "Bearer governance-test" }),
}));

describe("GeneLockControlCard", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: 1,
        maturity_level: 2,
        maturity_level_name: "growing",
        panic: { active: false, since: null, reason: "" },
        mode: "dev",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("exposes the selected governance mode and maturity level", async () => {
    renderWithProviders(<GeneLockControlCard compact />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "宽松" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.getByRole("button", { name: "严格" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Lv2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "紧急锁定" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(fetchMock.mock.calls[0]![1].headers.get("Authorization")).toBe(
      "Bearer governance-test",
    );
  });

  it("does not announce a rejected governance change as a success", async () => {
    renderWithProviders(<GeneLockControlCard compact />, { locale: "zh-CN" });
    const strictButton = await screen.findByRole("button", { name: "严格" });
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: "forbidden" }),
    });
    await userEvent.setup().click(strictButton);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "当前账号没有此功能的管理权限",
    );
    expect(screen.queryByText("已更新")).toBeNull();
    expect(strictButton).toHaveAttribute("aria-pressed", "false");
    const request = fetchMock.mock.calls.find(([url]) => url.endsWith("/mode"));
    expect(request![1].headers.get("Authorization")).toBe(
      "Bearer governance-test",
    );
  });
});
