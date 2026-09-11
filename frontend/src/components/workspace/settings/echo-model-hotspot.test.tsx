import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { EchoModelHotspotSettings } from "./echo-model-hotspot";

vi.mock("@/components/workspace/codex-hotspot-panel", () => ({
  CodexHotspotPanel: () => <div>共享我的模型</div>,
}));
afterEach(() => vi.unstubAllGlobals());

it("connects and registers a Responses source in Echo without requiring a Codex client", async () => {
  const onConnected = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/discover"))
      return {
        ok: true,
        json: async () => ({
          base_url: "http://localhost:18322/v1",
          models: ["upstream-model"],
        }),
      };
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      wire_api: "responses",
      models: ["upstream-model"],
      api_key: "invitation",
      compat_profile: "echo_hotspot",
    });
    return { ok: true, json: async () => ({ _status: { ok: true } }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<EchoModelHotspotSettings onConnected={onConnected} />);
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("热点邀请凭证"), {
    target: { value: "invitation" },
  });
  fireEvent.click(screen.getByRole("button", { name: "连接并读取模型" }));
  expect(await screen.findByLabelText("热点模型")).toHaveValue(
    "upstream-model",
  );
  fireEvent.click(screen.getByRole("button", { name: "添加到 Echo 模型列表" }));
  await waitFor(() => expect(onConnected).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("热点邀请凭证")).toHaveValue("");
  expect(screen.getByRole("status")).toHaveTextContent("聊天的模型选择器");
  fireEvent.change(screen.getByLabelText("热点邀请凭证"), {
    target: { value: "invitation" },
  });
  fireEvent.click(screen.getByRole("button", { name: "连接并读取模型" }));
  await screen.findByLabelText("热点模型");
  fireEvent.click(screen.getByRole("button", { name: "添加到 Echo 模型列表" }));
  await waitFor(() => expect(onConnected).toHaveBeenCalledTimes(2));
  const saved = fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
  expect(saved[0]?.[0]).not.toBe(saved[1]?.[0]);
});
