// Build the existing standalone page into the source-checkout marketplace layout.
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build, loadConfigFromFile } from "vite";
import react from "@vitejs/plugin-react";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const packages = {
  projects: {
    name: "项目管理",
    description: "里程碑、风险与项目协作",
    route: "/workspace/projects",
    module: "projects",
    // Project records belong to the host, never to the removable UI package.
    data: [],
  },
  self_evolution: {
    name: "自进化",
    description: "双螺旋、候选基因、治理与审计",
    route: "/workspace/evolution",
    module: "evolution",
  },
  design: {
    name: "设计画布",
    description: "视觉创作、素材编排与设计工作流",
    route: "/workspace/design",
    module: "design",
  },
  narrative_studio: {
    name: "叙事工坊",
    description: "角色、世界观、剧情分支与正典协作",
    route: "/workspace/narrative",
    module: "narrative",
    version: "0.2.0",
    runtime: "narrative_studio",
    data: ["narrative-studio"],
  },
  "paper-trading": {
    name: "模拟炒股",
    description: "策略验证与模拟交易",
    route: "/workspace/paper-trading",
    module: "paper.trading",
    runtime: "paper_trading",
    data: [],
  },
  intelligence: {
    name: "订阅",
    description: "持续跟踪主题与情报",
    route: "/workspace/intelligence",
    module: "intelligence",
  },
  community: {
    name: "发现社区",
    description: "发现并复用社区工作流",
    route: "/workspace/community",
    module: "community",
  },
};
const packageId = process.argv[2] || "self_evolution";
if (!Object.hasOwn(packages, packageId))
  throw new Error(`Unsupported workbench: ${packageId}`);
const descriptor = packages[packageId];
const output = path.resolve(
  frontend,
  "../extensions/workbench-apps",
  packageId,
);
const loaded = await loadConfigFromFile(
  { command: "build", mode: "production" },
  path.join(frontend, "vite.config.ts"),
);
if (!loaded) throw new Error("Missing frontend Vite configuration");
const temporary = await mkdtemp(path.join(frontend, ".workbench-build-"));
try {
  await writeFile(
    path.join(temporary, "index.html"),
    `<!doctype html><html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>${descriptor.name}</title></head><body><div id="root"></div><script type="module" src="../src/workbenches/entries/${packageId}.tsx"></script></body></html>`,
  );
  await build({
    configFile: false,
    root: temporary,
    base: "./",
    publicDir: false,
    define: loaded.config.define,
    resolve: loaded.config.resolve,
    plugins: [react()],
    css: { postcss: frontend },
    build: { outDir: path.join(output, "dist"), emptyOutDir: true },
  });
  await mkdir(output, { recursive: true });
  await writeFile(
    path.join(output, "app.json"),
    JSON.stringify(
      {
        schema: "octopus.workbench_app.v1",
        id: packageId,
        name: descriptor.name,
        description: descriptor.description,
        route: descriptor.route,
        module_id: descriptor.module,
        version: descriptor.version || "1.0.0",
        runtime_plugin: descriptor.runtime,
        host_api: ">=0.2,<0.3",
        dependencies: [],
        entry: "dist/index.html",
        isolation: "iframe",
        // This trusted first-party page uses the host's existing auth interceptor.
        permissions: ["backend.api", "host.same_origin"],
        data_paths: descriptor.data || [],
      },
      null,
      2,
    ) + "\n",
  );
  console.log(`Workbench package ready: ${output}`);
} finally {
  if (path.dirname(temporary) !== frontend.replace(/[\\/]$/, "")) {
    throw new Error("Temporary build path escaped the frontend directory");
  }
  await rm(temporary, { recursive: true, force: true });
}
