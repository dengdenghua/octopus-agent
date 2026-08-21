/// <reference types="vitest" />
import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { createHash } from "node:crypto";
import { fileURLToPath } from "url";
import { createRequire } from "module";
import path from "path";
import fs from "fs";

import { WEB_BUILD_DEDUPLICATED_PET_ASSETS } from "./config/public-asset-dedup";

const require = createRequire(import.meta.url);
const vitePackage = require("vite/package.json");

function sha256File(filename: string): string {
  return createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
}

function omitDuplicatePetAssetsFromWebBuild(): Plugin {
  let rootDir = "";
  let outputDir = "";

  return {
    name: "octopus-omit-duplicate-pet-authoring-assets",
    apply: "build",
    configResolved(config) {
      rootDir = config.root;
      outputDir = path.resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      // Both source assets remain in the repository. A future edit that makes
      // either copy diverge fails the build instead of silently dropping a
      // newly-used asset from the renderer package.
      for (const asset of WEB_BUILD_DEDUPLICATED_PET_ASSETS) {
        const publicSource = path.resolve(rootDir, "public", asset.publicPath);
        const canonicalSource = path.resolve(rootDir, asset.canonicalPath);
        if (!fs.existsSync(publicSource) || !fs.existsSync(canonicalSource)) {
          throw new Error(
            `Cannot deduplicate missing pet asset: ${asset.publicPath}`,
          );
        }
        if (
          fs.statSync(publicSource).size !==
            fs.statSync(canonicalSource).size ||
          sha256File(publicSource) !== sha256File(canonicalSource)
        ) {
          throw new Error(
            `Pet asset copies diverged; keep the web copy until its loading contract is explicit: ${asset.publicPath}`,
          );
        }
        fs.rmSync(path.resolve(outputDir, asset.publicPath), { force: true });
      }
    },
  };
}

const gatewayTarget =
  process.env.OCTOPUS_INTERNAL_GATEWAY_BASE_URL ||
  `http://127.0.0.1:${process.env.GATEWAY_PORT || "8000"}`;

function packageNameFromNodeModule(id: string): string | null {
  const normalized = id.replace(/\\/g, "/");
  const marker = "/node_modules/";
  const markerIndex = normalized.lastIndexOf(marker);
  if (markerIndex < 0) return null;
  const rest = normalized.slice(markerIndex + marker.length);
  const parts = rest.split("/");
  if (parts[0]?.startsWith("@")) {
    return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : null;
  }
  return parts[0] || null;
}

function safeChunkName(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-").replace(/-+/g, "-");
}

function chunkFileStem(id: string): string {
  const filename = id.replace(/\\/g, "/").split("/").pop() ?? "chunk";
  return filename.replace(/\.[cm]?js$/, "");
}

const proxyConfig = {
  "/api/files/stream": {
    target: gatewayTarget,
    changeOrigin: true,
    secure: false,
    timeout: 0,
    proxyTimeout: 0,
    on: {
      proxyReq: (proxyReq: any) => {
        proxyReq.setHeader("Connection", "keep-alive");
        proxyReq.setHeader("Cache-Control", "no-cache");
      },
    },
  },
  "/api/preview/stream": {
    target: gatewayTarget,
    changeOrigin: true,
    secure: false,
    timeout: 0,
    proxyTimeout: 0,
    on: {
      proxyReq: (proxyReq: any) => {
        proxyReq.setHeader("Connection", "keep-alive");
        proxyReq.setHeader("Cache-Control", "no-cache");
      },
    },
  },
  "/api": {
    target: gatewayTarget,
    changeOrigin: true,
    secure: false,
    timeout: 0,
    proxyTimeout: 0,
    ws: true,
    on: {
      proxyReq: (proxyReq: any, req: any, _res: any) => {
        if (req.headers.accept?.includes("text/event-stream")) {
          proxyReq.setHeader("Connection", "keep-alive");
          proxyReq.setHeader("Cache-Control", "no-cache");
        }
      },
      proxyRes: (proxyRes: any, req: any, _res: any) => {
        if (
          req.headers.accept?.includes("text/event-stream") ||
          (proxyRes.headers["content-type"] || "").includes("text/event-stream")
        ) {
          proxyRes.headers["cache-control"] = "no-cache";
          proxyRes.headers["x-accel-buffering"] = "no";
        }
      },
      error: (_err: any, _req: any, res: any) => {
        if (!res.headersSent) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "proxy_error" }));
        }
      },
    },
  },
  "/v1": {
    target: gatewayTarget,
    changeOrigin: true,
    ws: true,
  },
  "/media": {
    target: gatewayTarget,
    changeOrigin: true,
  },
  "/.well-known": {
    target: gatewayTarget,
    changeOrigin: true,
  },
  "/.a2a": {
    target: gatewayTarget,
    changeOrigin: true,
  },
};

function buildTracePlugin() {
  const tracePath = path.resolve("vite-transform-trace.log");
  return {
    name: "octopus-build-trace",
    buildStart() {
      fs.writeFileSync(tracePath, "");
    },
    transform(_code: string, id: string) {
      fs.appendFileSync(tracePath, `${id}\n`);
      return null;
    },
  };
}

