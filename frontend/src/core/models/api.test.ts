import { afterEach, expect, it, vi } from "vitest";
import { loadModels } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("merges the official service catalog with custom connections using distinct route ids", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.includes("/api/llm-models")
          ? {
              models: [
                { name: "qwen", entry_id: "my-api", selection_id: "api-route" },
              ],
            }
          : {
              data: [
                { id: "qwen", display_name: "极速", multiplier: "1x" },
                { id: "auto" },
              ],
            },
    })),
  );
  const models = await loadModels();
  expect(models).toHaveLength(2);
  expect(models[0]?.selection_id).toBe("api-route");
  expect(models[1]).toMatchObject({
    name: "official/qwen",
    selection_id: "official/qwen",
    entry_id: "official",
    display_name: "极速",
    official: true,
  });
});

it("keeps custom connections usable when the official service is disabled", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: url.includes("/api/llm-models"),
      json: async () => ({ models: [{ name: "api" }] }),
    })),
  );
  expect(await loadModels()).toEqual([{ name: "api" }]);
});
