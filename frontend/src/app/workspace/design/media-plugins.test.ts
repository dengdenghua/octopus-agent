import { describe, expect, it } from "vitest";
import type { HubPluginInfo } from "@/core/plugins/types";
import { designMediaPlugins } from "./media-plugins";

const plugin = (id: string, patch: Partial<HubPluginInfo> = {}): HubPluginInfo => ({
  id, name: id, version: "1", description: "media", author: "Echo",
  capabilities: [], loaded: true, enabled: true, dir: "", dependencies: [], state: "loaded", ...patch,
});

describe("Design media plugin availability", () => {
  it("does not advertise missing, disabled or failed plugins", () => {
    expect(designMediaPlugins([])).toEqual([]);
    expect(designMediaPlugins([
      plugin("comfyui_bridge", { enabled: false }),
      plugin("clip_studio", { loaded: false }),
      plugin("comfyui_bridge", { error: "startup failed" }),
    ])).toEqual([]);
  });
  it("projects the supported media types of enabled plugins", () => {
    expect(designMediaPlugins([plugin("comfyui_bridge"), plugin("clip_studio")]).map(({ id }) => id)).toEqual([
      "plugin:comfyui_bridge:image", "plugin:comfyui_bridge:video", "plugin:comfyui_bridge:audio", "plugin:clip_studio:video",
    ]);
  });
});
