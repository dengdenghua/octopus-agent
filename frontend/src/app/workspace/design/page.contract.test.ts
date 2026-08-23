import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const pageSource = readFileSync(
  join(process.cwd(), "src/app/workspace/design/page.tsx"),
  "utf8",
);
const routerSource = readFileSync(
  join(process.cwd(), "src/router.tsx"),
  "utf8",
);
const catalogSource = readFileSync(
  join(process.cwd(), "src/core/modules/catalog.ts"),
  "utf8",
);
const designCatalogSource = readFileSync(
  join(process.cwd(), "src/app/workspace/design/design-catalog.ts"),
  "utf8",
);
const directorSource = readFileSync(
  join(process.cwd(), "src/app/workspace/design/director-stage.tsx"),
  "utf8",
);
const comfyEditorSource = readFileSync(
  join(process.cwd(), "src/app/workspace/design/comfy-workflow-editor.tsx"),
  "utf8",
);
const projectsSource = readFileSync(
  join(process.cwd(), "src/app/workspace/projects/page.tsx"),
  "utf8",
);

describe("Octopus Design platform contract", () => {
  it("keeps freeform and workflow in one canvas surface", () => {
    expect(pageSource).toContain('"freeform"');
    expect(pageSource).toContain('"workflow"');
    expect(pageSource).toContain('data-testid="design-infinite-canvas"');
    expect(pageSource).toContain("<EdgeLayer document={document}");
  });

  it("matches the creation-home hierarchy before entering the canvas", () => {
    expect(pageSource).toContain("function DesignHomeView");
    expect(pageSource).toContain("属于你的多模态 Agent 团队");
    expect(pageSource).toContain("描述你要生成的内容");
    expect(pageSource).toContain("进入当前创作画布");
    expect(pageSource).toContain('projectId ? "canvas" : "home"');
  });

  it("binds real skills and plugins and compiles the graph for AI execution", () => {
    expect(pageSource).toContain("useSkills()");
    expect(pageSource).toContain("usePlugins()");
    expect(pageSource).toContain("useAgents()");
    expect(pageSource).toContain("designCanvasRunPrompt(document)");
    expect(pageSource).toContain('embedded: "design"');
    expect(pageSource).toContain(
      "#/workspace/realtime/new?${params.toString()}",
    );
    expect(pageSource).toContain("setEmbeddedChatUrl");
  });

  it("uses the MiniMax-style on-demand node menu and workspace layouts", () => {
    expect(pageSource).toContain("添加节点");
    expect(pageSource).toContain("对话 + 画布");
    expect(pageSource).toContain("仅对话");
    expect(pageSource).toContain("仅画布");
    expect(pageSource).toContain("ComfyUI 工作流");
  });

  it("ships a functional embedded 3D director surface", () => {
    expect(pageSource).toContain("<DirectorStage");
    expect(directorSource).toContain("new THREE.WebGLRenderer");
    expect(directorSource).toContain("makeMannequin");
    expect(directorSource).toContain("makeDeclarativeModel");
    expect(directorSource).toContain("程序化模型");
    expect(directorSource).toContain("场景道具");
    expect(directorSource).toContain("makeProp");
    expect(directorSource).toContain("导出图片");
    expect(directorSource).toContain("添加路径");
  });

  it("registers a first-class workspace route and module", () => {
    expect(routerSource).toContain('path="design" element={<DesignPage />}');
    expect(catalogSource).toContain('id: "design"');
    expect(catalogSource).toContain('to: "/workspace/design"');
  });

  it("scopes a canvas to its Octopus project", () => {
    expect(pageSource).toContain("useSearchParams()");
    expect(pageSource).toContain(
      "`${DESIGN_CANVAS_STORAGE_KEY}:project:${projectId}`",
    );
    expect(pageSource).toContain("项目 · {projectName || projectId}");
    expect(projectsSource).toContain("/workspace/design?project=");
    expect(projectsSource).toContain("创作画布");
    expect(pageSource).toContain(
      "/api/design/projects/${encodeURIComponent(projectId)}/canvas",
    );
    expect(pageSource).toContain(
      "expected_revision: serverRevisionRef.current",
    );
    expect(pageSource).toContain("版本冲突");
  });

  it("labels runnable and dependency-gated ComfyUI templates honestly", () => {
    expect(pageSource).toContain('workflow.availability === "bundled"');
    expect(pageSource).toContain("已内置");
    expect(pageSource).toContain("需依赖");
    expect(pageSource).toContain("/api/design/comfyui/queue");
    expect(pageSource).toContain("/api/design/comfyui/dependencies");
    expect(pageSource).toContain("/api/design/comfyui/history/");
    expect(pageSource).toContain("直接运行");
    expect(pageSource).toContain("生成完成");
  });

  it("exposes the expanded original creative skill collection", () => {
    expect(pageSource).toContain("CREATIVE_SKILL_COLLECTION");
    expect(designCatalogSource).toContain("多模态视频提示词导演");
    expect(designCatalogSource).toContain("数字产品宣传片");
    expect(designCatalogSource).toContain("IP 潮玩六宫格动态海报");
  });

  it("previews Director Stage camera, object and character timeline tracks", () => {
    expect(directorSource).toContain("samplePath");
    expect(directorSource).toContain("evaluateTimeline");
    expect(directorSource).toContain('track.type === "camera_path"');
    expect(directorSource).toContain('track.type === "object_path"');
    expect(directorSource).toContain('track.type === "character_animation"');
    expect(directorSource).toContain("motionPoseAt");
    expect(directorSource).toContain('aria-label="时间线播放位置"');
  });

  it("embeds a persistent native Comfy workflow editor", () => {
    expect(pageSource).toContain("<ComfyWorkflowEditor");
    expect(pageSource).toContain("返回 Octopus 编辑器");
    expect(comfyEditorSource).toContain("ui: { positions }");
    expect(comfyEditorSource).toContain("expected_revision: revision");
    expect(comfyEditorSource).toContain(
      'window.addEventListener("pointermove"',
    );
    expect(comfyEditorSource).toContain("/api/design/comfyui/queue");
    expect(comfyEditorSource).toContain("/api/design/comfyui/object-info");
    expect(comfyEditorSource).toContain("添加 ComfyUI 节点");
    expect(comfyEditorSource).toContain("版本冲突，请重新打开");
  });
});