export default defineConfig({
  base: "./",
  define: {
    __VITE_VERSION__: JSON.stringify(vitePackage.version),
  },
  plugins: [
    omitDuplicatePetAssetsFromWebBuild(),
    ...(process.env.OCTOPUS_BUILD_TRACE === "1" ? [buildTracePlugin()] : []),
    react(),
    // Build-size audit capability. Gated behind an env var so ordinary
    // `pnpm build` output is unaffected. Run a report with:
    //   OCTOPUS_VISUALIZER=1 pnpm build
    // and open `dist/stats.html` (or `--report` for rollup console output).
    ...(process.env.OCTOPUS_VISUALIZER === "1"
      ? [
          visualizer({
            filename: "dist/stats.html",
            gzipSize: true,
            brotliSize: true,
          }),
        ]
      : []),
  ],
  resolve: {
    alias: [
      {
        find: "@",
        replacement: fileURLToPath(new URL("./src", import.meta.url)),
      },
      {
        find: "motion/react",
        replacement: fileURLToPath(
          new URL("./src/lib/motion-shim.tsx", import.meta.url),
        ),
      },
      {
        find: "mermaid-real",
        replacement: fileURLToPath(
          new URL(
            "./node_modules/mermaid/dist/mermaid.esm.min.mjs",
            import.meta.url,
          ),
        ),
      },
      // ``mermaid`` is aliased to a local shim because the upstream
      // package ships a large ESM bundle with worker-based parsing
      // we don't need in the workspace UI. ``resolve.alias`` covers
      // both dev and build; no pre-resolve plugin required.
      {
        find: "mermaid",
        replacement: fileURLToPath(
          new URL("./src/lib/mermaid-shim.ts", import.meta.url),
        ),
      },
      // ``shiki`` (bare specifier only — subpaths like "shiki/langs/*"
      // must keep resolving to the real package) is aliased to a local
      // shim that swaps the full bundle (~200 language chunks + the
      // Oniguruma WASM engine) for a JS-regex-engine core highlighter
      // with a curated language whitelist. See src/lib/shiki-shim.ts.
      {
        find: /^shiki$/,
        replacement: fileURLToPath(
          new URL("./src/lib/shiki-shim.ts", import.meta.url),
        ),
      },
    ],
  },
  server: {
    // PORT is honoured so a supervisor that assigns a free port (the IDE
    // preview pane) can run alongside a dev server already holding 3000.
    // FRONTEND_PORT stays the explicit override and wins.
    port: parseInt(process.env.FRONTEND_PORT || process.env.PORT || "3000"),
    host: "0.0.0.0",
    proxy: proxyConfig,
  },
  preview: {
    port: parseInt(process.env.FRONTEND_PORT || process.env.PORT || "3000"),
    host: "0.0.0.0",
    proxy: proxyConfig,
  },
  build: {
    outDir: "dist",
    sourcemap: process.env.OCTOPUS_SOURCEMAP === "1" ? "hidden" : false,
    reportCompressedSize: true,
    // Most heavy engines are split below 800 KB. Mermaid's
    // architectureDiagram implementation is a single upstream lazy chunk
    // (~1.35 MB minified, ~350 KB gzip), so keep the warning threshold just
    // above that known on-demand boundary while still catching larger chunks.
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const pkg = packageNameFromNodeModule(id);

          if (
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react/") ||
            id.includes("node_modules/react-router-dom")
          ) {
            return "react-vendor";
          }
          if (id.includes("node_modules/@radix-ui/")) {
            return "ui-radix";
          }

          if (pkg === "@uiw/react-codemirror") {
            return "codemirror-react";
          }
          if (pkg?.startsWith("@uiw/codemirror-theme-")) {
            return "codemirror-themes";
          }
          if (pkg?.startsWith("@codemirror/lang-")) {
            return safeChunkName(pkg.replace("@", ""));
          }
          if (pkg === "@codemirror/language-data") {
            return "codemirror-language-data";
          }
          if (pkg === "@codemirror/merge") {
            return "codemirror-merge";
          }
          if (pkg?.startsWith("@codemirror/")) {
            return "codemirror-core";
          }
          if (pkg === "codemirror") {
            return "codemirror-core";
          }
          if (pkg?.startsWith("@lezer/")) {
            return safeChunkName(pkg.replace("@", ""));
          }
          if (id.includes("node_modules/@tanstack/")) {
            return "query-virtual";
          }
          if (pkg === "lodash-es") {
            return "lodash-es";
          }
          if (pkg === "streamdown") {
            return "markdown-streamdown";
          }
          if (
            pkg?.startsWith("rehype-") ||
            pkg?.startsWith("remark-") ||
            pkg === "unified" ||
            pkg === "hast" ||
            pkg === "unist-util-visit"
          ) {
            return "markdown-plugins";
          }
          if (pkg?.startsWith("d3")) {
            return "mermaid-d3";
          }
          if (
            pkg === "cytoscape" ||
            pkg === "dagre-d3-es" ||
            pkg === "elkjs" ||
            pkg === "khroma"
          ) {
            return "mermaid-layout";
          }
          if (id.includes("/node_modules/mermaid/dist/chunks/")) {
            return `mermaid-${safeChunkName(chunkFileStem(id))}`;
          }
          if (pkg === "mermaid") {
            return "mermaid";
          }
          if (id.includes("node_modules/katex/")) {
            return "katex";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["node_modules/**", "dist/**", "e2e/**"],
    coverage: {
      provider: "v8",
      // Ratchet thresholds — set slightly below current levels to prevent
      // regression while allowing incremental improvement over time.
      // Goal: ratchet up until we reach 80/75/80/80.
      // Current actual (2026-08-03): lines 51.03 / branches 48.59 /
      // functions 38.29 / statements 50.01.
      thresholds: {
        lines: 51,
        branches: 48,
        functions: 38,
        statements: 50,
      },
    },
  },
});
