import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

// Dev-style backend base (relative /api through the proxy).
vi.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { installAuthFetchInterceptor } from "./fetch-interceptor";

const calls: Array<{ url: string; headers: Headers }> = [];
const mockFetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  calls.push({ url, headers: new Headers(init?.headers) });
  return Promise.resolve({ ok: true, status: 200 } as Response);
});

beforeAll(() => {
  // The interceptor captures whatever window.fetch is at install time as the
  // "original", so stub first, then install once (it's idempotent).
  window.fetch = mockFetch as typeof window.fetch;
  installAuthFetchInterceptor();
});

afterEach(() => {
  calls.length = 0;
  mockFetch.mockClear();
  localStorage.clear();
});

const authOf = (i = 0): string | null =>
  calls[i]?.headers.get("Authorization") ?? null;

describe("installAuthFetchInterceptor", () => {
  it("attaches the bearer token to backend /api requests", async () => {
    localStorage.setItem("octopus_auth_token", "tok123");
    await window.fetch("/api/cli-team/status");
    expect(authOf()).toBe("Bearer tok123");
  });

  it("does not leak the token to third-party URLs", async () => {
    localStorage.setItem("octopus_auth_token", "tok123");
    await window.fetch("https://evil.example.com/api/steal");
    expect(authOf()).toBeNull();
  });

  it("never overrides an Authorization header the caller set", async () => {
    localStorage.setItem("octopus_auth_token", "tok123");
    await window.fetch("/api/x", {
      headers: { Authorization: "Bearer caller-set" },
    });
    expect(authOf()).toBe("Bearer caller-set");
  });

  it("leaves requests untouched when there is no token", async () => {
    await window.fetch("/api/x");
    expect(authOf()).toBeNull();
  });

  it("ignores the legacy guest sentinel", async () => {
    localStorage.setItem("octopus_auth_token", "__guest__");
    await window.fetch("/api/x");
    expect(authOf()).toBeNull();
  });
});
