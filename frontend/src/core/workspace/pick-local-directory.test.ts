import { afterEach, describe, expect, it, vi } from "vitest";

import { pickLocalDirectory } from "./pick-local-directory";

describe("pickLocalDirectory", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the desktop bridge when available", async () => {
    const open = vi.fn().mockResolvedValue({
      canceled: false,
      filePaths: ["/Users/dangbei/Project"],
    });
    vi.stubGlobal("octopus", { dialog: { open } });

    await expect(pickLocalDirectory("/Users/dangbei")).resolves.toBe(
      "/Users/dangbei/Project",
    );
    expect(open).toHaveBeenCalledWith({
      properties: ["openDirectory", "createDirectory"],
      defaultPath: "/Users/dangbei",
    });
  });

  it("uses the local backend system picker in browser mode", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        success: true,
        path: "/Users/dangbei/Project",
        canceled: false,
        error: null,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(pickLocalDirectory("/Users/dangbei")).resolves.toBe(
      "/Users/dangbei/Project",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/fs/pick-directory?default_path=%2FUsers%2Fdangbei",
      ),
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("returns null when the user cancels", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          success: false,
          path: null,
          canceled: true,
          error: null,
        }),
      }),
    );

    await expect(pickLocalDirectory()).resolves.toBeNull();
  });
});
