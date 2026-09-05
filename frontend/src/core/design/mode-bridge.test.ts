import { describe, expect, it } from "vitest";

import {
  DEFAULT_DESIGN_CANVAS,
  createDramaSeriesCanvas,
} from "@/app/workspace/design/canvas-model";
import {
  buildDesignCanvasAgentContext,
  compactDesignResultText,
  designWorkspaceRoute,
  embeddedDesignChatRoute,
  freshDesignWorkspaceRoute,
} from "./mode-bridge";

describe("design mode bridge", () => {
  it("keeps selected nodes first and carries project scope", () => {
    const context = buildDesignCanvasAgentContext({
      document: DEFAULT_DESIGN_CANVAS,
      selectedNodeIds: ["output"],
      revision: 7,
      projectId: "project 1",
    });
    expect(context).toMatchObject({
      scope: "project",
      project_id: "project 1",
      revision: 7,
      selected_node_ids: ["output"],
    });
    expect(context.nodes[0]?.id).toBe("output");
  });

  it("builds a design workspace route for the current task", () => {
    expect(
      designWorkspaceRoute({ threadId: "thread/1", projectId: "project 1" }),
    ).toBe("/workspace/design?thread=thread%2F1&project=project+1");
  });

  it("starts a fresh design task while retaining only its creation scope", () => {
    expect(
      freshDesignWorkspaceRoute({
        currentSearch:
          "?thread=old&project=project%201&name=Launch&design_stage=storyboard",
        taskNonce: "fresh/1",
      }),
    ).toBe(
      "/workspace/design?project=project+1&name=Launch&new_task=fresh%2F1",
    );
  });

  it("forces embedded canvas conversations into design mode", () => {
    const route = embeddedDesignChatRoute({
      threadId: "thread/1",
      projectId: "project 1",
    });
    expect(route).toContain("/workspace/realtime/thread%2F1?");
    expect(route).toContain("embedded=design");
    expect(route).toContain("agent_mode=uxui");
  });

  it("grounds a selected workflow stage and freezes it in the task route", () => {
    const document = createDramaSeriesCanvas();
    const context = buildDesignCanvasAgentContext({
      document,
      selectedNodeIds: ["drama-storyboard"],
      revision: 3,
    });
    expect(context.active_stage_node_id).toBe("drama-storyboard");
    expect(context.workflow_stages[3]).toMatchObject({
      id: "storyboard",
      dependencies: ["asset-anchors"],
    });
    expect(
      embeddedDesignChatRoute({
        threadId: "thread-1",
        targetStageNodeId: context.active_stage_node_id,
      }),
    ).toContain("design_stage=drama-storyboard");
  });

  it("bounds result text before it is persisted as a canvas node", () => {
    expect(compactDesignResultText(`  ${"x".repeat(5000)}  `)).toHaveLength(
      4000,
    );
  });
});
