import { afterEach, describe, expect, it, vi } from "vitest";
import { getChannelsStatus } from "./api";

vi.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({ Authorization: "Bearer test-session" }),
  jsonAuthHeaders: () => ({
    Authorization: "Bearer test-session",
    "Content-Type": "application/json",
  }),
}));

afterEach(() => vi.unstubAllGlobals());

function respond(data: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status === 200,
    status,
    json: async () => data,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("channel connection status", () => {
  it("uses the authenticated canonical URL and decodes the channel registry", async () => {
    const fetchMock = respond([
      { platform: "feishu", connected: true },
      { platform: "slack", connected: false },
      { platform: "feishu", connected: false },
    ]);
    expect(await getChannelsStatus()).toEqual({
      channels: {
        feishu: { enabled: true, running: true },
        slack: { enabled: false, running: false },
      },
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/channels", {
      headers: { Authorization: "Bearer test-session" },
    });
  });

  it("retains legacy status responses", async () => {
    const status = {
      service_running: true,
      channels: {
        slack: { enabled: true, running: false },
      },
    };
    respond(status);
    expect(await getChannelsStatus()).toEqual(status);
  });

  it.each([{}, null, [{ platform: "slack" }], { channels: { slack: true } }])(
    "does not turn malformed responses into a disconnected success: %j",
    async (data) => {
      respond(data);
      await expect(getChannelsStatus()).rejects.toThrow("数据格式不完整");
    },
  );

  it("preserves authorization failures for recovery", async () => {
    respond({ detail: "unauthorized" }, 401);
    await expect(getChannelsStatus()).rejects.toThrow("HTTP 401");
  });
});
