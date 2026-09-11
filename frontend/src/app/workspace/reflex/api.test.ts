import { afterEach, expect, it, vi } from "vitest";
import { reflexFetch } from "./api";

vi.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({ Authorization: "Bearer reflex-test" }),
}));
afterEach(() => vi.unstubAllGlobals());

it("authenticates rule requests while preserving caller headers and options", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ updated: true }) });
  vi.stubGlobal("fetch", fetchMock);
  const body = JSON.stringify({ weight: 1 });
  await reflexFetch("/api/reflex/rules/test", {
    method: "PATCH",
    headers: new Headers({ "Content-Type": "application/json" }),
    body,
  });
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toBe("/api/reflex/rules/test");
  expect(init).toMatchObject({ method: "PATCH", body });
  expect(init.headers.get("Authorization")).toBe("Bearer reflex-test");
  expect(init.headers.get("Content-Type")).toBe("application/json");
});

it("surfaces a real permission denial instead of returning empty metrics", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({ ok: false, status: 403, statusText: "Forbidden" }),
  );
  await expect(reflexFetch("/api/reflex/stats")).rejects.toThrow("403");
});
