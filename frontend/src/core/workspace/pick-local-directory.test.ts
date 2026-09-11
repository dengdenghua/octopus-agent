import { afterEach, describe, expect, it, vi } from "vitest";
import { pickLocalDirectory } from "./pick-local-directory";

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://localhost:8310",
}));
vi.mock("@/core/auth/api", () => ({ authHeaders: () => ({}) }));

afterEach(() => {
  delete window.octopus;
  vi.unstubAllGlobals();
});

describe("directory picker cancellation", () => {
  it("does not start a request that was already cancelled", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const request = new AbortController();
    request.abort();
    await expect(
      pickLocalDirectory("", { signal: request.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("discards a native selection that finishes after cancellation", async () => {
    let finish!: (value: unknown) => void;
    Object.defineProperty(window, "octopus", {
      configurable: true,
      value: {
        dialog: {
          open: () =>
            new Promise((resolve) => {
              finish = resolve;
            }),
        },
      },
    });
    const request = new AbortController();
    const selection = pickLocalDirectory("", { signal: request.signal });
    request.abort();
    finish({ canceled: false, filePaths: ["D:/late"] });
    await expect(selection).rejects.toMatchObject({ name: "AbortError" });
  });
  it("keeps native cancellation distinct from an unavailable picker", async () => {
    Object.defineProperty(window, "octopus", {
      configurable: true,
      value: {
        dialog: { open: async () => ({ canceled: true, filePaths: [] }) },
      },
    });
    await expect(pickLocalDirectory()).resolves.toBeNull();
  });
});
