import type { HubPluginInfo } from "@/core/plugins/types";

export interface DesignMediaPlugin {
  id: string;
  tab: "image" | "video" | "audio";
  name: string;
  detail: string;
  badge: string;
}

/** Media entries represent enabled runtime plugins, never configured LLMs. */
export function designMediaPlugins(plugins: HubPluginInfo[]): DesignMediaPlugin[] {
  return plugins.flatMap((plugin) => {
    if (!plugin.enabled || !plugin.loaded || plugin.error) return [];
    const capabilities = plugin.capabilities.map((capability) => capability.name);
    const comfy = plugin.id === "comfyui_bridge" || capabilities.some((name) => name.startsWith("comfyui_bridge."));
    const clip = plugin.id === "clip_studio" || capabilities.some((name) => name.startsWith("clip_studio."));
    const media: DesignMediaPlugin["tab"][] = comfy ? ["image", "video", "audio"] : clip ? ["video"] : [];
    return media.map((tab) => ({
      id: `plugin:${plugin.id}:${tab}`,
      tab,
      name: `${plugin.display_name || plugin.name} · ${{ image: "图片", video: "视频", audio: "音频" }[tab]}`,
      detail: plugin.description,
      badge: "插件",
    }));
  });
}
