import { describe, expect, it } from "vitest";

import {
  appendDesignNode,
  DEFAULT_DESIGN_CANVAS,
  designCanvasRunPrompt,
  parseDesignCanvas,
  tidyDesignCanvas,
} from "./canvas-model";

describe("design canvas model", () => {
  it("falls back safely for invalid persisted data", () => {
    expect(parseDesignCanvas("not json").nodes).toHaveLength(4);
    expect(parseDesignCanvas('{"version":2}').title).toBe("品牌发布创作流");
  });

  it("connects an appended node to the selected source", () => {
    const next = appendDesignNode(
      DEFAULT_DESIGN_CANVAS,
      {
        id: "plugin-1",
        kind: "plugin",
        title: "视频插件",
        description: "生成视频",
        x: 0,
        y: 0,
      },
      "brief",
    );
    expect(next.edges.at(-1)).toMatchObject({
      source: "brief",
      target: "plugin-1",
    });
  });

  it("tidies workflow columns and creates an executable prompt", () => {
    const tidy = tidyDesignCanvas(DEFAULT_DESIGN_CANVAS);
    const brief = tidy.nodes.find((node) => node.id === "brief")!;
    const output = tidy.nodes.find((node) => node.id === "output")!;
    expect(output.x).toBeGreaterThan(brief.x);
    expect(designCanvasRunPrompt(tidy)).toContain("创作画布");
    expect(designCanvasRunPrompt(tidy)).toContain("创作需求 → 视觉导演");
  });

  it("preserves a concrete ComfyUI workflow binding for Agent execution", () => {
    const document = appendDesignNode(DEFAULT_DESIGN_CANVAS, {
      id: "comfy-1",
      kind: "comfyui",
      title: "基础文生图",
      description: "运行本机工作流",
      binding: { type: "workflow", id: "text-to-image" },
      x: 0,
      y: 0,
    });
    expect(designCanvasRunPrompt(document)).toContain("workflow:text-to-image");
  });
});
