import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { SearxngControl } from "./searxng-control";

const mocks = vi.hoisted(() => ({
  refetch: vi.fn(),
  setEnabled: vi.fn(),
  status: {
    up: false,
    heartbeat: false,
    docker_present: true,
    managed: false,
    autostart: false,
  },
  isLoading: false,
  isError: false,
  isPending: false,
}));

vi.mock("@/core/searxng/use-searxng-status", () => ({
  useSearxngStatus: () => ({
    status: mocks.status,
    isLoading: mocks.isLoading,
    isError: mocks.isError,
    refetch: mocks.refetch,
  }),
  useSearxngControl: () => ({
    setEnabled: mocks.setEnabled,
    isPending: mocks.isPending,
  }),
}));

describe("SearxngControl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.status.up = false;
    mocks.status.docker_present = true;
    mocks.status.managed = false;
    mocks.isLoading = false;
    mocks.isError = false;
    mocks.isPending = false;
    mocks.setEnabled.mockResolvedValue(undefined);
  });

  it("renders Korean copy instead of falling back to English", () => {
    renderWithProviders(<SearxngControl />, { locale: "ko-KR" });

    expect(screen.getByText("로컬 웹 검색(SearXNG)")).toBeInTheDocument();
    expect(screen.getByText("중지됨")).toBeInTheDocument();
    expect(screen.queryByText("Stopped")).not.toBeInTheDocument();
  });

  it("shows a recoverable error and disables the switch when status is unknown", async () => {
    const user = userEvent.setup();
    mocks.isError = true;
    renderWithProviders(<SearxngControl />, { locale: "zh-CN" });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "暂时无法读取本地搜索状态",
    );
    expect(
      screen.getByRole("switch", { name: "本地网页搜索 (SearXNG)" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "重新检测" }));
    expect(mocks.refetch).toHaveBeenCalledOnce();
  });

  it("passes the requested state to the control mutation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearxngControl />, { locale: "en-US" });

    await user.click(
      screen.getByRole("switch", { name: "Local web search (SearXNG)" }),
    );
    expect(mocks.setEnabled).toHaveBeenCalledWith(true);
  });
});
