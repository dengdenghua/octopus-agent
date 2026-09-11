import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { CodexHotspotPanel } from "./codex-hotspot-panel";

vi.mock("@/core/auth/api", () => ({ jsonAuthHeaders: () => ({}) }));
afterEach(() => vi.unstubAllGlobals());

it("only opens on request, enables the hotspot, creates and revokes a bounded invitation", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  let enabled = false;
  let members: unknown[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/enabled"))
      enabled = JSON.parse(String(init?.body)).enabled;
    if (url.endsWith("/members") && init?.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({
        label: "同事甲",
        hours: 8,
        max_requests: 100,
        task_engine: "codex",
      });
      members = [
        {
          id: "member1",
          label: "同事甲",
          used: 0,
          max_requests: 100,
          expires: Date.now() / 1000 + 3600,
          revoked: 0,
        },
      ];
      return {
        ok: true,
        json: async () => ({
          id: "member1",
          token: "invitation-only-token",
          task_url: "http://127.0.0.1:8322/members/member1",
          base_url: "http://127.0.0.1:8322/v1",
        }),
      };
    }
    if (url.endsWith("/members/member1")) members = [];
    return { ok: true, json: async () => ({ enabled, members }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<CodexHotspotPanel />);
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "共享我的模型 管理" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "开启热点" })).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "开启热点" }));
  fireEvent.change(await screen.findByLabelText("同事名称"), {
    target: { value: "同事甲" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建邀请" }));
  const token = await screen.findByLabelText("访问凭证");
  expect(token).toHaveAttribute("type", "password");
  expect(token).toHaveValue("invitation-only-token");
  fireEvent.change(screen.getByLabelText("同事端模型隧道端口"), {
    target: { value: "19444" },
  });
  fireEvent.click(screen.getByRole("button", { name: "复制 Codex 模型配置" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
  const config = String(writeText.mock.calls[0]?.[0]);
  expect(config).toContain("http://127.0.0.1:19444/v1");
  expect(config).toContain("stream_max_retries = 0");
  expect(config).not.toContain("invitation-only-token");
  fireEvent.click(screen.getByRole("button", { name: "复制 OpenCode 模型配置" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
  const openCode = JSON.parse(String(writeText.mock.calls[1]?.[0]));
  expect(openCode.provider.echo_hotspot.npm).toBe("@ai-sdk/openai");
  expect(openCode.provider.echo_hotspot.options.apiKey).toBe("{env:ECHO_HOTSPOT_TOKEN}");
  expect(openCode.provider.echo_hotspot.options.baseURL).toBe("http://127.0.0.1:19444/v1");
  fireEvent.change(screen.getByLabelText("同事端模型隧道端口"), {
    target: { value: "0" },
  });
  fireEvent.click(screen.getByRole("button", { name: "复制 Codex 模型配置" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("1 到 65535");
  expect(writeText).toHaveBeenCalledTimes(2);
  fireEvent.click(await screen.findByRole("button", { name: "撤销" }));
  await waitFor(() =>
    expect(screen.queryByLabelText("访问凭证")).not.toBeInTheDocument(),
  );
});
