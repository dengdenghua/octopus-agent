import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { TeamGatewaySettings } from "./team-gateway-settings";

afterEach(() => vi.unstubAllGlobals());

it("restores saved connections and retries sync without exchanging again", async () => {
  const changed = vi.fn();
  const connection = {
    id: "saved",
    base_url: "http://localhost:8333/v1",
    connected: true,
    error: "目录暂时不可用",
    models: [],
  };
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("/connections")
        ? { connections: [connection] }
        : {
            ...connection,
            error: "",
            models: [
              { id: "team", display_name: "团队助手", wire_api: "responses" },
            ],
          },
  }));
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<TeamGatewaySettings onConnected={changed} />);
  fireEvent.click(await screen.findByRole("button", { name: "立即同步" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("团队助手")).toBeVisible();
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/join"))).toBe(
    false,
  );
  expect(screen.queryByText("目录暂时不可用")).not.toBeInTheDocument();
});

it("joins with a code and receives no member token in the browser", async () => {
  const changed = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/connections"))
      return { ok: true, json: async () => ({ connections: [] }) };
    expect(url).toContain("/team-gateway/join");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      code: "one-time-code",
    });
    return {
      ok: true,
      json: async () => ({
        id: "saved",
        base_url: "http://localhost:8333/v1",
        connected: true,
        error: "",
        models: [
          { id: "team", display_name: "团队助手", wire_api: "responses" },
        ],
      }),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<TeamGatewaySettings onConnected={changed} />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("团队邀请兑换码"), {
    target: { value: "one-time-code" },
  });
  fireEvent.click(screen.getByRole("button", { name: "兑换并接入团队" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("status")).toHaveTextContent("关闭页面后仍可使用");
  expect(screen.getByLabelText("团队邀请兑换码")).toHaveValue("");
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
    false,
  );
});

it("loads administration only on request and exposes publish and revoke actions", async () => {
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("/connections")
        ? { connections: [] }
        : {
            enabled: false,
            models: [{ id: "draft", name: "待发布", published: false }],
            members: [
              {
                id: "one",
                label: "小李",
                redeemed: true,
                revoked: 0,
                used: 2,
                max_requests: 10,
              },
            ],
            usage: [],
          },
  }));
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<TeamGatewaySettings onConnected={vi.fn()} />);
  expect(fetchMock.mock.calls.some(([url]) => url.includes("/admin/"))).toBe(
    false,
  );
  fireEvent.click(screen.getByText("管理本机团队网关"));
  fireEvent.click(screen.getByRole("button", { name: "加载 / 启动网关" }));
  expect(
    await screen.findByRole("button", { name: "测试并发布 待发布" }),
  ).toBeEnabled();
  expect(screen.getByRole("button", { name: "撤销 小李" })).toBeEnabled();
  expect(screen.getByText(/2\/10 次/)).toBeVisible();
});
